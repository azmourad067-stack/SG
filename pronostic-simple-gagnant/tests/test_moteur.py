"""Tests : python -m unittest discover -s tests -v

Ils vérifient surtout l'ABSENCE DE FUITE d'information du futur, la
justesse du calcul des gains et les règles de sélection.
"""

import json
import sys
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from simplegagnant import backtest, features, musique, schema  # noqa: E402
from simplegagnant.clogit import LogitConditionnel  # noqa: E402
from simplegagnant.config import Config, ConfigMise, ConfigSelection  # noqa: E402
from simplegagnant.value import selectionner  # noqa: E402


def courses_synthetiques(n_courses=600, graine=0, force=1.0):
    """Courses simulées : un vrai facteur caché `x` influence la victoire ;
    le marché le voit partiellement. Sert UNIQUEMENT aux tests du code."""
    rng = np.random.default_rng(graine)
    lignes = []
    jours = pd.date_range("2024-01-01", periods=n_courses // 10, freq="D")
    for k in range(n_courses):
        n = rng.integers(6, 14)
        x = rng.normal(size=n)
        u = force * x
        p = np.exp(u) / np.exp(u).sum()
        gagnant = rng.choice(n, p=p)
        q = np.exp(0.7 * u + rng.normal(scale=0.3, size=n))
        q = q / q.sum()
        cote = np.round(1 / (q * 1.18), 1).clip(1.1)
        for i in range(n):
            lignes.append({
                "course_id": f"C{k:05d}", "date": jours[k // 10], "num": i + 1,
                "cheval": f"H{rng.integers(0, 400)}", "jockey": f"J{rng.integers(0, 40)}",
                "cote_decision": cote[i], "x": x[i], "gagnant": int(i == gagnant),
                "position": 1 if i == gagnant else 2 + i,
                "rapport_gagnant": cote[i] if i == gagnant else np.nan,
            })
    return pd.DataFrame(lignes)


class TestMusique(unittest.TestCase):
    def test_lecture(self):
        f = musique.features_musique("1a3aDa(25)0a2m", "TROT_ATTELE")
        self.assertEqual(f["mus_n"], 5)
        self.assertEqual(f["mus_derniere"], 1)
        self.assertEqual(f["mus_victoires5"], 1)
        self.assertEqual(f["mus_incidents5"], 1)
        self.assertEqual(f["mus_reprise"], 0)
        self.assertAlmostEqual(f["mus_meme_disc5"], 0.8)

    def test_reprise_et_inedit(self):
        self.assertEqual(musique.features_musique("(25)1p2p", "PLAT")["mus_reprise"], 1)
        self.assertEqual(musique.features_musique("", "PLAT")["mus_inedit"], 1)


class TestLogitConditionnel(unittest.TestCase):
    def test_probas_somment_a_un_et_coef_retrouve(self):
        df = courses_synthetiques(1500, force=1.0)
        m = LogitConditionnel(l2=0.1).fit(df[["x"]].to_numpy(), df["gagnant"].to_numpy(), df["course_id"].to_numpy())
        self.assertAlmostEqual(m.coef_[0], 1.0, delta=0.15)
        p = m.predict_proba(df[["x"]].to_numpy(), df["course_id"].to_numpy())
        sommes = pd.Series(p).groupby(df["course_id"].to_numpy()).sum()
        np.testing.assert_allclose(sommes.to_numpy(), 1.0, atol=1e-9)


class TestAntiFuite(unittest.TestCase):
    def test_historique_n_utilise_que_le_passe(self):
        """Modifier les résultats d'un jour ne doit changer AUCUNE variable des jours ≤ ce jour."""
        df = schema.normaliser(courses_synthetiques(400))
        F1 = features.construire(df)
        jour = df["date"].sort_values().unique()[20]
        df2 = df.copy()
        masque = df2["date"] >= jour
        # On inverse les résultats de ce jour et des suivants
        df2.loc[masque, "gagnant"] = 1 - df2.loc[masque, "gagnant"]
        F2 = features.construire(df2)
        cols = [c for c in F1.columns if c.startswith(("jk_", "ent_", "chv_"))]
        avant = F1["date"] <= jour
        pd.testing.assert_frame_equal(F1.loc[avant, cols], F2.loc[avant, cols])

    def test_walk_forward_entraine_avant_le_test(self):
        df = schema.normaliser(courses_synthetiques(900))
        F = features.construire(df)
        cfg = Config()
        cfg.backtest.jours_entrainement_min = 30
        cfg.backtest.jours_par_pli = 15
        wf = backtest.walk_forward(F, cfg, ["x"], ["log_q"], verbeux=False)
        for _, pli in wf.plis.iterrows():
            test = wf.predictions[wf.predictions["pli"] == pli["pli"]]
            self.assertGreaterEqual(test["date"].min(), pd.Timestamp(pli["debut_test"]))
        # Les courses de test n'apparaissent qu'une fois
        self.assertFalse(wf.predictions.duplicated(["course_id", "num"]).any())

    def test_modele_trouve_l_information_cachee(self):
        """Sur données simulées où le marché ignore une partie de x, le modèle
        complet doit battre le marché hors échantillon (contrôle de bon fonctionnement)."""
        df = schema.normaliser(courses_synthetiques(1500))
        F = features.construire(df)
        cfg = Config()
        cfg.backtest.jours_entrainement_min = 60
        cfg.backtest.jours_par_pli = 30
        wf = backtest.walk_forward(F, cfg, ["x"], ["log_q"], verbeux=False)
        q = backtest.qualite_probabilites(wf.predictions)
        self.assertGreater(q.attrs["ecart_vs_marche_brut"][1], 0)


class TestSelectionEtGains(unittest.TestCase):
    def _pred(self):
        return pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"] * 4 + ["2024-01-02"] * 2),
            "course_id": ["A", "A", "A", "A", "B", "B"],
            "num": [1, 2, 3, 4, 1, 2],
            "cote_decision": [1.8, 5.0, 12.0, 30.0, 2.0, 2.9],
            "p_modele": [0.60, 0.25, 0.10, 0.02, 0.50, 0.50],
            "rapport_attendu": [1.8, 5.0, 12.0, 30.0, 2.0, 2.9],
            "gagnant": [0, 1, 0, 0, 1, 0],
            "rapport_gagnant": [np.nan, 5.6, np.nan, np.nan, 2.1, np.nan],
        })

    def test_favori_exclu_meme_avec_valeur(self):
        d = self._pred()
        d["ev"] = d["p_modele"] * d["rapport_attendu"] - 1   # favori A : EV = +8 %
        sel = ConfigSelection(cote_min=3.0, marge_ev=0.05, cote_min_auto=False)
        r = selectionner(d, sel)
        self.assertEqual(r.loc[0, "pari"], 0)        # favori à 1,8 exclu
        self.assertEqual(r.loc[1, "pari"], 1)        # 5,0 × 0,25 = 1,25 → EV +25 %
        self.assertEqual(r[r["course_id"] == "B"]["pari"].sum(), 0)  # course B : aucun pari

    def test_un_pari_par_course_et_rapport_paye(self):
        d = self._pred()
        d["ev"] = d["p_modele"] * d["rapport_attendu"] - 1
        sel = ConfigSelection(cote_min=3.0, marge_ev=0.05, cote_min_auto=False, max_paris_par_course=1)
        b = backtest.simuler(d, sel, ConfigMise(methode="fixe", mise_fixe=1.0))
        self.assertEqual(len(b), 1)
        self.assertEqual(int(b.iloc[0]["num"]), 2)
        self.assertAlmostEqual(b["profit"].sum(), 4.6)   # payé 5,6 (rapport réel), pas 5,0

    def test_kelly_plafonne(self):
        d = self._pred()
        d["ev"] = d["p_modele"] * d["rapport_attendu"] - 1
        sel = ConfigSelection(cote_min=3.0, marge_ev=0.05, cote_min_auto=False)
        m = ConfigMise(methode="kelly", bankroll_initiale=1000, fraction_kelly=0.25, plafond_pari_pct=0.02)
        b = backtest.simuler(d, sel, m)
        self.assertLessEqual(b.iloc[0]["mise"], 20.0 + 1e-9)


class TestAdaptateurPMU(unittest.TestCase):
    def test_lecture_fixture_api(self):
        from simplegagnant.adapters import pmu_api
        fx = RACINE / "tests" / "fixtures"
        prog = json.loads((fx / "programme_15092026.json").read_text())
        part = json.loads((fx / "participants_15092026_R1C1.json").read_text())
        rap = json.loads((fx / "rapports_15092026_R1C1.json").read_text())
        reunion = prog["programme"]["reunions"][0]
        lignes = pd.DataFrame(pmu_api.lignes_course(date(2026, 9, 15), reunion, reunion["courses"][0],
                                                    part, rap, internet=False))
        self.assertEqual(lignes["gagnant"].sum(), 1)
        g = lignes[lignes["gagnant"] == 1].iloc[0]
        self.assertEqual(g["num"], 7)
        self.assertAlmostEqual(g["rapport_gagnant"], 4.2)
        # La cote de décision doit être antérieure au départ (pas la cote finale)
        self.assertTrue((pd.to_datetime(lignes["heure_cote_decision"]) < pd.to_datetime(lignes["heure_depart"])).all())
        self.assertAlmostEqual(g["cote_decision"], 6.7)   # référence ≈ H-30
        self.assertAlmostEqual(g["cote_finale"], 4.2)


if __name__ == "__main__":
    unittest.main()


class TestPlat(unittest.TestCase):
    def _df(self):
        df = courses_synthetiques(400)
        df["discipline"] = "PLAT"
        rng = np.random.default_rng(1)
        df["corde"] = df.groupby("course_id").cumcount() + 1 + (rng.random(len(df)) > 0.8) * 3
        df["distance"] = 1200
        df["oeilleres"] = np.where(rng.random(len(df)) > 0.7, "OEILLERES_CLASSIQUE", "SANS_OEILLERES")
        return schema.normaliser(df)

    def test_corde_relative_bornee(self):
        cfg = Config.plat()
        F, cf, cm = features.preparer(self._df(), cfg)
        self.assertTrue(F["pl_corde_sprint"].between(0, 1).all())
        self.assertIn("pl_favori", cm)

    def test_variables_plat_sans_fuite(self):
        """Changer les résultats et l'équipement FUTURS ne change pas les variables passées."""
        df = self._df()
        F1 = features.construire(df, profil="plat")
        jour = df["date"].sort_values().unique()[20]
        df2 = df.copy()
        m = df2["date"] > jour
        df2.loc[m, "gagnant"] = 1 - df2.loc[m, "gagnant"]
        df2.loc[m, "oeilleres"] = "OEILLERES_AUSTRALIENNES"
        F2 = features.construire(df2, profil="plat")
        cols = [c for c in F1.columns if c.startswith(("pl_", "jk_", "chv_"))]
        av = F1["date"] <= jour
        pd.testing.assert_frame_equal(F1.loc[av, cols], F2.loc[av, cols])

    def test_filtre_discipline(self):
        df = self._df()
        df.loc[df["course_id"] < "C00100", "discipline"] = "TROT_ATTELE"
        F, _, _ = features.preparer(df, Config.plat())
        self.assertTrue((F["discipline"] == "PLAT").all())
