"""Interface Streamlit de l'outil simplegagnant.

Lancement (depuis le dossier pronostic-simple-gagnant) :
    pip install -r requirements.txt
    streamlit run app.py

Trois onglets :
  1. Pronostics : entraîne le modèle sur l'historique choisi puis évalue les
     courses à venir (API PMU du jour ou fichier CSV de partants).
  2. Backtest   : lance le backtest chronologique et affiche le verdict,
     la comparaison des stratégies et les graphiques.
  3. Données    : aperçu et contrôle de l'historique chargé.
"""

from __future__ import annotations

import copy
import hashlib
import io
import warnings
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from simplegagnant import backtest, features, patterns, pronostic, report, schema
from simplegagnant.config import Config

warnings.filterwarnings("ignore")
RACINE = Path(__file__).resolve().parent
DONNEES = RACINE / "donnees"
RESULTATS = RACINE / "resultats"

st.set_page_config(page_title="Simple Gagnant — value", page_icon="🐎", layout="wide")


# --------------------------------------------------------------------------- #
# Chargement et cache                                                          #
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner="Chargement de l'historique…")
def charger_historique(contenu: bytes) -> pd.DataFrame:
    return schema.normaliser(pd.read_csv(io.BytesIO(contenu), low_memory=False))


@st.cache_resource(show_spinner="Entraînement du modèle sur tout l'historique…")
def entrainer_modele(cle: str, _historique: pd.DataFrame, version_plat: bool) -> dict:
    # `cle` (empreinte des données) sert au cache ; le préfixe _ exclut le DataFrame du hachage
    cfg = Config.plat() if version_plat else Config()
    return pronostic.entrainer(_historique, cfg)


def empreinte(contenu: bytes) -> str:
    return hashlib.sha1(contenu).hexdigest()[:12]


def fichiers_donnees() -> list[Path]:
    return sorted(DONNEES.glob("*.csv")) if DONNEES.exists() else []


# --------------------------------------------------------------------------- #
# Barre latérale : historique et paramètres                                    #
# --------------------------------------------------------------------------- #
st.sidebar.title("🐎 Simple Gagnant")
st.sidebar.caption("Paris à valeur : la cote doit payer plus que la probabilité réelle.")

st.sidebar.header("Historique")
choix = [p.name for p in fichiers_donnees()] + ["Importer un fichier…"]
defaut = choix.index("pmu_turf_engine.csv") if "pmu_turf_engine.csv" in choix else 0
source_hist = st.sidebar.selectbox("Courses passées (format canonique)", choix, index=defaut)
if source_hist == "Importer un fichier…":
    fichier = st.sidebar.file_uploader("CSV canonique (voir schema.py)", type=["csv"], key="hist")
    contenu_hist = fichier.getvalue() if fichier else None
else:
    contenu_hist = (DONNEES / source_hist).read_bytes()

st.sidebar.header("Version")
version = st.sidebar.radio("Courses traitées", ["Toutes disciplines", "Plat uniquement"],
                           help="La version plat ajoute des variables propres au galop (corde × distance, "
                                "poids et décharge en handicap, oeillères 1re fois, changement de jockey, "
                                "forme en plat) et corrige le marché selon le rang de cote du cheval.")
version_plat = version == "Plat uniquement"

st.sidebar.header("Sélection des paris")
cote_min_auto = st.sidebar.checkbox("Cote minimale apprise sur les données", value=True,
                                    help="Exclut les petites cotes où le marché ne sous-estime pas les chevaux.")
cote_min = st.sidebar.number_input("Cote minimale (si non apprise)", 1.0, 20.0, 3.0, 0.5,
                                   disabled=cote_min_auto)
cote_max_auto = st.sidebar.checkbox("Cote maximale apprise sur les données", value=version_plat,
                                    help="Exclut les grosses cotes où le marché surestime les chevaux.")
cote_max = st.sidebar.number_input("Cote maximale (si non apprise)", 5.0, 200.0, 40.0, 5.0,
                                   disabled=cote_max_auto)
marge_ev = st.sidebar.slider("Marge de sécurité (EV minimale)", 0.0, 0.5, 0.10, 0.01,
                             help="On ne parie que si p × rapport attendu − 1 dépasse cette marge.")
proba_min = st.sidebar.slider("Probabilité minimale du modèle", 0.0, 0.2, 0.03, 0.01)

st.sidebar.header("Mise")
bankroll = st.sidebar.number_input("Bankroll (€)", 0.0, 1_000_000.0, 500.0, 50.0)
fraction_kelly = st.sidebar.slider("Fraction de Kelly", 0.05, 1.0, 0.25, 0.05)
plafond_pari = st.sidebar.slider("Plafond par cheval (% bankroll)", 0.5, 10.0, 2.0, 0.5) / 100


def appliquer_parametres(cfg: Config) -> Config:
    cfg = copy.deepcopy(cfg)
    s = cfg.selection
    s.cote_min_auto, s.cote_min, s.cote_max = cote_min_auto, cote_min, cote_max
    s.cote_max_auto = cote_max_auto
    if version_plat:
        cfg.donnees.disciplines, cfg.donnees.profil = ["PLAT"], "plat"
    s.marge_ev, s.proba_min = marge_ev, proba_min
    cfg.mise.fraction_kelly, cfg.mise.plafond_pari_pct = fraction_kelly, plafond_pari
    cfg.mise.bankroll_initiale = bankroll or 100.0
    return cfg


if contenu_hist is None:
    st.info("Choisissez ou importez un historique dans la barre latérale.")
    st.stop()

try:
    historique = charger_historique(contenu_hist)
except Exception as e:  # message lisible plutôt qu'une trace Python
    st.error(f"Historique illisible : {e}")
    st.stop()

onglet_pron, onglet_bt, onglet_donnees = st.tabs(["Pronostics", "Backtest", "Données"])

# --------------------------------------------------------------------------- #
# 1. Pronostics                                                                #
# --------------------------------------------------------------------------- #
with onglet_pron:
    st.subheader("Pronostics sur des courses à venir")
    st.warning("Aucune rentabilité n'est démontrée par le backtest actuel : utilisez ces pronostics "
               "à petites mises, pour les suivre en réel, pas comme une certitude.")
    col1, col2 = st.columns(2)
    with col1:
        mode = st.radio("Source des partants", ["API PMU (en direct)", "Fichier CSV"], horizontal=True)
    partants = None
    if mode == "API PMU (en direct)":
        with col2:
            jour = st.date_input("Jour", value=date.today())
            specialisation = st.selectbox("Masse de paris", ["OFFLINE", "INTERNET"],
                                          help="OFFLINE = points de vente ; INTERNET = pmu.fr (masse séparée).")
        if st.button("Récupérer les courses à venir", type="primary"):
            from simplegagnant.adapters import pmu_api
            try:
                with st.spinner("Interrogation de l'API PMU (1 requête/seconde)…"):
                    st.session_state["partants"] = pmu_api.courses_du_jour(
                        jour, specialisation, RACINE / "cache_pmu")
            except Exception as e:
                st.error(f"API PMU injoignable : {e}")
    else:
        with col2:
            f = st.file_uploader("Partants à venir (format canonique, sans résultats)", type=["csv"], key="part")
        if f is not None:
            st.session_state["partants"] = pd.read_csv(f)
    partants = st.session_state.get("partants")

    if partants is not None and len(partants):
        paquet = entrainer_modele(empreinte(contenu_hist), historique, version_plat)
        paquet = dict(paquet)
        paquet["cfg"] = appliquer_parametres(paquet["cfg"])
        try:
            pron = pronostic.pronostiquer(paquet, historique, partants, bankroll or None)
        except Exception as e:
            st.error(f"Impossible d'évaluer ces partants : {e}")
            st.stop()

        paris = pron[pron["pari"] == 1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Courses évaluées", pron["course_id"].nunique())
        c2.metric("Paris à valeur", len(paris))
        bas = f"{paquet['cote_min_apprise']:g}" if cote_min_auto else f"{cote_min:g}"
        haut = f"{paquet['cote_max_apprise']:g}" if cote_max_auto else f"{cote_max:g}"
        c3.metric("Cotes jouables", f"{bas} à {haut}")
        if "mise_kelly" in paris:
            c4.metric("Mise totale (Kelly)", f"{paris['mise_kelly'].sum():.2f} €")

        st.markdown("#### Paris recommandés")
        if paris.empty:
            st.info("Aucun cheval ne présente assez de valeur : ne rien jouer est la bonne décision.")
        else:
            vue = paris.assign(
                p_modele=(100 * paris["p_modele"]).round(1),
                p_marche=(100 * paris["p_marche"]).round(1),
                ev=(100 * paris["ev"]).round(0),
            )[[c for c in ["heure_depart", "course_id", "num", "cheval", "cote_decision", "p_marche",
                           "p_modele", "ev", "mise_kelly"] if c in paris]]
            st.dataframe(vue.rename(columns={"cote_decision": "cote", "p_marche": "p marché %",
                                             "p_modele": "p modèle %", "ev": "EV %", "mise_kelly": "mise €"}),
                         hide_index=True, use_container_width=True)
            st.caption("La cote PMU bouge jusqu'au départ : le rapport payé peut être nettement plus bas.")

        st.markdown("#### Détail par course")
        for cid, g in pron.groupby("course_id", sort=False):
            n_paris = int(g["pari"].sum())
            with st.expander(f"{cid} — {'✅ ' + str(n_paris) + ' pari' if n_paris else 'aucun pari'}"):
                st.dataframe(g.drop(columns=["date", "course_id"], errors="ignore")
                             .sort_values("p_modele", ascending=False), hide_index=True, use_container_width=True)
        st.download_button("Télécharger les pronostics (CSV)", pron.to_csv(index=False).encode("utf-8"),
                           "pronostics.csv", "text/csv")
    else:
        st.caption("Récupérez les courses du jour ou importez un fichier de partants pour obtenir des pronostics.")

# --------------------------------------------------------------------------- #
# 2. Backtest                                                                  #
# --------------------------------------------------------------------------- #
with onglet_bt:
    st.subheader("Backtest chronologique (courses jamais vues par le modèle)")
    st.caption("Le modèle est ré-entraîné à chaque pli sur le passé seulement ; les gains utilisent les "
               "rapports réellement payés. Comptez de 30 s à quelques minutes selon la taille des données.")
    c1, c2, c3 = st.columns(3)
    jours_min = c1.number_input("Jours d'entraînement avant le 1er test", 7, 3650, 21, 7)
    jours_pli = c2.number_input("Taille d'un pli (jours)", 1, 365, 7, 1)
    avec_patterns = c3.checkbox("Rechercher les patterns", value=True)

    if st.button("Lancer le backtest", type="primary"):
        cfg = appliquer_parametres(Config())
        cfg.backtest.jours_entrainement_min = int(jours_min)
        cfg.backtest.jours_par_pli = int(jours_pli)
        nom = (Path(source_hist).stem if source_hist != "Importer un fichier…" else "import") + \
            ("_plat" if version_plat else "")
        sortie = RESULTATS / f"app_{nom}"
        try:
            with st.spinner("Construction des variables…"):
                F, cf, cm = features.preparer(historique, cfg)
            with st.spinner("Walk-forward en cours…"):
                wf = backtest.walk_forward(F, cfg, cf, cm, verbeux=False)
                comp, registre = backtest.comparer(wf.predictions, cfg)
                explo = backtest.exploration_confirmation(wf.predictions, cfg)
                pats = patterns.rechercher(F) if avec_patterns else None
                resume = schema.resume(features.filtrer_disciplines(historique, cfg.donnees.disciplines))
                report.ecrire(sortie, nom, resume, cfg, wf, comp, registre, F, pats, explo)
            st.session_state["bt"] = {"sortie": str(sortie), "comp": comp,
                                      "qual": backtest.qualite_probabilites(wf.predictions)}
        except ValueError as e:
            st.error(f"Backtest impossible : {e}")

    bt = st.session_state.get("bt")
    if bt:
        sortie = Path(bt["sortie"])
        texte = (sortie / "rapport.md").read_text(encoding="utf-8")
        verdict = texte.split("## Verdict", 1)[1].split("## Données", 1)[0].strip()
        st.markdown("### Verdict")
        st.markdown(verdict)
        comp = bt["comp"]
        st.markdown("### Comparaison des stratégies")
        st.dataframe(comp, hide_index=True, use_container_width=True)
        for img, legende in [("profit_cumule.png", "Profit cumulé hors échantillon"),
                             ("bankroll_kelly.png", "Bankroll en Kelly fractionné"),
                             ("biais_favori_outsider.png", "Victoires réelles / attendues par tranche de cote")]:
            if (sortie / img).exists():
                st.image(str(sortie / img), caption=legende, use_container_width=True)
        with st.expander("Rapport complet"):
            import re
            st.markdown(re.sub(r"!\[[^\]]*\]\([^)]+\)", "", texte))
        html = sortie / "rapport.html"
        if html.exists():
            st.download_button("Télécharger le rapport HTML", html.read_bytes(), "rapport.html", "text/html")
    else:
        anciens = sorted(p for p in RESULTATS.glob("*/rapport.md")) if RESULTATS.exists() else []
        if anciens:
            st.markdown("#### Rapports déjà produits")
            for p in anciens:
                with st.expander(p.parent.name):
                    for img in ["profit_cumule.png", "biais_favori_outsider.png"]:
                        if (p.parent / img).exists():
                            st.image(str(p.parent / img), use_container_width=True)
                    import re
                    st.markdown(re.sub(r"!\[[^\]]*\]\([^)]+\)", "", p.read_text(encoding="utf-8")))

# --------------------------------------------------------------------------- #
# 3. Données                                                                   #
# --------------------------------------------------------------------------- #
with onglet_donnees:
    st.subheader("Historique chargé" + (" — courses de plat" if version_plat else ""))
    historique_vue = features.filtrer_disciplines(historique, ["PLAT"] if version_plat else None)
    r = schema.resume(historique_vue)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Courses", f"{r['courses']:,}".replace(",", " "))
    c2.metric("Partants", f"{r['partants']:,}".replace(",", " "))
    c3.metric("Période", f"{r['debut']} → {r['fin']}")
    if "somme_1_sur_cote_moyenne" in r:
        c4.metric("Taux de retour implicite", f"{100 / r['somme_1_sur_cote_moyenne']:.1f} %")
    if "disciplines" in r:
        st.bar_chart(pd.Series(r["disciplines"], name="courses"))
    st.markdown("#### Biais favori-outsider sur tout l'historique")
    st.caption("Victoires réelles / attendues selon les cotes, et ROI si l'on pariait tous les chevaux de la tranche.")
    F0 = historique_vue.assign(q_dec=features.probas_marche(historique_vue))
    st.dataframe(backtest.table_par_tranche(F0), hide_index=True, use_container_width=True)
    st.markdown("#### Le favori gagne-t-il ?")
    st.caption("Part des victoires selon le rang du gagnant dans la cote, réussite réelle / attendue "
               "et ROI si l'on jouait systématiquement ce rang (rapports réels).")
    st.dataframe(backtest.table_par_rang(F0), hide_index=True, use_container_width=True)
    st.markdown("#### Aperçu")
    st.dataframe(historique_vue.head(200), use_container_width=True)
