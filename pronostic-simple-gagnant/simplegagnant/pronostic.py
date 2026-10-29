"""Entraînement du modèle final et pronostics sur des courses à venir."""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from . import features, schema
from .config import Config
from .model import ModeleDeuxEtapes
from .backtest import justifier_cote_max, justifier_cote_min
from .value import esperance, estimer_facteur_rapport, kelly_simple, rapport_attendu, selectionner


def entrainer(historique: pd.DataFrame, cfg: Config) -> dict:
    """Entraîne le modèle sur TOUT l'historique (à refaire régulièrement, ex. chaque semaine)."""
    F, cf, cm = features.preparer(historique, cfg)
    modele = ModeleDeuxEtapes(cf, cm, cfg.modele).fit(F)
    apres = F["date"].max() + pd.Timedelta(days=1)
    seuil, _ = justifier_cote_min(F, apres, cfg.selection.cote_min_plancher, cfg.selection.cote_min_plafond)
    plafond = justifier_cote_max(F, apres, cfg.selection.cote_max_plancher, cfg.selection.cote_max_plafond)
    return {"modele": modele, "facteurs": estimer_facteur_rapport(F), "cfg": cfg, "cote_min_apprise": seuil, "cote_max_apprise": plafond,
            "cols_fond": cf, "cols_marche": cm, "fin_historique": str(F["date"].max().date()),
            "coefficients": modele.coefficients()}


def sauver(paquet: dict, chemin: str | Path) -> None:
    with open(chemin, "wb") as f:
        pickle.dump(paquet, f)


def charger(chemin: str | Path) -> dict:
    # pickle : ne charger que des modèles que VOUS avez produits.
    with open(chemin, "rb") as f:
        return pickle.load(f)


def pronostiquer(paquet: dict, historique: pd.DataFrame, partants: pd.DataFrame,
                 bankroll: float | None = None) -> pd.DataFrame:
    """Probabilités, valeur et recommandation pour chaque partant des courses à venir.

    historique : données passées (résultats connus) pour calculer la forme des
                 jockeys, entraîneurs et chevaux ; partants : courses à venir,
                 avec la cote actuelle dans `cote_decision`.
    """
    cfg: Config = paquet["cfg"]
    nouv = schema.normaliser(partants, avec_resultats=False)
    for c in ("gagnant", "position", "rapport_gagnant"):
        nouv[c] = np.nan
    ids = set(nouv["course_id"])
    hist = historique[~historique["course_id"].isin(ids)]
    tout = pd.concat([hist, nouv], ignore_index=True)
    tri = ["date", "heure_depart", "course_id", "num"] if "heure_depart" in tout.columns else ["date", "course_id", "num"]
    tout = tout.sort_values(tri, kind="mergesort").reset_index(drop=True)
    F = features.construire(tout, cfg.modele.lissage, cfg.donnees.profil)
    F = features.filtrer_disciplines(F[F["course_id"].isin(ids)], cfg.donnees.disciplines).copy()
    if F.empty:
        raise ValueError(f"Aucune course à venir pour les disciplines {cfg.donnees.disciplines}.")
    for c in paquet["cols_fond"] + paquet["cols_marche"]:
        if c not in F.columns:
            F[c] = np.nan
    pred = paquet["modele"].predict(F)
    F["p_modele"] = pred["p_modele"].to_numpy()
    F["rapport_attendu"] = rapport_attendu(F, paquet["facteurs"])
    F["ev"] = esperance(F["p_modele"], F["rapport_attendu"], cfg.backtest.commission_gains) + cfg.backtest.remise_mises
    if cfg.selection.cote_min_auto and "cote_min_apprise" in paquet:
        F["cote_min_pli"] = paquet["cote_min_apprise"]
    if cfg.selection.cote_max_auto and "cote_max_apprise" in paquet:
        F["cote_max_pli"] = paquet["cote_max_apprise"]
    seuil = F["cote_min_pli"].iloc[0] if "cote_min_pli" in F else cfg.selection.cote_min
    plafond = F["cote_max_pli"].iloc[0] if "cote_max_pli" in F else cfg.selection.cote_max
    F = selectionner(F, cfg.selection)
    F["kelly_fraction"] = np.where(F["pari"] == 1, np.minimum(
        kelly_simple(F["p_modele"].to_numpy(), F["rapport_attendu"].to_numpy()) * cfg.mise.fraction_kelly,
        cfg.mise.plafond_pari_pct), 0.0)
    if bankroll:
        F["mise_kelly"] = (F["kelly_fraction"] * bankroll).round(2)
    F["raison"] = np.select(
        [F["pari"] == 1, F["cote_decision"] < seuil, F["cote_decision"] > plafond,
         F["ev"] < cfg.selection.marge_ev],
        ["VALEUR", "exclu : cote < cote_min (favori sous-payé)", "exclu : cote > cote_max",
         "pas de valeur (EV < marge)"], default="autre filtre")
    cols = ["date", "heure_depart", "course_id", "hippodrome", "num", "cheval", "cote_decision", "q_dec",
            "p_modele", "rapport_attendu", "ev", "pari", "kelly_fraction", "mise_kelly", "raison"]
    out = F[[c for c in cols if c in F.columns]].rename(columns={"q_dec": "p_marche"})
    return out.sort_values(["heure_depart" if "heure_depart" in out else "date", "course_id", "ev"],
                           ascending=[True, True, False])


def resume_pronostics(pron: pd.DataFrame) -> str:
    lignes = []
    for cid, g in pron.groupby("course_id", sort=False):
        paris = g[g["pari"] == 1]
        if paris.empty:
            lignes.append(f"{cid} : aucun pari (pas de valeur suffisante)")
        for _, r in paris.iterrows():
            mise = f", mise Kelly {r['mise_kelly']:.2f}" if "mise_kelly" in r and pd.notna(r.get("mise_kelly")) else ""
            lignes.append(f"{cid} : n°{int(r['num'])} {r['cheval']} — cote {r['cote_decision']:g}, "
                          f"p modèle {100 * r['p_modele']:.1f} % vs marché {100 * r['p_marche']:.1f} %, "
                          f"EV {100 * r['ev']:+.0f} %{mise}")
    return "\n".join(lignes)
