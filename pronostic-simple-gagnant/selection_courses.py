"""Sélection des courses PMU du jour + pronostic au-delà du favori.

Usage :
  python selection_courses.py --historique donnees/pmu.csv --modele modele.pkl
  options : --min-partants 10 --n-dernieres 3 --taux-non-favoris 0.30
            --partants fichier.csv (sinon API PMU du jour)
Le modèle vient de : python -m simplegagnant entrainer donnees/pmu.csv
"""
import argparse
from datetime import date

import pandas as pd

from simplegagnant import pronostic, schema
from simplegagnant.adapters import pmu_api


def hippo(s):
    # Noms d'hippodromes comparables entre sources
    return s.astype(str).str.upper().str.replace("-", " ").str.strip()


def taux_non_favoris(hist, n):
    """Par hippodrome : part des n dernières courses gagnées par un NON-favori."""
    h = hist.assign(hip=hippo(hist["hippodrome"]),
                    rang=hist.groupby("course_id")["cote_decision"].rank(method="min"))
    g = h[h["gagnant"] == 1].drop_duplicates("course_id")
    g = g.sort_values(["date", "heure_depart"]).groupby("hip").tail(n)
    return g.groupby("hip")["rang"].apply(lambda r: (r > 1).mean())


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--historique", required=True)
    a.add_argument("--modele", default="modele.pkl")
    a.add_argument("--partants")
    a.add_argument("--min-partants", type=int, default=10)
    a.add_argument("--n-dernieres", type=int, default=3)
    a.add_argument("--taux-non-favoris", type=float, default=0.30)
    a = a.parse_args()

    hist = schema.charger(a.historique)
    part = pd.read_csv(a.partants) if a.partants else pmu_api.courses_du_jour(date.today())
    if part.empty:
        return print("Aucune course à venir.")

    # 1. Filtres : taille du peloton et historique de l'hippodrome
    actifs = part[part["non_partant"].fillna(0) != 1] if "non_partant" in part else part
    taille = actifs.groupby("course_id")["num"].size()
    taux = taux_non_favoris(hist, a.n_dernieres)
    retenues = [c for c, n in taille.items() if n >= a.min_partants
                and taux.get(hippo(actifs.loc[actifs["course_id"] == c, "hippodrome"]).iloc[0], 0)
                > a.taux_non_favoris]
    if not retenues:
        return print("Aucune course ne remplit les critères.")

    # 2. Probabilités du modèle (forme, jockey, corde... combinés aux cotes)
    pron = pronostic.pronostiquer(pronostic.charger(a.modele), hist,
                                  part[part["course_id"].isin(retenues)])

    # 3. Rapport : chevaux sous-cotés hors favori, prédiction, pari éventuel
    for cid, g in pron.groupby("course_id", sort=False):
        hors_fav = g[g["cote_decision"] > g["cote_decision"].min()]
        cand = hors_fav[hors_fav["p_modele"] >= 0.03]          # pas de « loterie »
        cand = cand.assign(ecart=cand["p_modele"] / cand["p_marche"]).nlargest(3, "ecart")
        pred = hors_fav.loc[hors_fav["p_modele"].idxmax()]      # non-favori le plus probable
        paris = g[g["pari"] == 1]
        heure = pd.to_datetime(g["heure_depart"].iloc[0], utc=True).tz_convert("Europe/Paris")
        hip = hippo(g["hippodrome"]).iloc[0]
        print(f"\n{cid} — {heure:%H h %M}, {len(g)} partants, non-favoris gagnants "
              f"sur les {a.n_dernieres} dernières de {hip} : {taux.get(hip, 0):.0%}")
        print("  Potentiel (sous-cotés par le marché) : "
              + ", ".join(f"n°{r.num} {r.cheval} ({r.p_modele:.1%} vs {r.p_marche:.1%})"
                          for r in cand.itertuples()))
        print(f"  Prédiction hors favori : n°{pred.num} {pred.cheval}, cote {pred.cote_decision:g}, "
              f"victoire estimée {pred.p_modele:.1%}")
        for r in paris.itertuples():
            print(f"  → PARI À VALEUR : n°{r.num} {r.cheval}, cote {r.cote_decision:g}, EV {r.ev:+.0%}")
        if paris.empty:
            print("  → Aucun pari : aucune cote ne paie assez sa probabilité")


if __name__ == "__main__":
    main()
