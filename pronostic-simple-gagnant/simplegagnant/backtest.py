"""Backtest chronologique (walk-forward) et mesures de rentabilité.

Principe : on avance dans le temps par « plis » (une semaine par défaut).
Pour chaque pli, le modèle est ré-entraîné UNIQUEMENT sur les jours qui
précèdent, puis appliqué aux courses du pli, qu'il n'a jamais vues. Les
paris sont simulés avec le rapport réellement payé (prélèvement inclus).

Toutes les références (favori systématique, hasard, marché seul) sont
calculées sur exactement les mêmes courses de test.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .clogit import log_vraisemblance
from .config import Config, ConfigMise, ConfigSelection
from .model import ModeleDeuxEtapes
from .value import (esperance, estimer_facteur_rapport, mises_course,
                    rapport_attendu, selectionner, tranche_cote)

COLS_SORTIE = ["date", "heure_depart", "course_id", "hippodrome", "discipline", "num", "cheval",
               "cote_decision", "cote_finale", "rapport_gagnant", "gagnant", "position", "q_dec", "taille"]


# --------------------------------------------------------------------------- #
# Walk-forward                                                                 #
# --------------------------------------------------------------------------- #
@dataclass
class ResultatWalkForward:
    predictions: pd.DataFrame
    plis: pd.DataFrame
    coefficients: list


def walk_forward(df: pd.DataFrame, cfg: Config, cols_fond: list[str], cols_marche: list[str],
                 verbeux: bool = True) -> ResultatWalkForward:
    bt = cfg.backtest
    jours = np.sort(df["date"].unique())
    debut = pd.Timestamp(jours[0]) + pd.Timedelta(days=bt.jours_entrainement_min)
    fin = pd.Timestamp(jours[-1]) + pd.Timedelta(days=1)
    bornes = list(pd.date_range(debut, fin, freq=f"{bt.jours_par_pli}D"))
    if bornes[-1] < fin:
        bornes.append(fin)

    preds, plis, coefs = [], [], []
    for k, (d0, d1) in enumerate(zip(bornes[:-1], bornes[1:])):
        train = df[df["date"] < d0]
        if bt.fenetre == "glissante":
            train = train[train["date"] >= d0 - pd.Timedelta(days=bt.jours_fenetre_glissante)]
        test = df[(df["date"] >= d0) & (df["date"] < d1)]
        if test.empty or train["course_id"].nunique() < 200:
            continue
        complet = ModeleDeuxEtapes(cols_fond, cols_marche, cfg.modele).fit(train)
        marche = ModeleDeuxEtapes([], cols_marche, cfg.modele, utiliser_fondamental=False).fit(train)
        facteurs = estimer_facteur_rapport(train)
        seuil, _ = justifier_cote_min(train, d0, cfg.selection.cote_min_plancher, cfg.selection.cote_min_plafond)
        plafond = (justifier_cote_max(train, d0, cfg.selection.cote_max_plancher, cfg.selection.cote_max_plafond)
                   if cfg.selection.cote_max_auto else cfg.selection.cote_max)

        p = test[[c for c in COLS_SORTIE if c in test.columns]].copy()
        pc = complet.predict(test)
        p["p_modele"] = pc["p_modele"].to_numpy()
        p["p_fond"] = pc["p_fond"].to_numpy() if "p_fond" in pc else np.nan
        p["p_marche"] = marche.predict(test)["p_modele"].to_numpy()
        p["rapport_attendu"] = rapport_attendu(test, facteurs).to_numpy()
        p["ev"] = esperance(p["p_modele"], p["rapport_attendu"], bt.commission_gains) + bt.remise_mises
        p["ev_marche"] = esperance(p["p_marche"], p["rapport_attendu"], bt.commission_gains) + bt.remise_mises
        p["cote_min_pli"] = seuil
        p["cote_max_pli"] = plafond
        p["pli"] = k
        preds.append(p)
        plis.append({"pli": k, "debut_test": d0.date(), "fin_test": (d1 - pd.Timedelta(days=1)).date(),
                     "courses_entrainement": train["course_id"].nunique(),
                     "courses_test": test["course_id"].nunique(), "cote_min_apprise": seuil,
                     "cote_max_appliquee": plafond})
        coefs.append({"pli": k, **complet.coefficients()})
        if verbeux:
            print(f"  pli {k:>3} : test {d0.date()} → {(d1 - pd.Timedelta(days=1)).date()} "
                  f"({test['course_id'].nunique()} courses, entraînement {train['course_id'].nunique()}, "
                  f"cotes retenues [{seuil:g} ; {plafond:g}])")
    if not preds:
        raise ValueError("Pas assez de données pour un seul pli : réduire jours_entrainement_min.")
    return ResultatWalkForward(pd.concat(preds), pd.DataFrame(plis), coefs)


# --------------------------------------------------------------------------- #
# Simulation des paris                                                         #
# --------------------------------------------------------------------------- #
def simuler(pred: pd.DataFrame, sel: ConfigSelection, mise: ConfigMise, col_p: str = "p_modele",
            col_ev: str = "ev", commission: float = 0.0, remise: float = 0.0) -> pd.DataFrame:
    """Rejoue les paris course par course dans l'ordre chronologique."""
    d = pred.copy()
    d["ev"] = d[col_ev]
    d = selectionner(d, sel, col_p=col_p)
    paris = d[d["pari"] == 1].copy()
    if paris.empty:
        return paris.assign(mise=[], retour=[], profit=[], bankroll=[])
    tri = ["date", "heure_depart", "course_id"] if "heure_depart" in paris.columns else ["date", "course_id"]
    paris = paris.sort_values(tri, kind="mergesort")
    if col_p != "p_modele":
        paris["p_modele"] = paris[col_p]
    bankroll = mise.bankroll_initiale
    mises_all, bk = np.zeros(len(paris)), np.zeros(len(paris))
    # Retour pour 1 misé : rapport payé (commission éventuelle sur le gain net)
    # + remise éventuelle sur la mise, gagnante ou non.
    gains_unitaires = np.where(paris["gagnant"].to_numpy() == 1,
                               1.0 + (paris["rapport_gagnant"].fillna(0).to_numpy() - 1.0) * (1 - commission), 0.0) + remise
    pos = 0
    for _, grp in paris.groupby("course_id", sort=False):
        n = len(grp)
        m = mises_course(grp, bankroll, mise, col_p="p_modele")
        r = m * gains_unitaires[pos:pos + n]
        bankroll += r.sum() - m.sum()
        mises_all[pos:pos + n] = m
        bk[pos:pos + n] = bankroll
        pos += n
    paris["mise"] = mises_all
    paris["retour"] = mises_all * gains_unitaires
    paris["profit"] = paris["retour"] - paris["mise"]
    paris["bankroll"] = bk
    return paris[paris["mise"] > 0]


def _tirage_un_par_course(d: pd.DataFrame, rng: np.random.Generator | None) -> np.ndarray:
    """Positions (iloc) d'un partant tiré uniformément dans chaque course."""
    rng = rng or np.random.default_rng()
    codes, uniq = pd.factorize(d["course_id"])
    ordre = np.argsort(codes, kind="mergesort")
    tailles = np.bincount(codes)
    debuts = np.r_[0, np.cumsum(tailles)[:-1]]
    choix = debuts + (rng.random(len(tailles)) * tailles).astype(int)
    return np.sort(ordre[choix])


def paris_reference(pred: pd.DataFrame, type_: str, sel: ConfigSelection | None = None,
                    rng: np.random.Generator | None = None, remise: float = 0.0) -> pd.DataFrame:
    """Stratégies naïves, mise fixe de 1 :
    favori    : le favori (plus petite cote de décision) de chaque course
    hasard    : un partant tiré au hasard dans chaque course
    hasard_plage : un partant tiré au hasard parmi ceux dans [cote_min ; cote_max]
    tous_plage   : tous les partants dans [cote_min ; cote_max]
    """
    d = pred
    if type_ == "favori":
        idx = d.groupby("course_id")["cote_decision"].idxmin()
        b = d.loc[idx]
    elif type_ == "hasard":
        b = d.iloc[_tirage_un_par_course(d, rng)]
    elif type_ in ("hasard_plage", "tous_plage"):
        seuil = d["cote_min_pli"] if (sel.cote_min_auto and "cote_min_pli" in d.columns) else sel.cote_min
        plafond = d["cote_max_pli"] if (sel.cote_max_auto and "cote_max_pli" in d.columns) else sel.cote_max
        dd = d[(d["cote_decision"] >= seuil) & (d["cote_decision"] <= plafond)]
        b = dd if type_ == "tous_plage" else dd.iloc[_tirage_un_par_course(dd, rng)]
    else:
        raise ValueError(type_)
    b = b.sort_values(["date", "course_id"]).copy()
    b["mise"] = 1.0
    b["retour"] = np.where(b["gagnant"] == 1, b["rapport_gagnant"].fillna(0), 0.0) + remise
    b["profit"] = b["retour"] - b["mise"]
    b["bankroll"] = 100 + b["profit"].cumsum()
    return b


# --------------------------------------------------------------------------- #
# Métriques                                                                    #
# --------------------------------------------------------------------------- #
def _drawdown_max(cumul: np.ndarray) -> float:
    if len(cumul) == 0:
        return 0.0
    pic = np.maximum.accumulate(np.r_[0.0, cumul])
    return float(np.max(pic - np.r_[0.0, cumul]))


def _serie_perdante(gagnant: np.ndarray) -> int:
    best = cur = 0
    for g in gagnant:
        cur = 0 if g else cur + 1
        best = max(best, cur)
    return best


def bootstrap_roi(paris: pd.DataFrame, n: int = 5000, graine: int = 0) -> tuple[float, float, float]:
    """IC 90 % du ROI par rééchantillonnage des JOURS (les paris d'un même jour
    sont corrélés : rééchantillonner les paris un par un serait trop optimiste).
    Retourne (borne basse 5 %, borne haute 95 %, proba ROI <= 0)."""
    if paris.empty:
        return (np.nan, np.nan, np.nan)
    j = paris.groupby("date").agg(m=("mise", "sum"), p=("profit", "sum"))
    rng = np.random.default_rng(graine)
    idx = rng.integers(0, len(j), size=(n, len(j)))
    m = j["m"].to_numpy()[idx].sum(axis=1)
    p = j["p"].to_numpy()[idx].sum(axis=1)
    roi = p / np.where(m > 0, m, np.nan)
    return float(np.nanpercentile(roi, 5)), float(np.nanpercentile(roi, 95)), float(np.nanmean(roi <= 0))


def metriques(paris: pd.DataFrame, nom: str, n_boot: int = 5000, bankroll_initiale: float | None = None) -> dict:
    if paris.empty:
        return {"strategie": nom, "paris": 0}
    mise = paris["mise"].sum()
    profit = paris["profit"].sum()
    cumul = paris["profit"].cumsum().to_numpy()
    g = paris["gagnant"].to_numpy() == 1
    lo, hi, p0 = bootstrap_roi(paris, n_boot)
    out = {
        "strategie": nom,
        "paris": int(len(paris)),
        "courses_jouees": int(paris["course_id"].nunique()),
        "mise_totale": round(float(mise), 2),
        "profit": round(float(profit), 2),
        "roi_pct": round(100 * profit / mise, 2),
        "roi_ic90_pct": f"[{100 * lo:.1f} ; {100 * hi:.1f}]",
        "proba_roi_negatif": round(p0, 3),
        "taux_reussite_pct": round(100 * g.mean(), 2),
        "cote_moy_paris": round(float(paris["cote_decision"].mean()), 2),
        "rapport_moy_gagnants": round(float(paris.loc[g, "rapport_gagnant"].mean()), 2) if g.any() else np.nan,
        "drawdown_max": round(_drawdown_max(cumul), 2),
        "serie_perdante_max": _serie_perdante(g),
    }
    if bankroll_initiale:
        bk = np.r_[bankroll_initiale, paris["bankroll"].to_numpy()]
        pic = np.maximum.accumulate(bk)
        out["bankroll_finale"] = round(float(bk[-1]), 2)
        out["drawdown_max_pct"] = round(float(100 * np.max((pic - bk) / pic)), 2)
    return out


def comparer(pred: pd.DataFrame, cfg: Config, verbeux: bool = True) -> tuple[pd.DataFrame, dict]:
    """Toutes les stratégies sur les mêmes courses de test."""
    bt, sel = cfg.backtest, cfg.selection
    fixe = copy.deepcopy(cfg.mise); fixe.methode = "fixe"; fixe.mise_fixe = 1.0
    kelly = copy.deepcopy(cfg.mise); kelly.methode = "kelly"
    registre = {}
    kw = dict(commission=bt.commission_gains, remise=bt.remise_mises)
    nom_kelly = f"Modèle value — Kelly {cfg.mise.fraction_kelly:g}"
    registre["Modèle value — mise fixe"] = simuler(pred, sel, fixe, **kw)
    registre[nom_kelly] = simuler(pred, sel, kelly, **kw)
    registre["Marché seul value — mise fixe"] = simuler(pred, sel, fixe, col_p="p_marche", col_ev="ev_marche", **kw)
    registre["Favori systématique"] = paris_reference(pred, "favori", remise=bt.remise_mises)
    registre["Tous les chevaux dans la plage de cotes"] = paris_reference(pred, "tous_plage", sel, remise=bt.remise_mises)

    lignes = [metriques(registre[k], k, bt.n_bootstrap,
                        cfg.mise.bankroll_initiale if "Kelly" in k else None) for k in registre]

    rng = np.random.default_rng(bt.graine)
    for type_, nom in [("hasard", "Hasard (1 cheval/course)"), ("hasard_plage", "Hasard dans la plage de cotes")]:
        rois, ex = [], None
        for _ in range(bt.n_simulations_hasard):
            b = paris_reference(pred, type_, sel, rng, remise=bt.remise_mises)
            rois.append(b["profit"].sum() / b["mise"].sum())
            ex = b if ex is None else ex
        m = metriques(ex, nom, n_boot=200)
        m["roi_pct"] = round(100 * float(np.mean(rois)), 2)
        m["roi_ic90_pct"] = f"[{100 * np.percentile(rois, 5):.1f} ; {100 * np.percentile(rois, 95):.1f}] (simulations)"
        m["proba_roi_negatif"] = round(float(np.mean(np.array(rois) <= 0)), 3)
        lignes.append(m)
        registre[nom] = ex
    return pd.DataFrame(lignes), registre


# --------------------------------------------------------------------------- #
# Diagnostics                                                                  #
# --------------------------------------------------------------------------- #
def qualite_probabilites(pred: pd.DataFrame, n_boot: int = 2000, graine: int = 0) -> pd.DataFrame:
    """Log-vraisemblance moyenne par course (plus haut = meilleur) sur le test.

    Le test décisif : le modèle complet doit battre le « marché seul ».
    L'intervalle de l'écart est obtenu par bootstrap des jours."""
    d = pred.sort_values(["date", "course_id"], kind="mergesort")
    y, g = d["gagnant"].to_numpy(), d["course_id"].to_numpy()
    lignes = []
    for col, nom in [("q_dec", "Marché brut (1/cote normalisé)"), ("p_marche", "Marché recalibré"),
                     ("p_fond", "Fondamental seul (sans cotes)"), ("p_modele", "Modèle complet")]:
        if col in d and d[col].notna().all():
            lignes.append({"modele": nom, "logvrais_par_course": round(log_vraisemblance(d[col].to_numpy(), y, g), 5)})
    out = pd.DataFrame(lignes)
    # Écart de log-vraisemblance du modèle complet par rapport à chaque version
    # du marché, agrégé par jour puis bootstrap des jours (IC 90 %).
    rng = np.random.default_rng(graine)
    gag = d[d["gagnant"] == 1]
    for ref, cle in [("p_marche", "ecart_vs_marche_recalibre"), ("q_dec", "ecart_vs_marche_brut")]:
        dif_j = (np.log(gag["p_modele"].clip(1e-12)) - np.log(gag[ref].clip(1e-12))).groupby(gag["date"]).agg(["sum", "count"])
        idx = rng.integers(0, len(dif_j), size=(n_boot, len(dif_j)))
        dif = dif_j["sum"].to_numpy()[idx].sum(1) / dif_j["count"].to_numpy()[idx].sum(1)
        out.attrs[cle] = (float(dif_j["sum"].sum() / dif_j["count"].sum()),
                          float(np.percentile(dif, 5)), float(np.percentile(dif, 95)))
    return out


def table_par_tranche(pred: pd.DataFrame, col_p: str = "q_dec") -> pd.DataFrame:
    """Biais favori-outsider : victoires réelles / attendues et ROI d'un pari
    sur TOUS les chevaux de la tranche (rapports réels)."""
    d = pred.assign(tranche=tranche_cote(pred["cote_decision"]))
    d["retour"] = np.where(d["gagnant"] == 1, d["rapport_gagnant"].fillna(0), 0.0)
    t = d.groupby("tranche", observed=True).agg(
        partants=("gagnant", "size"), victoires=("gagnant", "sum"),
        attendues=(col_p, "sum"), retour=("retour", "sum"))
    t["reel_sur_attendu"] = (t["victoires"] / t["attendues"]).round(3)
    t["roi_tous_pct"] = (100 * (t["retour"] / t["partants"] - 1)).round(1)
    t["attendues"] = t["attendues"].round(1)
    return t.drop(columns=["retour"]).reset_index()


def justifier_cote_min(F: pd.DataFrame, avant: pd.Timestamp, plancher: float = 2.0,
                       plafond: float = 6.0) -> tuple[float, pd.DataFrame]:
    """Seuil de cote minimale déduit des données ANTÉRIEURES à `avant` (jamais du test).

    Règle fixée à l'avance : on part des plus petites cotes et on exclut chaque
    tranche consécutive où le marché ne sous-estime PAS les chevaux (victoires
    réelles / attendues ≤ 1). Dans ces tranches, les favoris ne sont pas
    sous-payés en moyenne : quand le modèle y voit de la valeur, c'est plus
    probablement une erreur du modèle qu'une erreur du marché. Le seuil est
    borné entre `plancher` et `plafond`.
    """
    t = table_par_tranche(F[F["date"] < avant])
    seuil = 1.0
    for _, row in t.iterrows():
        if row["reel_sur_attendu"] <= 1.0:
            seuil = float(str(row["tranche"]).split(";")[1].rstrip(")"))
        else:
            break
    return float(np.clip(seuil, plancher, plafond)), t


def justifier_cote_max(F: pd.DataFrame, avant: pd.Timestamp, plancher: float = 15.0,
                       plafond: float = 100.0) -> float:
    """Plafond de cote déduit des données ANTÉRIEURES à `avant`, symétrique de
    `justifier_cote_min` : en partant des plus grosses cotes, on exclut chaque
    tranche consécutive où le marché SURESTIME les chevaux (réel/attendu ≤ 1).
    Ces « loteries » sont là où le biais favori-outsider coûte le plus cher."""
    t = table_par_tranche(F[F["date"] < avant])
    seuil = 1e9
    for _, row in t.iloc[::-1].iterrows():
        if row["reel_sur_attendu"] <= 1.0:
            seuil = float(str(row["tranche"]).split(";")[0].lstrip("[≥"))
        else:
            break
    return float(np.clip(seuil, plancher, plafond))


def paris_necessaires(cote_moy: float, roi: float = 0.05, z: float = 1.96) -> int:
    """Nombre de paris pour distinguer un ROI donné de 0 (test bilatéral à 95 %).
    Variance du retour d'un pari de 1 à la cote o ≈ o − 1."""
    return int(np.ceil(z ** 2 * max(cote_moy - 1, 0.01) / roi ** 2))


def table_par_rang(pred: pd.DataFrame, rang_max: int = 6) -> pd.DataFrame:
    """Par rang dans la cote (1 = favori ; rang_max = rang_max et au-delà) :
    part des victoires, victoires réelles / attendues et ROI d'un pari systématique."""
    rang = pred["cote_decision"].groupby(pred["course_id"]).rank(method="first").clip(upper=rang_max)
    d = pred.assign(rang=rang.astype(int),
                    retour=np.where(pred["gagnant"] == 1, pred["rapport_gagnant"].fillna(0), 0.0))
    t = d.groupby("rang").agg(partants=("gagnant", "size"), victoires=("gagnant", "sum"),
                              attendues=("q_dec", "sum"), retour=("retour", "sum"))
    t["part_des_victoires_pct"] = (100 * t["victoires"] / t["victoires"].sum()).round(1)
    t["reel_sur_attendu"] = (t["victoires"] / t["attendues"]).round(3)
    t["roi_systematique_pct"] = (100 * (t["retour"] / t["partants"] - 1)).round(1)
    t = t.drop(columns=["retour", "attendues"]).reset_index()
    t["rang"] = t["rang"].map(lambda r: "favori" if r == 1 else (f"{r}e" if r < rang_max else f"{rang_max}e et +"))
    return t


def calibration_modele(pred: pd.DataFrame) -> pd.DataFrame:
    d = pred.assign(tranche=tranche_cote(pred["cote_decision"]))
    t = d.groupby("tranche", observed=True).agg(
        partants=("gagnant", "size"), victoires=("gagnant", "sum"),
        p_marche=("p_marche", "sum"), p_modele=("p_modele", "sum"))
    t["reel/marche"] = (t["victoires"] / t["p_marche"]).round(3)
    t["reel/modele"] = (t["victoires"] / t["p_modele"]).round(3)
    return t.round(1).reset_index()


def derive_rapport(pred: pd.DataFrame) -> pd.DataFrame:
    """Chez les gagnants : rapport payé / cote de décision, par tranche.
    < 1 : la cote a baissé avant le départ (le pari rapporte moins que prévu)."""
    g = pred[pred["gagnant"] == 1].assign(tranche=lambda x: tranche_cote(x["cote_decision"]))
    r = (g["rapport_gagnant"] / g["cote_decision"])
    t = r.groupby(g["tranche"], observed=True).agg(["count", "mean", "median"]).round(3)
    return t.rename(columns={"count": "gagnants", "mean": "ratio_moyen", "median": "ratio_median"}).reset_index()


def sensibilite(pred: pd.DataFrame, cfg: Config, cotes_min=(1.0, 2.0, 3.0, 4.0, 6.0, 8.0),
                marges=(0.0, 0.05, 0.10, 0.20, 0.30)) -> pd.DataFrame:
    """ROI (mise fixe) pour une grille de paramètres. DESCRIPTIF : choisir le
    meilleur point de cette grille sur la période de test serait du surajustement."""
    fixe = copy.deepcopy(cfg.mise); fixe.methode = "fixe"; fixe.mise_fixe = 1.0
    lignes = []
    for cm in cotes_min:
        for mg in marges:
            s = copy.deepcopy(cfg.selection); s.cote_min = cm; s.marge_ev = mg; s.cote_min_auto = False
            b = simuler(pred, s, fixe, commission=cfg.backtest.commission_gains, remise=cfg.backtest.remise_mises)
            lignes.append({"cote_min": cm, "marge_ev": mg, "paris": len(b),
                           "roi_pct": round(100 * b["profit"].sum() / b["mise"].sum(), 1) if len(b) else np.nan})
    return pd.DataFrame(lignes)


def exploration_confirmation(pred: pd.DataFrame, cfg: Config, cotes_min=(2.0, 3.0, 4.0, 6.0, 8.0),
                             marges=(0.05, 0.10, 0.20, 0.30), min_paris: int = 30) -> dict:
    """Choix des paramètres sur la 1re moitié des plis de test (« exploration »),
    puis mesure sur la 2nde moitié (« confirmation ») jamais utilisée pour choisir.
    C'est le chiffre le moins biaisé que l'on puisse produire avec ces données."""
    plis = np.sort(pred["pli"].unique())
    if len(plis) < 2:
        return {}
    coupe = plis[len(plis) // 2]
    expl, conf = pred[pred["pli"] < coupe], pred[pred["pli"] >= coupe]
    grille = sensibilite(expl, cfg, cotes_min, marges)
    ok = grille[grille["paris"] >= min_paris]
    if ok.empty:
        return {"grille_exploration": grille, "message": "Trop peu de paris en exploration."}
    best = ok.sort_values("roi_pct", ascending=False).iloc[0]
    s = copy.deepcopy(cfg.selection); s.cote_min = float(best["cote_min"]); s.marge_ev = float(best["marge_ev"])
    s.cote_min_auto = False
    fixe = copy.deepcopy(cfg.mise); fixe.methode = "fixe"; fixe.mise_fixe = 1.0
    b = simuler(conf, s, fixe, commission=cfg.backtest.commission_gains, remise=cfg.backtest.remise_mises)
    return {
        "periode_exploration": (str(expl["date"].min().date()), str(expl["date"].max().date())),
        "periode_confirmation": (str(conf["date"].min().date()), str(conf["date"].max().date())),
        "parametres_choisis": {"cote_min": s.cote_min, "marge_ev": s.marge_ev},
        "roi_exploration_pct": float(best["roi_pct"]),
        "metriques_confirmation": metriques(b, "Confirmation (paramètres figés)", cfg.backtest.n_bootstrap),
        "grille_exploration": grille,
    }
