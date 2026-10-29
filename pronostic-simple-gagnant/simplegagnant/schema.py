"""Format canonique des données : une ligne par partant.

Toutes les sources (API PMU, fichiers d'abonnement, autres pays) sont
converties dans ce format par un « adaptateur » (dossier `adapters/`).
Le reste de l'outil ne connaît que ce format.

Colonnes OBLIGATOIRES
---------------------
course_id        identifiant unique de la course (ex. "2026-10-25_R1C1")
date             date de la course (AAAA-MM-JJ)
num              numéro du partant
cheval           nom ou identifiant du cheval (sert à suivre son historique)
cote_decision    cote disponible AU MOMENT OÙ L'ON PARIE (rapport probable
                 pour 1 €, mise incluse). C'est la seule cote que le modèle a
                 le droit d'utiliser pour décider.

Colonnes de RÉSULTAT (obligatoires pour entraîner / backtester, absentes pour
pronostiquer une course à venir)
-------------------------------------------------------------------------------
position         place à l'arrivée (1 = gagnant ; vide = non classé / disqualifié)
gagnant          1 si le cheval a gagné (ex aequo compris), sinon 0
rapport_gagnant  rapport Simple Gagnant RÉELLEMENT PAYÉ pour 1 € (vide si perdant).
                 Le prélèvement de l'opérateur y est déjà intégré.

Colonnes OPTIONNELLES (utilisées si présentes)
----------------------------------------------
heure_depart     date-heure de départ (ordonne les courses d'une même journée)
hippodrome, discipline, distance, terrain, corde_sens, autostart
jockey, entraineur, musique, corde (numéro de corde / place derrière l'autostart),
ferrure (FERRE, D4, DA, DP), oeilleres, age, sexe, poids, gains, valeur_handicap
poids_cheval (poids du cheval lui-même), ecart (longueurs de retard sur le gagnant)
cote_matin, cote_t90, cote_t30 : cotes à des horizons ANTÉRIEURS à la décision
cote_finale      dernière cote affichée (sert uniquement au backtest « optimiste »)
non_partant      1 si non-partant (ligne ignorée : mise remboursée)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OBLIGATOIRES = ["course_id", "date", "num", "cheval", "cote_decision"]
RESULTATS = ["position", "gagnant", "rapport_gagnant"]
OPTIONNELLES = [
    "heure_depart", "hippodrome", "discipline", "distance", "terrain", "corde_sens",
    "autostart", "jockey", "entraineur", "musique", "corde", "ferrure", "oeilleres",
    "age", "sexe", "poids", "gains", "valeur_handicap", "cote_matin", "cote_t90",
    "cote_t30", "cote_finale", "non_partant",
]

NUMERIQUES = [
    "num", "cote_decision", "position", "gagnant", "rapport_gagnant", "distance",
    "corde", "age", "poids", "gains", "valeur_handicap", "cote_matin", "cote_t90",
    "cote_t30", "cote_finale", "poids_cheval", "ecart", "poids_porte", "allocation",
    "nb_courses", "nb_victoires", "nb_places", "changement_jockey",
]


class ErreurDonnees(ValueError):
    pass


def charger(path: str | Path) -> pd.DataFrame:
    """Charge un CSV/Parquet au format canonique et le valide."""
    path = Path(path)
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, low_memory=False)
    return normaliser(df)


def normaliser(df: pd.DataFrame, avec_resultats: bool | None = None,
               bornes_overround: tuple[float, float] = (1.02, 1.45)) -> pd.DataFrame:
    """Valide et normalise les types ; retire les non-partants.

    avec_resultats : None = détecter automatiquement.
    bornes_overround : intervalle accepté pour la somme des 1/cote d'une course.
    """
    manquantes = [c for c in OBLIGATOIRES if c not in df.columns]
    if manquantes:
        raise ErreurDonnees(f"Colonnes obligatoires manquantes : {manquantes}")
    df = df.copy()
    df["course_id"] = df["course_id"].astype(str)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    if "heure_depart" in df.columns:
        df["heure_depart"] = pd.to_datetime(df["heure_depart"], utc=True, errors="coerce")
    for c in NUMERIQUES:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Poids exprimés en dixièmes de kg dans certaines sources (ex. 575 = 57,5 kg)
    for c in ("poids", "poids_porte"):
        if c in df.columns:
            df.loc[df[c] > 150, c] = df.loc[df[c] > 150, c] / 10.0
    if "non_partant" in df.columns:
        np_mask = df["non_partant"].fillna(0).astype(bool)
        df = df.loc[~np_mask].drop(columns=["non_partant"])
    # Cote de décision absente ou < 1 pour UN partant : toute la course est écartée
    # (retirer seulement le partant fausserait les probabilités des autres).
    invalide = df["cote_decision"].isna() | (df["cote_decision"] < 1.0)
    mauvaises = df.loc[invalide, "course_id"].unique()
    df = df[~df["course_id"].isin(mauvaises)]
    # Contrôle de cohérence du marché : la somme des 1/cote (« overround ») vaut
    # 1/(taux de retour) ≈ 1,18 au PMU. Une somme aberrante signale une erreur de
    # relevé (cotes figées, partants manquants…) : course écartée.
    s = (1.0 / df["cote_decision"]).groupby(df["course_id"]).transform("sum")
    df = df[(s >= bornes_overround[0]) & (s <= bornes_overround[1])]

    if avec_resultats is None:
        avec_resultats = "gagnant" in df.columns and df["gagnant"].notna().any()
    if avec_resultats:
        for c in RESULTATS:
            if c not in df.columns:
                raise ErreurDonnees(f"Colonne de résultat manquante : {c}")
        df["gagnant"] = df["gagnant"].fillna(0).astype(int)
        # Cohérence : un gagnant doit avoir un rapport payé
        g = df["gagnant"] == 1
        sans_rapport = g & df["rapport_gagnant"].isna()
        if sans_rapport.any():
            # On ne peut pas valoriser ces courses honnêtement -> exclues
            mauvaises = df.loc[sans_rapport, "course_id"].unique()
            df = df[~df["course_id"].isin(mauvaises)]

    # Courses à au moins 2 partants seulement
    taille = df.groupby("course_id")["num"].transform("size")
    df = df[taille >= 2]
    tri = ["date", "heure_depart", "course_id", "num"] if "heure_depart" in df.columns else ["date", "course_id", "num"]
    df = df.sort_values(tri, kind="mergesort").reset_index(drop=True)
    return df


def courses_valides_pour_entrainement(df: pd.DataFrame) -> pd.Series:
    """Masque des lignes appartenant à une course avec exactement >= 1 gagnant connu."""
    nb_g = df.groupby("course_id")["gagnant"].transform("sum")
    return nb_g >= 1


def resume(df: pd.DataFrame) -> dict:
    out = {
        "partants": int(len(df)),
        "courses": int(df["course_id"].nunique()),
        "debut": str(df["date"].min().date()),
        "fin": str(df["date"].max().date()),
        "jours": int(df["date"].nunique()),
    }
    if "discipline" in df.columns:
        out["disciplines"] = df.drop_duplicates("course_id")["discipline"].value_counts().to_dict()
    if "gagnant" in df.columns:
        by = df.groupby("course_id")
        out["somme_1_sur_cote_moyenne"] = float(by["cote_decision"].apply(lambda s: np.sum(1 / s)).mean())
    return out
