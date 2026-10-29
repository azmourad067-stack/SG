"""Rapport de backtest : Markdown + graphiques PNG + CSV des paris."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import backtest  # noqa: E402

# Palette de référence (validée pour daltonisme, 3 premières teintes)
BLEU, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
TEXTE, TEXTE2, GRILLE, FOND = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def _style(ax, titre, ylabel):
    ax.set_facecolor(FOND)
    ax.set_title(titre, loc="left", color=TEXTE, fontsize=11, fontweight="bold")
    ax.set_ylabel(ylabel, color=TEXTE2, fontsize=9)
    ax.tick_params(colors=TEXTE2, labelsize=8)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(GRILLE)
    ax.grid(axis="y", color=GRILLE, linewidth=0.8)
    ax.set_axisbelow(True)


def graphique_profits(registre: dict, chemin: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5), facecolor=FOND)
    series = [("Modèle value — mise fixe", BLEU), ("Marché seul value — mise fixe", AQUA),
              ("Favori systématique", ORANGE)]
    for nom, couleur in series:
        b = registre.get(nom)
        if b is None or b.empty:
            continue
        c = b.groupby("date")["profit"].sum().cumsum()
        ax.plot(c.index, c.values, color=couleur, linewidth=2, label=f"{nom} ({len(b)} paris)")
        ax.annotate(f"{c.values[-1]:+.0f}", (c.index[-1], c.values[-1]), xytext=(4, 0),
                    textcoords="offset points", color=TEXTE2, fontsize=8, va="center")
    ax.axhline(0, color=TEXTE2, linewidth=0.8)
    _style(ax, "Profit cumulé hors échantillon (mise de 1 par pari, rapports réels)", "unités")
    ax.legend(frameon=False, fontsize=8, labelcolor=TEXTE)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(chemin, dpi=130)
    plt.close(fig)


def graphique_biais(table: pd.DataFrame, trj: float, chemin: Path, titre: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 4), facecolor=FOND)
    x = np.arange(len(table))
    ax.bar(x, table["reel_sur_attendu"], color=BLEU, width=0.7)
    for i, (v, n) in enumerate(zip(table["reel_sur_attendu"], table["partants"])):
        ax.text(i, v - 0.03, f"{v:.2f}", ha="center", va="top", fontsize=8, color="white", fontweight="bold")
        ax.text(i, 0.03, f"n={n}", ha="center", va="bottom", fontsize=7, color="white")
    ax.axhline(1, color=TEXTE2, linewidth=1)
    ax.axhline(1 / trj, color=ORANGE, linewidth=1.5, linestyle="--")
    ax.text(len(table) - 0.5, 1 / trj + 0.02, f"seuil de rentabilité ≈ {1 / trj:.2f}", ha="right",
            fontsize=8, color=TEXTE)
    ax.set_ylim(0, max(1.35, float(table["reel_sur_attendu"].max()) + 0.1))
    ax.set_xticks(x, table["tranche"].astype(str))
    _style(ax, titre, "victoires réelles / attendues")
    ax.set_xlabel("tranche de cote de décision", color=TEXTE2, fontsize=9)
    fig.tight_layout()
    fig.savefig(chemin, dpi=130)
    plt.close(fig)


def graphique_bankroll(b: pd.DataFrame, initiale: float, chemin: Path, titre: str) -> None:
    if b is None or b.empty:
        return
    fig, ax = plt.subplots(figsize=(9, 3.5), facecolor=FOND)
    s = b.groupby("date")["bankroll"].last()
    ax.plot(s.index, s.values, color=BLEU, linewidth=2)
    ax.axhline(initiale, color=TEXTE2, linewidth=0.8)
    _style(ax, titre, "bankroll")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(chemin, dpi=130)
    plt.close(fig)


def _milliers(n: int) -> str:
    return f"{n:,}".replace(",", "\u202f")


def _md(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False)


def verdict(comp: pd.DataFrame, qual_attrs: dict, n_needed: int) -> str:
    m = comp.set_index("strategie").loc["Modèle value — mise fixe"]
    ecart, lo, hi = qual_attrs["ecart_vs_marche_brut"]
    if m.get("paris", 0) == 0:
        return ("**Aucun pari sélectionné** sur la période de test : avec ces paramètres, le modèle "
                "ne trouve jamais une valeur suffisante. Ce n'est pas un échec du code : c'est ce "
                "que fait un modèle qui ne s'écarte pas du marché.")
    if m.get("paris", 0) < 30:
        return (f"**Le modèle ne trouve presque jamais de valeur** ({int(m['paris'])} pari(s) sur toute la période "
                "de test). Ses probabilités restent collées à celles du marché (écart de log-vraisemblance "
                f"{ecart:+.4f} par course, IC 90 % [{lo:+.4f} ; {hi:+.4f}]) : avec la marge de sécurité "
                "demandée, aucun cheval n'est assez sous-coté. Le tableau de sensibilité montre ce que donnent "
                "des marges plus faibles.")
    roi_ic = str(m["roi_ic90_pct"]).strip("[]").split(";")
    borne_basse = float(roi_ic[0])
    if borne_basse > 0 and lo > 0:
        return ("**Signal positif à confirmer.** Le ROI hors échantillon et l'apport du modèle par "
                "rapport au marché sont tous deux positifs avec un intervalle de confiance à 90 % "
                "au-dessus de zéro. Cela reste un backtest : le valider en réel, à petites mises, "
                f"sur au moins {_milliers(n_needed)} paris avant d'engager une somme significative.")
    return ("**Pas de rentabilité démontrée.** "
            f"Le ROI hors échantillon du modèle est de {m['roi_pct']:+.1f} % sur {int(m['paris'])} paris, "
            f"avec un intervalle de confiance à 90 % de {m['roi_ic90_pct']} % : la vraie valeur peut "
            "aussi bien être fortement négative que positive. L'écart de log-vraisemblance du modèle par "
            f"rapport aux cotes brutes est de {ecart:+.4f} par course (IC 90 % [{lo:+.4f} ; {hi:+.4f}]) : "
            "le modèle n'apporte pas d'information prouvée au-delà du marché. Pour distinguer un ROI de "
            f"+5 % de zéro à la cote moyenne jouée, il faudrait environ {_milliers(n_needed)} paris.")


def ecrire(dossier: str | Path, nom_donnees: str, resume: dict, cfg, wf, comp: pd.DataFrame,
           registre: dict, F: pd.DataFrame, pats: pd.DataFrame | None, explo: dict,
           avertissement_cotes: str = "") -> Path:
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    pred = wf.predictions
    qual = backtest.qualite_probabilites(pred)
    debut_test = pd.Timestamp(pred["date"].min())
    seuil, table_avant = backtest.justifier_cote_min(F, debut_test)
    table_test = backtest.table_par_tranche(pred)
    overround = float((1 / F["cote_decision"]).groupby(F["course_id"]).sum().median())
    trj = 1 / overround
    if cfg.selection.cote_min_auto and "cote_min_apprise" in wf.plis:
        vals = sorted(set(wf.plis["cote_min_apprise"].round(2)))
        texte_seuil = "cote_min apprise dans chaque pli sur ses seules données d'entraînement (" + \
            ", ".join(f"{v:g}" for v in vals) + ")"
    else:
        texte_seuil = f"{cfg.selection.cote_min:g} (fixe)"
    if cfg.selection.cote_max_auto and "cote_max_appliquee" in wf.plis:
        vals = sorted(set(wf.plis["cote_max_appliquee"].round(2)))
        texte_plafond = "cote_max apprise par pli (" + ", ".join(f"{v:g}" for v in vals) + ")"
    else:
        texte_plafond = f"{cfg.selection.cote_max:g}"
    m = comp.set_index("strategie").loc["Modèle value — mise fixe"]
    cote_moy = float(m["cote_moy_paris"]) if m.get("paris", 0) else 10.0
    n_needed = backtest.paris_necessaires(cote_moy)

    graphique_profits(registre, dossier / "profit_cumule.png")
    graphique_biais(table_test, trj, dossier / "biais_favori_outsider.png",
                    "Le marché sous-estime-t-il certaines cotes ? (période de test)")
    nom_k = [k for k in registre if "Kelly" in k]
    if nom_k:
        graphique_bankroll(registre[nom_k[0]], cfg.mise.bankroll_initiale, dossier / "bankroll_kelly.png",
                           f"Bankroll — {nom_k[0]} (départ {cfg.mise.bankroll_initiale:g})")

    for k, b in registre.items():
        if k.startswith("Modèle") and not b.empty:
            b.to_csv(dossier / f"paris_{'kelly' if 'Kelly' in k else 'fixe'}.csv", index=False)
    pred.to_csv(dossier / "predictions_test.csv", index=False)
    comp.to_csv(dossier / "comparaison_strategies.csv", index=False)

    ecart_m = qual.attrs["ecart_vs_marche_brut"]
    ecart_r = qual.attrs["ecart_vs_marche_recalibre"]
    coef = wf.coefficients[-1]
    lignes = [
        f"# Rapport de backtest — {nom_donnees}",
        "",
        "## Verdict",
        "",
        verdict(comp, qual.attrs, n_needed),
        "",
        avertissement_cotes,
        "",
        "## Données",
        "",
        f"- Période : {resume['debut']} → {resume['fin']} ({resume['jours']} jours de courses)",
        f"- {resume['courses']} courses, {resume['partants']} partants",
        f"- Disciplines : {resume.get('disciplines', {})}",
        f"- Somme médiane des 1/cote par course : {overround:.3f} → taux de retour implicite ≈ {100 * trj:.1f} % "
        f"(prélèvement + arrondi ≈ {100 * (1 - trj):.1f} %)",
        "",
        "## Protocole (aucune information du futur)",
        "",
        f"- Validation chronologique par plis de {cfg.backtest.jours_par_pli} jours ; fenêtre {cfg.backtest.fenetre}, "
        f"au moins {cfg.backtest.jours_entrainement_min} jours d'entraînement avant le premier test.",
        f"- {len(wf.plis)} plis ; période de test : {pred['date'].min().date()} → {pred['date'].max().date()} "
        f"({pred['course_id'].nunique()} courses jamais vues par le modèle au moment de la prédiction).",
        "- Dans chaque pli : étape 1 (modèle fondamental, sans cotes) entraînée sur la partie ancienne de la fenêtre, "
        f"étape 2 (combinaison avec le marché) sur les {int(100 * cfg.modele.part_calibration)} % les plus récents.",
        "- Décision prise avec `cote_decision` ; gain calculé avec le **rapport réellement payé** (prélèvement inclus). "
        "Le rapport attendu tient compte de la dérive habituelle des cotes entre la décision et le départ.",
        f"- Disciplines : {cfg.donnees.disciplines or 'toutes'} ; profil de variables : {cfg.donnees.profil}.",
        f"- Sélection : cote ∈ [{texte_seuil} ; {texte_plafond}], "
        f"EV ≥ {100 * cfg.selection.marge_ev:.0f} %, p ≥ {cfg.selection.proba_min:g}, "
        f"au plus {cfg.selection.max_paris_par_course} cheval par course. Une course sans valeur n'est pas jouée.",
        f"- Remise sur mises : {100 * cfg.backtest.remise_mises:g} % ; commission sur gains : "
        f"{100 * cfg.backtest.commission_gains:g} %.",
        "",
        "## Comparaison des stratégies (mêmes courses de test)",
        "",
        "![Profit cumulé](profit_cumule.png)",
        "",
        _md(comp.drop(columns=[c for c in ["mise_totale"] if c in comp])),
        "",
        "Lecture : `roi_ic90_pct` est l'intervalle de confiance à 90 % du ROI (bootstrap des jours) ; "
        "`proba_roi_negatif` la proportion de rééchantillonnages où le ROI est ≤ 0. Pour le hasard, "
        f"moyenne de {cfg.backtest.n_simulations_hasard} simulations.",
        "",
    ]
    if nom_k:
        lignes += ["![Bankroll Kelly](bankroll_kelly.png)", ""]
    lignes += [
        "## Le modèle bat-il le marché ?",
        "",
        "Log-vraisemblance moyenne par course sur la période de test (plus haut = meilleures probabilités) :",
        "",
        _md(qual),
        "",
        f"- Écart modèle complet − cotes brutes : **{ecart_m[0]:+.4f}** par course, IC 90 % [{ecart_m[1]:+.4f} ; {ecart_m[2]:+.4f}]",
        f"- Écart modèle complet − marché recalibré : {ecart_r[0]:+.4f}, IC 90 % [{ecart_r[1]:+.4f} ; {ecart_r[2]:+.4f}]",
        "",
        "Repère : chez Benter (Hong Kong, 1994), l'apport du modèle sur le marché était modeste "
        "(pseudo-R² 0,1218 → 0,1396) et suffisait pourtant à être rentable. Un écart dont l'intervalle "
        "contient 0 signifie qu'aucun apport n'est démontré.",
        "",
        "Coefficients du dernier pli (variables standardisées) :",
        "",
        "```json",
        json.dumps({k: {kk: float(vv) for kk, vv in v.items()} for k, v in coef.items() if k != "pli"},
                   indent=1, ensure_ascii=False),
        "```",
        "",
        "## Justification du seuil de cote minimale",
        "",
        f"Calculée sur les données **antérieures au premier test** ({F['date'].min().date()} → "
        f"{(debut_test - pd.Timedelta(days=1)).date()}), selon une règle fixée à l'avance : on exclut les "
        "tranches de petites cotes consécutives où le marché ne sous-estime pas les chevaux (réel/attendu ≤ 1).",
        "",
        _md(table_avant),
        "",
        f"→ Seuil suggéré par les données : **{seuil:g}**. Seuil réellement appliqué : {texte_seuil}.",
        "",
        "Même tableau sur la période de test (contrôle, pas utilisé pour choisir) :",
        "",
        "![Biais favori-outsider](biais_favori_outsider.png)",
        "",
        _md(table_test),
        "",
        "`roi_tous_pct` : ROI obtenu en pariant TOUS les chevaux de la tranche aux rapports réels. "
        f"Un réel/attendu supérieur à ≈ {1 / trj:.2f} serait nécessaire pour être rentable.",
        "",
        "## Le favori gagne-t-il ? (période de test)",
        "",
        _md(backtest.table_par_rang(pred)),
        "",
        "`part_des_victoires_pct` : part des courses gagnées par chaque rang de cote. `reel_sur_attendu` > 1 : "
        "le marché sous-estime ce rang. `roi_systematique_pct` : ROI en jouant ce rang dans toutes les courses. "
        "Que la majorité des gagnants ne soient pas le favori ne suffit pas : il faut que leur cote paie plus "
        "que leur chance réelle, prélèvement compris.",
        "",
        "## Dérive de la cote entre la décision et le départ (gagnants)",
        "",
        _md(backtest.derive_rapport(pred)),
        "",
        "Un ratio médian < 1 : le gagnant paie moins que la cote vue au moment de parier "
        "(l'argent tardif fait baisser les cotes des chevaux qui gagnent).",
        "",
        "## Sensibilité aux paramètres (descriptif)",
        "",
        "ROI en mise fixe selon la cote minimale (lignes) et la marge d'EV (colonnes), nombre de paris entre parenthèses. "
        "**Choisir la meilleure case de ce tableau serait du surajustement** : il montre seulement la stabilité.",
        "",
    ]
    sens = backtest.sensibilite(pred, cfg)
    sens["cellule"] = sens.apply(lambda r: f"{r['roi_pct']:+.1f} % ({int(r['paris'])})" if r["paris"] else "—", axis=1)
    lignes += [_md(sens.pivot(index="cote_min", columns="marge_ev", values="cellule").reset_index()), ""]
    if explo and "metriques_confirmation" in explo:
        mc = explo["metriques_confirmation"]
        lignes += [
            "## Exploration puis confirmation",
            "",
            f"Paramètres choisis sur {explo['periode_exploration'][0]} → {explo['periode_exploration'][1]} : "
            f"{explo['parametres_choisis']} (ROI en exploration {explo['roi_exploration_pct']:+.1f} %).",
            f"Puis mesurés, figés, sur {explo['periode_confirmation'][0]} → {explo['periode_confirmation'][1]} : "
            f"**{mc.get('paris', 0)} paris, ROI {mc.get('roi_pct', float('nan')):+.1f} %**, IC 90 % {mc.get('roi_ic90_pct', '—')}.",
            "",
        ]
    elif explo:
        lignes += ["## Exploration puis confirmation", "", explo.get("message", ""), ""]
    if pats is not None and not pats.empty:
        cols = ["pattern", "n_entr", "AE_entr", "roi_pct_entr", "z_entr", "retenu_entr_BH", "n_test", "AE_test",
                "roi_pct_test", "valide_test"]
        lignes += [
            "## Patterns : situations sous-cotées par le marché ?",
            "",
            f"Entraînement avant le {pats.attrs.get('coupure')}, test ensuite. A/E = victoires réelles / attendues "
            f"selon les cotes. Retenu si significatif après correction de Benjamini-Hochberg (α = {pats.attrs.get('alpha')}) ; "
            "validé seulement si A/E > 1 et ROI > 0 en test.",
            "",
            _md(pats[cols]),
            "",
            f"→ **{int(pats['valide_test'].sum())} pattern(s) validé(s) hors échantillon** sur {len(pats)} testés.",
            "",
        ]
    lignes += [
        "## Limites",
        "",
        "- En pari mutuel, la cote finale n'est connue qu'après le départ et votre propre mise la fait baisser "
        "(négligeable pour de petites mises sur des masses de plusieurs milliers d'euros, pas pour des courses à faible enjeu).",
        "- Le nombre de paris nécessaire pour prouver un avantage est très élevé aux cotes moyennes jouées : "
        f"≈ {_milliers(n_needed)} paris pour distinguer +5 % de 0.",
        "- Les hyperparamètres (pénalités, marge, seuils) sont fixés a priori ; aucune optimisation n'a été faite "
        "sur la période de test.",
        "",
        "Fichiers : `predictions_test.csv` (toutes les probabilités hors échantillon), `paris_fixe.csv`, "
        "`paris_kelly.csv`, `comparaison_strategies.csv`.",
    ]
    chemin = dossier / "rapport.md"
    texte = "\n".join(lignes)
    chemin.write_text(texte, encoding="utf-8")
    ecrire_html(texte, dossier, nom_donnees)
    return chemin


CSS = """
:root{--fond:#fcfcfb;--texte:#0b0b0b;--texte2:#52514e;--bord:#e4e3df;--accent:#2a78d6;--code:#f3f2ee}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--fond:#1a1a19;--texte:#f0efec;--texte2:#c3c2b7;--bord:#383835;--accent:#3987e5;--code:#242423}}
:root[data-theme="dark"]{--fond:#1a1a19;--texte:#f0efec;--texte2:#c3c2b7;--bord:#383835;--accent:#3987e5;--code:#242423}
body{background:var(--fond);color:var(--texte);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;padding:24px 16px}
main{max-width:1100px;margin:auto}h1{font-size:1.6em}h2{margin-top:2em;border-bottom:1px solid var(--bord);padding-bottom:.2em}
table{border-collapse:collapse;font-size:12.5px;display:block;overflow-x:auto;max-width:100%}
th,td{border-bottom:1px solid var(--bord);padding:4px 8px;text-align:right;white-space:nowrap}th{color:var(--texte2)}
td:first-child,th:first-child{text-align:left}img{max-width:100%;background:#fcfcfb;border-radius:6px}
blockquote{border-left:3px solid var(--accent);margin:0;padding:4px 12px;color:var(--texte2)}
pre{background:var(--code);padding:10px;overflow-x:auto;font-size:12px;border-radius:6px}code{background:var(--code);padding:0 3px;border-radius:3px}
"""


def ecrire_html(texte: str, dossier: Path, titre: str) -> Path:
    """Version HTML autonome du rapport (images intégrées), lisible dans un navigateur."""
    import base64
    import re
    try:
        import markdown
    except ImportError:
        return None
    def img(m):
        f = dossier / m.group(2)
        if not f.exists():
            return ""
        b64 = base64.b64encode(f.read_bytes()).decode()
        return f'![{m.group(1)}](data:image/png;base64,{b64})'
    texte = re.sub(r"!\[([^\]]*)\]\(([^)]+\.png)\)", img, texte)
    corps = markdown.markdown(texte, extensions=["tables", "fenced_code"])
    html = (f'<!doctype html><html lang="fr"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Backtest Simple Gagnant</title><style>{CSS}</style></head>'
            f'<body><main>{corps}</main></body></html>')
    chemin = dossier / "rapport.html"
    chemin.write_text(html, encoding="utf-8")
    return chemin
