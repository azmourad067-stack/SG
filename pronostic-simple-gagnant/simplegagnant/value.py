"""Sélection des paris à valeur et gestion de la mise.

Valeur attendue d'un pari de 1 € sur le cheval i :
    EV_i = p_i × R_i − 1
où p_i est la probabilité de victoire estimée par le modèle et R_i le rapport
ATTENDU s'il gagne. En pari mutuel, R_i n'est pas connu au moment du pari :
la cote bouge jusqu'au départ. On estime donc R_i = cote_decision × facteur,
où le facteur (rapport payé / cote de décision, chez les gagnants) est appris
sur l'historique d'entraînement par tranche de cote. Au PMU, les gagnants voient
souvent leur cote baisser dans les dernières minutes (argent informé) : ignorer
ce facteur surestimerait systématiquement la valeur.

Un cheval n'est retenu que si :
    cote_min ≤ cote_decision ≤ cote_max   (les favoris sous-payés sont exclus)
    p_i ≥ proba_min
    EV_i ≥ marge_ev                        (marge de sécurité)
et au plus `max_paris_par_course` chevaux par course (les meilleurs EV).
Une course sans cheval remplissant ces conditions n'est PAS jouée.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import ConfigMise, ConfigSelection

TRANCHES = [1.0, 2.0, 3.0, 4.0, 6.0, 10.0, 15.0, 25.0, 40.0, 1e9]


def tranche_cote(cote: pd.Series) -> pd.Series:
    return pd.cut(cote, TRANCHES, right=False, labels=[
        f"[{a:g};{b:g})" if b < 1e8 else f"≥{a:g}" for a, b in zip(TRANCHES[:-1], TRANCHES[1:])])


def estimer_facteur_rapport(train: pd.DataFrame, lissage: float = 20.0) -> dict:
    """Moyenne de rapport_payé / cote_decision chez les gagnants, par tranche, lissée vers 1.

    Utilise uniquement les données d'entraînement.
    """
    g = train[train["gagnant"] == 1]
    ratio = (g["rapport_gagnant"] / g["cote_decision"]).clip(0.2, 5.0)
    global_ = float(ratio.mean()) if len(ratio) else 1.0
    t = tranche_cote(g["cote_decision"])
    stats = ratio.groupby(t, observed=False).agg(["sum", "count"])
    facteurs = {}
    for k, row in stats.iterrows():
        facteurs[str(k)] = float((row["sum"] + lissage * global_) / (row["count"] + lissage))
    facteurs["_global"] = global_
    return facteurs


def rapport_attendu(df: pd.DataFrame, facteurs: dict | None) -> pd.Series:
    if not facteurs:
        return df["cote_decision"].astype(float)
    t = tranche_cote(df["cote_decision"]).astype(str)
    f = t.map(facteurs).fillna(facteurs.get("_global", 1.0)).astype(float)
    return df["cote_decision"] * f


def esperance(p: pd.Series, rapport: pd.Series, commission_gains: float = 0.0) -> pd.Series:
    """EV par euro misé ; la commission éventuelle s'applique au gain net."""
    gain_si_victoire = 1.0 + (rapport - 1.0) * (1.0 - commission_gains)
    return p * gain_si_victoire - 1.0


def selectionner(df: pd.DataFrame, cfg: ConfigSelection, col_p: str = "p_modele") -> pd.DataFrame:
    """Marque `pari` = 1 pour les chevaux retenus. df doit contenir `ev` et `col_p`."""
    df = df.copy()
    # Seuil propre à chaque ligne s'il a été appris pli par pli (colonne
    # `cote_min_pli`), sinon le seuil fixe de la configuration.
    if cfg.cote_min_auto and "cote_min_pli" in df.columns:
        seuil = df["cote_min_pli"].fillna(cfg.cote_min)
    else:
        seuil = cfg.cote_min
    ok = (
        (df["cote_decision"] >= seuil)
        & (df["cote_decision"] <= (df["cote_max_pli"].fillna(cfg.cote_max)
                                   if (cfg.cote_max_auto and "cote_max_pli" in df.columns) else cfg.cote_max))
        & (df[col_p] >= cfg.proba_min)
        & (df["ev"] >= cfg.marge_ev)
    )
    df["pari"] = 0
    cand = df[ok]
    if len(cand):
        rang = cand.groupby("course_id")["ev"].rank(ascending=False, method="first")
        retenus = cand.index[rang <= cfg.max_paris_par_course]
        df.loc[retenus, "pari"] = 1
    return df


def kelly_simple(p: np.ndarray, rapport: np.ndarray) -> np.ndarray:
    """Fraction de Kelly pour un pari gagnant isolé : (p·R − 1) / (R − 1)."""
    return np.clip((p * rapport - 1.0) / np.maximum(rapport - 1.0, 1e-9), 0.0, None)


def mises_course(paris: pd.DataFrame, bankroll: float, cfg: ConfigMise, col_p: str = "p_modele") -> np.ndarray:
    """Mises des paris d'UNE course, en unités monétaires."""
    if cfg.methode == "fixe":
        return np.full(len(paris), cfg.mise_fixe)
    f = kelly_simple(paris[col_p].to_numpy(), paris["rapport_attendu"].to_numpy()) * cfg.fraction_kelly
    f = np.minimum(f, cfg.plafond_pari_pct)
    tot = f.sum()
    if tot > cfg.plafond_course_pct:
        f *= cfg.plafond_course_pct / tot
    mises = f * max(bankroll, 0.0)
    mises[mises < cfg.mise_minimale] = 0.0
    return mises
