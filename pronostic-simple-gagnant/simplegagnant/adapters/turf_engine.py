"""Adaptateur pour les archives publiques du dépôt GitHub « Moriah12783/turf-engine ».

Ce projet tiers (« Elite Turf ») relève chaque jour le flux public turfinfo du
PMU et publie dans son dépôt :
  site/archive/AAAA-MM-JJ.json    partants, musique, cotes à plusieurs horizons
                                  (matin, T-90, T-30, T-15 min, dernière cote)
  site/resultats/AAAA-MM-JJ.json  arrivées officielles et rapports définitifs
  turf_bench.db                   base SQLite (âge, sexe, entraîneur, poids,
                                  terrain… pour une partie de la période)

C'est un historique RÉEL du PMU mais COURT (depuis fin août 2026) et produit
par un tiers : il sert à tester l'outil sur le vrai marché français, pas à
remplacer un historique de plusieurs années.

Usage :
    git clone --depth 1 https://github.com/Moriah12783/turf-engine
    python -m simplegagnant construire-donnees turf-engine --source turf-engine/ \
        --sortie donnees/pmu_turf_engine.csv

Les sorties du moteur de ce projet tiers (prob_pct, value_index, smart_signal,
sélections) ne sont volontairement PAS reprises : on ne sait pas à quel
moment elles ont été calculées (risque de fuite d'information).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

CODES_FERRURE = {"FERRE": "FERRE", "D4": "D4", "DA": "DA", "DP": "DP"}


def _hippodrome(race_id: str) -> str:
    # "R1C1_25102026_SAINT-CLOUD" -> "SAINT-CLOUD"
    parts = race_id.split("_", 2)
    return parts[2] if len(parts) == 3 else ""


def _discipline(d: str | None) -> str:
    d = (d or "").upper()
    if d in ("ATTELE", "TROT_ATTELE"):
        return "TROT_ATTELE"
    if d in ("MONTE", "TROT_MONTE"):
        return "TROT_MONTE"
    if d in ("HAIE", "OBSTACLE_HAIE"):
        return "HAIES"
    if d in ("STEEPLECHASE", "OBSTACLE_STEEPLE"):
        return "STEEPLE"
    if d in ("OBSTACLE_CROSS", "CROSS"):
        return "CROSS"
    return d or "INCONNUE"


def lire_archives(dossier: Path) -> pd.DataFrame:
    lignes = []
    for f in sorted((dossier / "site" / "archive").glob("*.json")):
        for r in json.loads(f.read_text()):
            if r.get("is_cancelled"):
                continue
            for x in r["runners"]:
                lignes.append({
                    "course_id": r["race_id"],
                    "date": r["date"],
                    "heure_depart": r.get("start_time_utc"),
                    "hippodrome": _hippodrome(r["race_id"]),
                    "discipline": _discipline(r.get("discipline")),
                    "distance": r.get("distance"),
                    "corde_sens": r.get("rope"),
                    "autostart": float(bool(r.get("autostart"))),
                    "num": x["num"],
                    "cheval": x["name"],
                    "jockey": x.get("driver"),
                    "ferrure": CODES_FERRURE.get(x.get("shoeing"), x.get("shoeing")),
                    "corde": x.get("draw"),
                    "musique": x.get("music"),
                    "cote_matin": x.get("morning_odds"),
                    "cote_t90": x.get("o_t90"),
                    "cote_t30": x.get("o_t30"),
                    "cote_t15": x.get("o_t15"),
                    "cote_finale": x.get("live_odds"),
                    "cote_reelle": bool(x.get("odds_real")),
                    "non_partant": int(bool(x.get("is_np"))),
                })
    return pd.DataFrame(lignes)


def lire_resultats(dossier: Path) -> pd.DataFrame:
    lignes = []
    for f in sorted((dossier / "site" / "resultats").glob("*.json")):
        d = json.loads(f.read_text())
        for c in d.get("courses", []):
            statut = (c.get("statut") or {})
            if not statut.get("definitive") or statut.get("annulee"):
                continue
            rap = (c.get("rapports") or {})
            if not rap.get("disponibles"):
                continue
            brut = rap.get("simple_gagnant") or {}
            # Clés non numériques (ex. « Autres Chevaux » sur certaines courses
            # étrangères à masse groupée) : course ignorée, rapport non attribuable
            if any(not str(k).strip().isdigit() for k in brut):
                continue
            sg = {int(k): float(v) for k, v in brut.items()}
            if not sg:
                continue
            vus = set()
            for cl in c.get("classement", []):
                num = int(cl["num"])
                vus.add(num)
                lignes.append({
                    "course_id": c["course_id"],
                    "num": num,
                    "position": cl.get("rang"),
                    "rapport_gagnant": sg.get(num),
                })
            # Les gagnants payés font foi : un cheval avec rapport Simple Gagnant a gagné
            for num, div in sg.items():
                if num not in vus:
                    lignes.append({"course_id": c["course_id"], "num": num, "position": 1, "rapport_gagnant": div})
    return pd.DataFrame(lignes).drop_duplicates(["course_id", "num"])


def lire_base_sqlite(dossier: Path) -> pd.DataFrame:
    """Variables complémentaires (âge, sexe, entraîneur, poids, terrain…) quand disponibles."""
    db = dossier / "turf_bench.db"
    if not db.exists():
        return pd.DataFrame()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    q = """
        select r.race_id as course_id, r.num, r.sex as sexe, r.age, r.trainer as entraineur,
               r.weight as poids, r.blinkers as oeilleres, r.earnings as gains,
               r.official_rating as valeur_handicap, c.track_condition as terrain
        from runners r join races c on c.race_id = r.race_id
    """
    out = pd.read_sql(q, con)
    con.close()
    return out


def construire(dossier: str | Path, horizon_decision: str = "cote_t15") -> pd.DataFrame:
    """Construit le jeu canonique.

    horizon_decision : cote utilisée pour DÉCIDER le pari ("cote_t15" par défaut,
    c.-à-d. la cote affichée 15 minutes avant le départ). Le gain, lui, est
    toujours calculé avec le rapport définitif réellement payé.
    """
    dossier = Path(dossier)
    arch = lire_archives(dossier)
    res = lire_resultats(dossier)
    # Jointure à GAUCHE sur les courses ayant un résultat : les partants absents du
    # classement (disqualifiés, arrêtés, tombés) restent dans les données comme perdants.
    # Les supprimer gonflerait artificiellement le taux de réussite.
    arch = arch[arch["course_id"].isin(res["course_id"].unique())]
    df = arch.merge(res, on=["course_id", "num"], how="left")

    # Ne garder que les courses dont toutes les cotes des partants sont réelles
    # (le projet tiers a parfois utilisé des cotes « nominales » de secours).
    partants = df[df["non_partant"] == 0]
    ok = partants.groupby("course_id")["cote_reelle"].all()
    df = df[df["course_id"].isin(ok[ok].index)]

    # Variables complémentaires de la base SQLite (première partie de la période)
    extra = lire_base_sqlite(dossier)
    if not extra.empty:
        df = df.merge(extra, on=["course_id", "num"], how="left")

    df["cote_decision"] = df[horizon_decision]
    df["gagnant"] = df["rapport_gagnant"].notna().astype(int)
    df.loc[df["gagnant"] == 0, "rapport_gagnant"] = np.nan
    # Une course n'est exploitable que si elle a au moins un gagnant payé
    g = df.groupby("course_id")["gagnant"].transform("sum")
    df = df[g >= 1]
    df = df.drop(columns=["cote_reelle"])
    return df.sort_values(["date", "heure_depart", "course_id", "num"]).reset_index(drop=True)
