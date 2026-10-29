"""Adaptateur pour le jeu public « hkracing » (Hong Kong Jockey Club, 1997-2005).

Jeu Kaggle de G. Daley (6 349 courses, 79 447 partants), recopié dans plusieurs
dépôts GitHub publics (ex. rue619/horse_racing_data_analysis, dossier data/).
Fichiers : races.csv et runs.csv.

Intérêt : 8 ans de courses RÉELLES en pari mutuel (prélèvement d'environ 17,5 %
sur le gagnant à Hong Kong), avec rapports gagnants payés — de quoi valider la
MÉTHODE sur un échantillon bien plus long que l'historique PMU disponible ici.

Limite importante : seule la cote FINALE est fournie. Le backtest décide donc
avec une cote qu'aucun parieur ne connaît avant le départ : c'est un majorant
optimiste de ce qu'on aurait réellement obtenu.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def construire(dossier: str | Path) -> pd.DataFrame:
    dossier = Path(dossier)
    races = pd.read_csv(dossier / "races.csv")
    runs = pd.read_csv(dossier / "runs.csv")
    df = runs.merge(races, on="race_id", how="inner")

    out = pd.DataFrame({
        "course_id": "HK_" + df["race_id"].astype(str),
        "date": pd.to_datetime(df["date"]),
        # Pas d'heure : on ordonne les courses de la journée par leur numéro
        "heure_depart": pd.to_datetime(df["date"]) + pd.to_timedelta(df["race_no"] * 30, unit="min"),
        "hippodrome": df["venue"],
        "discipline": np.where(df["surface"] == 0, "PLAT_GAZON", "PLAT_PSF"),
        "distance": df["distance"],
        "terrain": df["going"],
        "num": df["horse_no"],
        "cheval": "H" + df["horse_id"].astype(str),
        "jockey": "J" + df["jockey_id"].astype(str),
        "entraineur": "T" + df["trainer_id"].astype(str),
        "corde": df["draw"],
        "poids": df["actual_weight"],
        "poids_cheval": df["declared_weight"],
        "age": df["horse_age"],
        "valeur_handicap": df["horse_rating"],
        "ecart": df["lengths_behind"],
        "position": df["result"],
        "cote_decision": df["win_odds"],
        "cote_finale": df["win_odds"],
    })
    # Gagnant(s) et rapport payé (dividende HK pour 10 $ -> pour 1)
    w1 = df["win_combination1"].astype(float)
    w2 = df["win_combination2"].astype(float)
    gagnant = (df["horse_no"] == w1) | (df["horse_no"] == w2)
    rapport = np.where(df["horse_no"] == w1, df["win_dividend1"] / 10.0,
                       np.where(df["horse_no"] == w2, df["win_dividend2"] / 10.0, np.nan))
    out["gagnant"] = gagnant.astype(int)
    out["rapport_gagnant"] = rapport
    return out.sort_values(["date", "heure_depart", "course_id", "num"]).reset_index(drop=True)
