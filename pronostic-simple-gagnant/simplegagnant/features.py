"""Construction des variables explicatives — sans aucune information du futur.

Règles anti-fuite appliquées ici :
  1. Les variables « marché » n'utilisent que `cote_decision` et les cotes
     relevées AVANT la décision (cote_t90, cote_t30, cote_matin), jamais la
     cote finale ni le rapport.
  2. Les statistiques historiques (jockey, entraîneur, cheval) n'utilisent que
     les courses des JOURS PRÉCÉDENTS : la journée en cours est exclue, même
     pour les courses déjà courues, par prudence (heures de départ incertaines).
  3. Rien n'est normalisé ici avec des statistiques globales : centrage,
     réduction et imputation sont appris sur la fenêtre d'entraînement seule
     (voir model.py).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .musique import features_musique_df

# Variables du modèle « marché » (étape 2)
MARCHE = ["log_q", "derive_t90", "derive_t30"]


def probas_marche(df: pd.DataFrame, col: str = "cote_decision") -> pd.Series:
    """Probabilité implicite normalisée : (1/cote) / somme(1/cote) dans la course.

    La normalisation retire la marge de l'opérateur (prélèvement) : la somme
    des 1/cote vaut ≈ 1,18 au PMU, soit un taux de retour d'environ 85 %.
    """
    inv = 1.0 / df[col]
    return inv / inv.groupby(df["course_id"]).transform("sum")


def _historique(df: pd.DataFrame, cle: str, prefixe: str, lissage: float) -> pd.DataFrame:
    """Statistiques cumulées d'une entité (jockey, entraîneur…) sur les jours précédents.

    - n      : nombre de partants antérieurs
    - ae     : victoires réelles / victoires attendues par le marché (lissé vers 1).
               ae > 1 => le marché a SOUS-estimé cette entité par le passé.
    - tv     : taux de victoire lissé
    """
    out = pd.DataFrame(index=df.index)
    if cle not in df.columns or df[cle].isna().all():
        return out
    base = df[[cle, "date", "gagnant", "q_dec"]].copy()
    base[cle] = base[cle].fillna("?").astype(str)
    jour = base.groupby([cle, "date"], sort=True).agg(n=("gagnant", "size"), v=("gagnant", "sum"), e=("q_dec", "sum"))
    jour = jour.sort_index()
    cum = jour.groupby(level=0).cumsum() - jour  # cumul STRICTEMENT antérieur à la date
    cum = cum.rename(columns=lambda c: f"{c}_ant").reset_index()
    m = base[[cle, "date"]].merge(cum, on=[cle, "date"], how="left")
    m.index = df.index
    taux_moyen = 0.09  # ~1 / taille moyenne d'un peloton, a priori
    out[f"{prefixe}_n"] = np.log1p(m["n_ant"])
    out[f"{prefixe}_ae"] = np.log((m["v_ant"] + lissage * 0.1) / (m["e_ant"] + lissage * 0.1))
    out[f"{prefixe}_tv"] = (m["v_ant"] + lissage * taux_moyen) / (m["n_ant"] + lissage)
    return out


def _historique_cheval(df: pd.DataFrame) -> pd.DataFrame:
    """Sorties précédentes du cheval DANS LES DONNÉES (complète la musique).

    Calculé au niveau (cheval, jour) puis décalé d'un jour de course : seules
    les sorties des JOURS PRÉCÉDENTS sont utilisées, même si deux homonymes
    courent le même jour.
    """
    cols = ["cheval", "date", "gagnant", "position", "taille", "q_dec"]
    cols += [c for c in ["ecart", "poids_cheval", "distance", "valeur_handicap"] if c in df.columns]
    h = df[cols].copy()
    h["pos_rel"] = (h["position"] / h["taille"]).fillna(1.1)  # non classé = pire que dernier
    h["surplus"] = h["gagnant"] - h["q_dec"]                   # victoire - proba implicite du marché
    if "ecart" in h.columns:
        h["ecart"] = h["ecart"].clip(upper=30)
    agg = {"gagnant": "sum", "pos_rel": "mean", "surplus": "sum", "taille": "size"}
    agg.update({c: "mean" for c in ["ecart", "poids_cheval", "distance", "valeur_handicap"] if c in h.columns})
    j = h.groupby(["cheval", "date"], sort=True).agg(agg).rename(columns={"taille": "n"}).reset_index()
    g = j.groupby("cheval", sort=False)
    o = j[["cheval", "date"]].copy()
    o["chv_jours_repos"] = np.log1p((j["date"] - g["date"].shift(1)).dt.days.clip(upper=365))
    o["chv_pos_rel_prec"] = g["pos_rel"].shift(1)
    o["chv_pos_rel_moy3"] = g["pos_rel"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    o["chv_nb_courses"] = (g["n"].cumsum() - j["n"]).astype(float)
    o["chv_victoires_ant"] = g["gagnant"].cumsum() - j["gagnant"]
    o["chv_surplus_marche"] = g["surplus"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).sum())
    if "ecart" in j.columns:
        o["chv_ecart_prec"] = g["ecart"].shift(1)
        o["chv_ecart_moy3"] = g["ecart"].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    m = df[["cheval", "date"]].merge(o, on=["cheval", "date"], how="left")
    m.index = df.index
    # Variations par rapport à la sortie précédente (valeurs du jour = connues avant la course)
    prev = j[["cheval", "date"]].copy()
    for c in ["poids_cheval", "distance", "valeur_handicap"]:
        if c in j.columns:
            prev[c + "_prec"] = g[c].shift(1)
    pm = df[["cheval", "date"]].merge(prev, on=["cheval", "date"], how="left")
    pm.index = df.index
    if "poids_cheval" in df.columns:
        m["chv_var_poids_corps"] = df["poids_cheval"] - pm["poids_cheval_prec"]
    if "distance" in df.columns:
        m["chv_var_distance"] = np.log(df["distance"] / pm["distance_prec"])
    if "valeur_handicap" in df.columns:
        m["chv_var_valeur"] = df["valeur_handicap"] - pm["valeur_handicap_prec"]
    return m.drop(columns=["cheval", "date"])


def construire(df: pd.DataFrame, lissage: float = 30.0, profil: str = "general") -> pd.DataFrame:
    """Ajoute toutes les variables au DataFrame canonique (copie).

    profil="plat" : ajoute les variables pl_* propres au galop (module plat.py).
    """
    df = df.copy()
    df["taille"] = df.groupby("course_id")["num"].transform("size")
    df["q_dec"] = probas_marche(df, "cote_decision")
    df["log_q"] = np.log(df["q_dec"])
    df["rang_cote"] = df.groupby("course_id")["cote_decision"].rank(method="min")
    df["favori"] = (df["rang_cote"] == 1).astype(int)

    # --- Dynamique du marché avant la décision (argent « informé ») ---------
    for h in ["t90", "t30", "matin"]:
        col = f"cote_{h}"
        if col in df.columns and df[col].notna().mean() > 0.5:
            r = np.log(df[col] / df["cote_decision"])          # > 0 : la cote a baissé
            df[f"derive_{h}"] = r.replace([np.inf, -np.inf], np.nan).clip(-2, 2)
        else:
            df[f"derive_{h}"] = np.nan

    # --- Musique -------------------------------------------------------------
    if "musique" in df.columns:
        df = df.join(features_musique_df(df))

    # --- Variables catégorielles ----------------------------------------------
    if "ferrure" in df.columns:
        f = df["ferrure"].fillna("").astype(str).str.upper()
        df["fer_D4"] = (f == "D4").astype(float)
        df["fer_DA"] = (f == "DA").astype(float)
        df["fer_DP"] = (f == "DP").astype(float)
    if "oeilleres" in df.columns:
        o = df["oeilleres"].fillna("").astype(str).str.upper()
        df["oeilleres_oui"] = (~o.isin(["", "SANS_OEILLERES", "NAN", "NONE"])).astype(float)
    disc = df["discipline"].fillna("").astype(str).str.upper() if "discipline" in df.columns else pd.Series("", index=df.index)
    est_plat = disc.str.contains("PLAT").astype(float)
    est_trot = disc.str.contains("TROT|ATTELE|MONTE").astype(float)
    if "corde" in df.columns:
        rang_c = df["corde"].groupby(df["course_id"]).rank(method="average")
        rel = (rang_c - 1) / (df["taille"] - 1).clip(lower=1)
        df["corde_rel_plat"] = rel * est_plat
        auto = df["autostart"].fillna(0) if "autostart" in df.columns else 0.0
        df["corde_rel_autostart"] = rel * est_trot * auto
        # Deuxième ligne derrière l'autostart (numéros > 8 en général) : handicap connu
        df["deuxieme_ligne"] = ((df["corde"] > 8) & (est_trot * auto > 0)).astype(float)

    # --- Variables relatives à la course (poids, valeur, âge, gains) -----------
    for col in ["poids", "valeur_handicap", "age"]:
        if col in df.columns and df[col].notna().mean() > 0.3:
            df[f"{col}_rel"] = df[col] - df.groupby("course_id")[col].transform("mean")
    if "gains" in df.columns and df["gains"].notna().mean() > 0.3:
        lg = np.log1p(df["gains"].clip(lower=0))
        df["gains_rel"] = lg - lg.groupby(df["course_id"]).transform("mean")

    # --- Historique (jours précédents uniquement) -----------------------------
    # Les courses à venir (sans résultat) sont acceptées : leur résultat
    # inconnu est compté 0, ce qui est sans effet puisque seuls les jours
    # ANTÉRIEURS entrent dans les cumuls.
    if "gagnant" not in df.columns:
        df["gagnant"] = np.nan
    if "position" not in df.columns:
        df["position"] = np.nan
    a_venir = df["gagnant"].isna()
    df["gagnant"] = df["gagnant"].fillna(0)
    df = df.join(_historique(df, "jockey", "jk", lissage))
    df = df.join(_historique(df, "entraineur", "ent", lissage))
    df = df.join(_historique_cheval(df))
    df.loc[a_venir, "gagnant"] = np.nan
    if profil == "plat":
        from . import plat
        df = df.join(plat.construire(df))
    return df


def colonnes_fondamentales(df: pd.DataFrame, couverture_min: float = 0.6, profil: str = "general") -> list[str]:
    """Variables candidates de l'étape 1 présentes avec une couverture suffisante.

    Les variables de cotes sont EXCLUES : l'étape 1 doit fournir un avis
    indépendant du marché, que l'étape 2 combinera avec lui.
    """
    candidates = [
        "mus_n", "mus_inedit", "mus_reprise", "mus_derniere", "mus_moy3", "mus_moy5",
        "mus_victoires5", "mus_top3_5", "mus_incidents5", "mus_meme_disc5",
        "mus_derniere_gagnee", "fer_D4", "fer_DA", "fer_DP", "oeilleres_oui",
        "corde_rel_plat", "corde_rel_autostart", "deuxieme_ligne",
        "poids_rel", "valeur_handicap_rel", "age_rel", "gains_rel",
        "jk_n", "jk_ae", "jk_tv", "ent_n", "ent_ae", "ent_tv",
        "chv_jours_repos", "chv_pos_rel_prec", "chv_pos_rel_moy3", "chv_nb_courses",
        "chv_victoires_ant", "chv_surplus_marche", "chv_ecart_prec", "chv_ecart_moy3",
        "chv_var_poids_corps", "chv_var_distance", "chv_var_valeur",
    ]
    out = []
    for c in candidates:
        if c in df.columns and df[c].notna().mean() >= couverture_min and df[c].nunique(dropna=True) > 1:
            out.append(c)
    # Variables partiellement renseignées : gardées avec indicateur de valeur manquante
    for c in ["chv_jours_repos", "chv_pos_rel_prec", "chv_pos_rel_moy3", "chv_surplus_marche",
              "mus_derniere", "mus_moy3", "mus_moy5"]:
        if c in df.columns and c not in out and df[c].notna().mean() >= 0.15:
            out.append(c)
    if profil == "plat":
        from .plat import FONDAMENTALES_PLAT
        # Couverture plus tolérante : les champs plat (poids, valeur…) manquent
        # dans certaines sources ; un indicateur de valeur manquante est ajouté.
        for c in FONDAMENTALES_PLAT:
            if c in df.columns and c not in out and df[c].notna().mean() >= 0.3 and df[c].nunique(dropna=True) > 1:
                out.append(c)
    return out


def colonnes_marche(df: pd.DataFrame, profil: str = "general") -> list[str]:
    cols = list(MARCHE)
    if profil == "plat":
        from .plat import MARCHE_PLAT
        cols += MARCHE_PLAT
    return [c for c in cols if c in df.columns and df[c].notna().mean() > 0.5 and df[c].nunique() > 1]


def filtrer_disciplines(df: pd.DataFrame, disciplines: list | None) -> pd.DataFrame:
    """Garde les courses des disciplines demandées (comparaison par sous-chaîne :
    "PLAT" garde PLAT, PLAT_GAZON, PLAT_PSF…)."""
    if not disciplines or "discipline" not in df.columns:
        return df
    d = df["discipline"].fillna("").astype(str).str.upper()
    masque = np.zeros(len(df), bool)
    for x in disciplines:
        masque |= d.str.contains(str(x).upper(), regex=False).to_numpy()
    return df[masque]


def preparer(df: pd.DataFrame, cfg) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Variables calculées sur TOUT l'historique (les jockeys et chevaux gardent
    leur passé dans les autres disciplines), puis filtre des disciplines, puis
    choix des colonnes sur le sous-ensemble conservé."""
    profil = cfg.donnees.profil
    F = construire(df, cfg.modele.lissage, profil)
    F = filtrer_disciplines(F, cfg.donnees.disciplines)
    if F.empty:
        raise ValueError(f"Aucune course pour les disciplines {cfg.donnees.disciplines}.")
    return F, colonnes_fondamentales(F, profil=profil), colonnes_marche(F, profil)
