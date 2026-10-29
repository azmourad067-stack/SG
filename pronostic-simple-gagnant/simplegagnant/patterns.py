"""Recherche de situations où le marché sous-évalue un cheval, avec validation
hors échantillon.

Méthode :
  1. Une liste FIXÉE À L'AVANCE de situations candidates (« patterns »),
     toutes calculables avant la course (musique, ferrure, dérive de cote…).
  2. Période d'ENTRAÎNEMENT (la plus ancienne) : pour chaque pattern, on
     compare les victoires réelles aux victoires attendues selon le marché
     (somme des probabilités implicites q). Un rapport réel/attendu (A/E)
     > 1 signifie que le marché a sous-estimé ces chevaux.
     Test statistique : z = (V - E) / sqrt(Σ q(1-q)), puis correction de
     Benjamini-Hochberg pour les tests multiples (sinon, sur 30 patterns,
     plusieurs paraîtraient « significatifs » par pur hasard).
  3. Période de TEST (la plus récente, jamais vue) : seuls les patterns
     retenus à l'étape 2 sont re-mesurés. Un pattern n'est « validé » que si
     son A/E reste > 1 ET si son ROI réel reste positif en test.

Attention : un A/E > 1 ne suffit pas à gagner de l'argent. Avec un taux de
retour d'environ 85 %, il faut que le marché sous-estime le cheval de plus
de ~18 % (A/E > 1/0,85) pour que parier aux rapports réels soit rentable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm


def candidats(F: pd.DataFrame) -> dict[str, pd.Series]:
    """Patterns candidats. Chacun est un masque booléen calculé avant la course."""
    c: dict[str, pd.Series] = {}
    has = lambda col: col in F.columns and F[col].notna().mean() > 0.3  # noqa: E731

    if has("derive_t90"):
        c["Cote en forte baisse T-90 → décision (> 25 %)"] = F["derive_t90"] > np.log(1.25)
        c["Cote en forte hausse T-90 → décision (> 25 %)"] = F["derive_t90"] < -np.log(1.25)
    if has("derive_t30"):
        c["Cote en baisse T-30 → décision (> 10 %)"] = F["derive_t30"] > np.log(1.10)
    if has("mus_derniere_gagnee"):
        c["A gagné sa dernière course"] = F["mus_derniere_gagnee"] == 1
    if has("mus_incidents5"):
        c["≥ 2 incidents (D/A/T) sur 5 dernières"] = F["mus_incidents5"] >= 2
        c["Aucun incident sur 5 dernières (trot)"] = (F["mus_incidents5"] == 0) & F["discipline"].astype(str).str.contains("TROT")
    if has("mus_top3_5"):
        c["≥ 3 podiums sur 5 dernières"] = F["mus_top3_5"] >= 3
    if has("mus_moy3"):
        c["Musique faible (moyenne 3 dernières ≥ 8)"] = F["mus_moy3"] >= 8
    if has("mus_reprise"):
        c["Reprise (pas couru cette année)"] = F["mus_reprise"] == 1
    if "mus_inedit" in F.columns:
        c["Inédit"] = F["mus_inedit"] == 1
    if "fer_D4" in F.columns:
        c["Déferré des 4 pieds"] = F["fer_D4"] == 1
        c["Déferré antérieurs ou postérieurs"] = (F["fer_DA"] == 1) | (F["fer_DP"] == 1)
    if "deuxieme_ligne" in F.columns:
        c["Autostart, 2e ligne"] = F["deuxieme_ligne"] == 1
    if "corde_rel_plat" in F.columns:
        plat = F["discipline"].astype(str).str.contains("PLAT")
        c["Plat, corde intérieure (1er tiers)"] = plat & (F["corde_rel_plat"] <= 1 / 3)
        c["Plat, corde extérieure (dernier tiers)"] = plat & (F["corde_rel_plat"] >= 2 / 3)
    if has("jk_ae"):
        c["Jockey/driver historiquement sous-coté (A/E passé > 1,2)"] = F["jk_ae"] > np.log(1.2)
        c["Jockey/driver historiquement sur-coté (A/E passé < 0,8)"] = F["jk_ae"] < np.log(0.8)
    if has("ent_ae"):
        c["Entraîneur historiquement sous-coté (A/E passé > 1,2)"] = F["ent_ae"] > np.log(1.2)
    if has("chv_jours_repos"):
        c["Recourt dans les 10 jours"] = F["chv_jours_repos"] <= np.log1p(10)
        c["Absent depuis > 60 jours"] = F["chv_jours_repos"] > np.log1p(60)
    if has("chv_surplus_marche"):
        c["A fait mieux que ses cotes (surplus passé > 0)"] = F["chv_surplus_marche"] > 0
    if has("chv_var_valeur"):
        c["Valeur handicap en baisse"] = F["chv_var_valeur"] < 0
    if has("chv_var_distance"):
        c["Changement de distance > 15 %"] = F["chv_var_distance"].abs() > np.log(1.15)
    if "rang_cote" in F.columns:
        c["2e favori"] = F["rang_cote"] == 2
        c["Outsider 10-25 dans un petit peloton (≤ 8)"] = (F["cote_decision"].between(10, 25)) & (F["taille"] <= 8)
    # --- Patterns propres au plat (si les variables pl_* existent) ---------------
    if "pl_favori" in F.columns and F["pl_favori"].notna().any():
        grand = F["taille"] >= 14
        c["Plat : favori dans un grand peloton (≥ 14)"] = (F["pl_favori"] == 1) & grand
        c["Plat : 2e à 5e favori"] = F["pl_rang_2_5"] == 1
        c["Plat : 2e à 5e favori dans un grand peloton"] = (F["pl_rang_2_5"] == 1) & grand
        if "distance" in F.columns and "corde_rel_plat" in F.columns:
            sprint = F["distance"] <= 1400
            c["Plat : sprint, corde dans le 1er quart"] = sprint & (F["corde_rel_plat"] <= 0.25)
            c["Plat : sprint, corde dans le dernier quart"] = sprint & (F["corde_rel_plat"] >= 0.75)
        if has("pl_poids_rel_handicap"):
            h = F["pl_poids_rel_handicap"]
            c["Plat : handicap, parmi les plus chargés (+2 kg)"] = h >= 2
            c["Plat : handicap, parmi les plus légers (−2 kg)"] = h <= -2
        if has("pl_decharge"):
            c["Plat : jockey avec décharge"] = F["pl_decharge"] > 0
        if has("pl_oeilleres_1re_fois"):
            c["Plat : oeillères pour la 1re fois"] = F["pl_oeilleres_1re_fois"] == 1
        if has("pl_changement_jockey"):
            c["Plat : changement de jockey"] = F["pl_changement_jockey"] == 1
        if has("pl_var_valeur"):
            c["Plat : valeur en baisse d'au moins 2 points"] = F["pl_var_valeur"] <= -2
        if has("pl_victoire_plat_recente"):
            c["Plat : victoire en plat dans les 3 dernières"] = F["pl_victoire_plat_recente"] == 1
        if has("pl_forme_plat_moy3"):
            c["Plat : forme plat faible (moyenne ≥ 7) mais ≤ 5e favori"] = (F["pl_forme_plat_moy3"] >= 7) & (F["rang_cote"] <= 5)
    return {k: v.fillna(False).astype(bool) for k, v in c.items()}


def _stats(d: pd.DataFrame) -> dict:
    v = d["gagnant"].sum()
    e = d["q_dec"].sum()
    var = (d["q_dec"] * (1 - d["q_dec"])).sum()
    retour = np.where(d["gagnant"] == 1, d["rapport_gagnant"].fillna(0), 0.0).sum()
    z = (v - e) / np.sqrt(var) if var > 0 else 0.0
    return {"n": int(len(d)), "victoires": int(v), "attendues": round(float(e), 1),
            "AE": round(float(v / e), 3) if e > 0 else np.nan,
            "roi_pct": round(100 * (retour / len(d) - 1), 1) if len(d) else np.nan,
            "z": round(float(z), 2), "p_unilat": float(1 - norm.cdf(z))}


def benjamini_hochberg(p: np.ndarray, alpha: float = 0.10) -> np.ndarray:
    p = np.asarray(p)
    n = len(p)
    ordre = np.argsort(p)
    seuil = alpha * (np.arange(1, n + 1) / n)
    ok = p[ordre] <= seuil
    k = np.max(np.nonzero(ok)[0]) + 1 if ok.any() else 0
    res = np.zeros(n, bool)
    res[ordre[:k]] = True
    return res


def rechercher(F: pd.DataFrame, part_test: float = 0.4, alpha: float = 0.10,
               cote_min: float = 1.0, n_min: int = 100) -> pd.DataFrame:
    """Retourne une ligne par pattern : statistiques entraînement, sélection BH, statistiques test."""
    F = F[F["cote_decision"] >= cote_min]
    jours = np.sort(F["date"].unique())
    coupe = jours[int(len(jours) * (1 - part_test))]
    tr_mask = F["date"] < coupe
    lignes = []
    for nom, m in candidats(F).items():
        tr = F[m & tr_mask]
        te = F[m & ~tr_mask]
        if len(tr) < n_min:
            continue
        s_tr, s_te = _stats(tr), _stats(te) if len(te) else {}
        lignes.append({"pattern": nom,
                       **{f"{k}_entr": v for k, v in s_tr.items()},
                       **{f"{k}_test": v for k, v in s_te.items() if k != "p_unilat"}})
    out = pd.DataFrame(lignes)
    if out.empty:
        return out
    out["retenu_entr_BH"] = benjamini_hochberg(out["p_unilat_entr"].to_numpy(), alpha)
    out["valide_test"] = out["retenu_entr_BH"] & (out["AE_test"] > 1) & (out["roi_pct_test"] > 0)
    out.attrs["coupure"] = str(pd.Timestamp(coupe).date())
    out.attrs["alpha"] = alpha
    return out.sort_values("p_unilat_entr").reset_index(drop=True)
