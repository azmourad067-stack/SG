"""Ligne de commande : python -m simplegagnant <commande> --help"""

from __future__ import annotations

import argparse
import sys
import warnings
from datetime import date
from pathlib import Path

import pandas as pd

from . import backtest, features, patterns, pronostic, report, schema
from .config import Config

warnings.filterwarnings("ignore", category=RuntimeWarning)


def _date(s: str) -> date:
    return date.today() if s in ("aujourdhui", "today") else date.fromisoformat(s)


def cmd_construire(a):
    if a.type == "turf-engine":
        from .adapters import turf_engine
        df = turf_engine.construire(a.source, horizon_decision=a.horizon)
    elif a.type == "hkracing":
        from .adapters import hkracing
        df = hkracing.construire(a.source)
    else:
        from .adapters import pmu_api
        df = pmu_api.collecter(_date(a.debut), _date(a.fin), a.sortie, a.specialisation, a.cache, pause=a.pause)
        if a.releves:
            df = pmu_api.appliquer_releves(df, a.releves, a.minutes_avant)
    df.to_csv(a.sortie, index=False)
    print(f"{len(df)} lignes écrites dans {a.sortie}")
    print(schema.resume(schema.normaliser(df)))


def _config(a) -> Config:
    """--plat charge le profil plat ; un --config éventuel le complète."""
    return Config.load(getattr(a, "config", None), base=Config.plat() if getattr(a, "plat", False) else None)


def cmd_backtest(a):
    cfg = _config(a)
    df = schema.charger(a.donnees)
    resume = schema.resume(features.filtrer_disciplines(df, cfg.donnees.disciplines))
    print("Données :", resume)
    F, cf, cm = features.preparer(df, cfg)
    if cfg.donnees.disciplines:
        print(f"Disciplines retenues : {cfg.donnees.disciplines} ({F['course_id'].nunique()} courses), profil {cfg.donnees.profil}")
    print(f"Variables fondamentales ({len(cf)}) : {cf}\nVariables marché : {cm}")
    print("Walk-forward…")
    wf = backtest.walk_forward(F, cfg, cf, cm)
    comp, registre = backtest.comparer(wf.predictions, cfg)
    explo = backtest.exploration_confirmation(wf.predictions, cfg)
    pats = None if a.sans_patterns else patterns.rechercher(F, cote_min=1.0)
    avert = ""
    cotes_anterieures = any(c in df.columns and df[c].notna().mean() > 0.5 for c in ("cote_t30", "cote_t90", "cote_matin"))
    if not cotes_anterieures and "cote_finale" in df.columns and (df["cote_finale"] == df["cote_decision"]).mean() > 0.9:
        avert = ("> ⚠️ **Les cotes de décision de ce jeu sont les cotes FINALES** (aucune cote antérieure au départ "
                 "n'est disponible). Les résultats sont donc un majorant optimiste : en pratique, personne ne connaît "
                 "la cote finale au moment de parier.")
    chemin = report.ecrire(a.sortie, a.nom or Path(a.donnees).stem, resume, cfg, wf, comp, registre, F, pats,
                           explo, avert)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    print(comp[["strategie", "paris", "roi_pct", "roi_ic90_pct", "taux_reussite_pct", "rapport_moy_gagnants",
                "drawdown_max"]].to_string(index=False))
    print(f"\nRapport : {chemin}")


def cmd_patterns(a):
    df = schema.charger(a.donnees)
    F, _, _ = features.preparer(df, _config(a))
    r = patterns.rechercher(F, part_test=a.part_test, alpha=a.alpha, cote_min=a.cote_min)
    pd.set_option("display.width", 250)
    print(r.to_string(index=False))


def cmd_entrainer(a):
    cfg = _config(a)
    df = schema.charger(a.donnees)
    paquet = pronostic.entrainer(df, cfg)
    pronostic.sauver(paquet, a.modele)
    print(f"Modèle entraîné jusqu'au {paquet['fin_historique']} → {a.modele}")
    print(f"Cote minimale apprise sur l'historique : {paquet['cote_min_apprise']:g}")
    if cfg.selection.cote_max_auto:
        print(f"Cote maximale apprise sur l'historique : {paquet['cote_max_apprise']:g}")


def cmd_pronostiquer(a):
    paquet = pronostic.charger(a.modele)
    hist = schema.charger(a.historique)
    if a.partants:
        partants = pd.read_csv(a.partants)
    else:
        from .adapters import pmu_api
        partants = pmu_api.courses_du_jour(_date(a.jour), a.specialisation, a.cache)
        if partants.empty:
            print("Aucune course à venir trouvée.")
            return
    pron = pronostic.pronostiquer(paquet, hist, partants, a.bankroll)
    print(pronostic.resume_pronostics(pron))
    if a.sortie:
        pron.to_csv(a.sortie, index=False)
        print(f"\nDétail : {a.sortie}")


def cmd_releve(a):
    from .adapters import pmu_api
    n = pmu_api.releve_cotes(_date(a.jour), a.fichier, a.specialisation, a.cache)
    print(f"{n} cotes relevées → {a.fichier}")


def cmd_config(a):
    Config().save(a.sortie)
    print(f"Configuration par défaut écrite dans {a.sortie}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="simplegagnant", description="Pronostics Simple Gagnant orientés valeur")
    s = p.add_subparsers(dest="cmd", required=True)

    c = s.add_parser("construire-donnees", help="convertir une source vers le format canonique")
    c.add_argument("type", choices=["turf-engine", "hkracing", "pmu"])
    c.add_argument("--source", help="dossier source (turf-engine, hkracing)")
    c.add_argument("--sortie", required=True)
    c.add_argument("--horizon", default="cote_t15", help="turf-engine : cote de décision (cote_t15, cote_t30, cote_t90)")
    c.add_argument("--debut", help="pmu : date de début AAAA-MM-JJ")
    c.add_argument("--fin", help="pmu : date de fin AAAA-MM-JJ")
    c.add_argument("--specialisation", default="OFFLINE", choices=["OFFLINE", "INTERNET"])
    c.add_argument("--cache", default="cache_pmu")
    c.add_argument("--pause", type=float, default=1.0, help="secondes entre deux requêtes")
    c.add_argument("--releves", help="pmu : CSV de relevés de cotes (commande releve-cotes)")
    c.add_argument("--minutes-avant", type=int, default=15)
    c.set_defaults(f=cmd_construire)

    b = s.add_parser("backtest", help="backtest chronologique complet + rapport")
    b.add_argument("donnees")
    b.add_argument("--config")
    b.add_argument("--sortie", default="resultats/backtest")
    b.add_argument("--nom")
    b.add_argument("--sans-patterns", action="store_true")
    b.add_argument("--plat", action="store_true", help="version spécialisée courses de plat")
    b.set_defaults(f=cmd_backtest)

    t = s.add_parser("patterns", help="recherche de situations sous-cotées, validée hors échantillon")
    t.add_argument("donnees")
    t.add_argument("--part-test", type=float, default=0.4)
    t.add_argument("--alpha", type=float, default=0.10)
    t.add_argument("--cote-min", type=float, default=1.0)
    t.add_argument("--plat", action="store_true", help="courses de plat uniquement + patterns plat")
    t.add_argument("--config")
    t.set_defaults(f=cmd_patterns)

    e = s.add_parser("entrainer", help="entraîner le modèle final sur tout l'historique")
    e.add_argument("donnees")
    e.add_argument("--modele", default="modele.pkl")
    e.add_argument("--config")
    e.add_argument("--plat", action="store_true", help="modèle spécialisé courses de plat")
    e.set_defaults(f=cmd_entrainer)

    r = s.add_parser("pronostiquer", help="valeur et recommandations sur des courses à venir")
    r.add_argument("--modele", default="modele.pkl")
    r.add_argument("--historique", required=True, help="CSV canonique des courses passées")
    r.add_argument("--partants", help="CSV des partants à venir (format canonique, sans résultats)")
    r.add_argument("--jour", default="aujourdhui", help="sinon : interroger l'API PMU pour ce jour")
    r.add_argument("--specialisation", default="OFFLINE", choices=["OFFLINE", "INTERNET"])
    r.add_argument("--cache", default="cache_pmu")
    r.add_argument("--bankroll", type=float)
    r.add_argument("--sortie")
    r.set_defaults(f=cmd_pronostiquer)

    v = s.add_parser("releve-cotes", help="enregistrer les cotes actuelles (à planifier toutes les 5 min)")
    v.add_argument("--fichier", default="releves_cotes.csv")
    v.add_argument("--jour", default="aujourdhui")
    v.add_argument("--specialisation", default="OFFLINE", choices=["OFFLINE", "INTERNET"])
    v.add_argument("--cache", default="cache_pmu")
    v.set_defaults(f=cmd_releve)

    g = s.add_parser("config-defaut", help="écrire la configuration par défaut (JSON modifiable)")
    g.add_argument("--sortie", default="config.json")
    g.set_defaults(f=cmd_config)

    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    sys.exit(main())
