"""Variables spécifiques aux courses de PLAT (galop sans obstacles).

Rappel important pour le logit conditionnel : une variable identique pour tous
les partants d'une course (terrain, distance, type de course) n'a AUCUN effet
sur les probabilités relatives. Elle ne sert qu'en interaction avec une
caractéristique propre au cheval (ex. corde × sprint, poids × handicap).

Toutes ces variables sont connues avant la course :
  - corde (numéro de stalle), poids, décharge, valeur, oeillères, jockey :
    publiés au programme ;
  - historiques (oeillères précédentes, jockey précédent, forme en plat) :
    calculés uniquement sur les JOURS ANTÉRIEURS.

Ce que l'on sait du plat (et que le modèle doit confirmer sur VOS données) :
  - la corde compte surtout sur les courses courtes et dans les grands pelotons ;
  - en handicap, les poids égalisent les chances : le marché sur- ou sous-réagit
    parfois au poids ou à une baisse de valeur ;
  - une décharge d'apprenti allège le cheval de 1,5 à 4 kg ;
  - la pose d'oeillères pour la première fois ou un changement de jockey
    (souvent un meilleur jockey) sont des signaux d'intention de l'entourage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .musique import parser as parser_musique

# Variables fondamentales (étape 1) propres au plat
FONDAMENTALES_PLAT = [
    # (corde relative et poids relatif « simples » sont déjà dans les variables générales)
    "pl_corde_sprint", "pl_corde_grand_peloton",
    "pl_poids_rel_handicap", "pl_decharge", "pl_valeur_rel_handicap",
    "pl_oeilleres_1re_fois", "pl_oeilleres_retirees", "pl_changement_jockey",
    "pl_forme_plat_moy3", "pl_victoire_plat_recente", "pl_nb_courses_plat",
    "pl_taux_victoire_carriere", "pl_taux_place_carriere",
    "pl_var_poids", "pl_var_valeur",
]
# Corrections du marché (étape 2) : laissent le modèle apprendre si le
# favori est surjoué ou si les 2e-5e choix sont sous-estimés en plat.
MARCHE_PLAT = ["pl_favori", "pl_rang_2_5", "pl_logq_x_peloton"]


def _est_plat(df: pd.DataFrame) -> pd.Series:
    if "discipline" not in df.columns:
        return pd.Series(True, index=df.index)
    return df["discipline"].fillna("").astype(str).str.upper().str.contains("PLAT")


def _est_handicap(df: pd.DataFrame) -> pd.Series:
    if "categorie" in df.columns and df["categorie"].notna().any():
        return df["categorie"].fillna("").astype(str).str.upper().str.contains("HANDICAP").astype(float)
    # Sans la catégorie : une course où les valeurs handicap varient est un handicap
    if "valeur_handicap" in df.columns:
        sd = df.groupby("course_id")["valeur_handicap"].transform("std")
        return (sd > 0.5).astype(float)
    return pd.Series(np.nan, index=df.index)


def _forme_plat(musique: str | float | None) -> tuple[float, float, float]:
    """(moyenne des 3 dernières places EN PLAT, victoire dans les 3 dernières, nb courses de plat)."""
    perf = [p for p in parser_musique(musique) if p[1] == "p"]
    if not perf:
        return (np.nan, np.nan, 0.0)
    places = [p[0] for p in perf]
    return (float(np.mean(places[:3])), float(1 in places[:3]), float(len(perf)))


def _precedent_par_cheval(df: pd.DataFrame, col: str) -> pd.Series:
    """Valeur de `col` lors de la sortie précédente du cheval (jours antérieurs)."""
    j = (df[["cheval", "date", col]].dropna(subset=["cheval"])
         .groupby(["cheval", "date"], sort=True)[col].first().reset_index())
    j[col + "_prec"] = j.groupby("cheval")[col].shift(1)
    m = df[["cheval", "date"]].merge(j[["cheval", "date", col + "_prec"]], on=["cheval", "date"], how="left")
    m.index = df.index
    return m[col + "_prec"]


def construire(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les variables pl_* (NaN pour les courses qui ne sont pas du plat)."""
    out = pd.DataFrame(index=df.index)
    plat = _est_plat(df)
    taille = df["taille"]

    # --- Corde ---------------------------------------------------------------
    if "corde" in df.columns:
        # Rang de la corde parmi les PARTANTS (les non-partants laissent des trous) : 0 = corde 1, 1 = la plus large
        rang_c = df["corde"].groupby(df["course_id"]).rank(method="average")
        rel = (rang_c - 1) / (taille - 1).clip(lower=1)
        out["pl_corde_rel"] = rel
        if "distance" in df.columns:
            out["pl_corde_sprint"] = rel * (df["distance"] <= 1400)
        out["pl_corde_grand_peloton"] = rel * (taille >= 14)

    # --- Poids, décharge, valeur ----------------------------------------------
    handicap = _est_handicap(df)
    poids = df["poids_porte"] if "poids_porte" in df.columns and df["poids_porte"].notna().any() else df.get("poids")
    if poids is not None and poids.notna().any():
        pr = poids - poids.groupby(df["course_id"]).transform("mean")
        out["pl_poids_rel"] = pr
        out["pl_poids_rel_handicap"] = pr * handicap
        out["pl_var_poids"] = poids - _precedent_par_cheval(df.assign(_p=poids), "_p")
    if {"poids_porte", "poids"}.issubset(df.columns):
        # Poids porté < poids attribué : décharge d'apprenti / jeune jockey (en kg)
        out["pl_decharge"] = (df["poids"] - df["poids_porte"]).clip(lower=0)
    if "valeur_handicap" in df.columns and df["valeur_handicap"].notna().any():
        vr = df["valeur_handicap"] - df.groupby("course_id")["valeur_handicap"].transform("mean")
        out["pl_valeur_rel_handicap"] = vr * handicap
        out["pl_var_valeur"] = df["valeur_handicap"] - _precedent_par_cheval(df, "valeur_handicap")

    # --- Équipement et jockey : signaux d'intention -------------------------------
    if "oeilleres" in df.columns and df["oeilleres"].notna().any():
        o = df["oeilleres"].fillna("").astype(str).str.upper()
        avec = (~o.isin(["", "SANS_OEILLERES", "NAN", "NONE"])).astype(float)
        avec[df["oeilleres"].isna()] = np.nan
        prec = _precedent_par_cheval(df.assign(_o=avec), "_o")
        out["pl_oeilleres_1re_fois"] = ((avec == 1) & (prec == 0)).astype(float).where(prec.notna())
        out["pl_oeilleres_retirees"] = ((avec == 0) & (prec == 1)).astype(float).where(prec.notna())
    if "changement_jockey" in df.columns and df["changement_jockey"].notna().any():
        out["pl_changement_jockey"] = df["changement_jockey"].astype(float)
    elif "jockey" in df.columns:
        prec = _precedent_par_cheval(df, "jockey")
        out["pl_changement_jockey"] = (df["jockey"] != prec).astype(float).where(prec.notna())

    # --- Forme en plat (musique) et carrière --------------------------------------
    if "musique" in df.columns:
        f = np.array([_forme_plat(m) for m in df["musique"]], dtype=float).reshape(-1, 3)
        out["pl_forme_plat_moy3"] = f[:, 0]
        out["pl_victoire_plat_recente"] = f[:, 1]
        out["pl_nb_courses_plat"] = np.log1p(f[:, 2])
    if {"nb_courses", "nb_victoires"}.issubset(df.columns):
        n = df["nb_courses"].fillna(0)
        out["pl_taux_victoire_carriere"] = (df["nb_victoires"].fillna(0) + 0.8) / (n + 8)
        if "nb_places" in df.columns:
            out["pl_taux_place_carriere"] = (df["nb_places"].fillna(0) + 2.5) / (n + 8)

    # --- Corrections de marché par rang de cote ------------------------------------
    rang = df["cote_decision"].groupby(df["course_id"]).rank(method="min")
    out["pl_favori"] = (rang == 1).astype(float)
    out["pl_rang_2_5"] = rang.between(2, 5).astype(float)
    out["pl_logq_x_peloton"] = df["log_q"] * (taille - 10) / 5

    # Hors plat : NaN (ces variables n'ont pas de sens au trot)
    out.loc[~plat, :] = np.nan
    return out
