"""Lecture de la « musique » PMU.

La musique résume les dernières courses d'un cheval, de la plus récente
(à gauche) à la plus ancienne. Exemple : "1a3a(25)Da0m".

  chiffre 1-9 : place obtenue ; 0 = au-delà de la 9e place (non placé)
  D = disqualifié, A = arrêté, T = tombé, R = rétrogradé / refus
  lettre suivante = discipline : a attelé, m monté, p plat, h haies,
                   s steeple, c cross
  (25) = marqueur d'année : les performances à droite datent de 2025

La musique est publiée AVANT la course : l'utiliser n'introduit aucune fuite.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

_TOKEN = re.compile(r"\((\d{2})\)|(\d{1,2}|D|A|T|R|Ret|Dist)([amphsc])", re.IGNORECASE)

# Valeur numérique d'un incident (pire qu'un « 0 » = non placé, codé 10)
_INCIDENT = 12.0


def parser(musique: str | float | None) -> list[tuple[float, str, bool]]:
    """Retourne [(place_numerique, discipline, est_incident), ...] du plus récent au plus ancien.

    Le marqueur d'année est restitué comme ("ANNEE", ...) n'est pas conservé,
    mais sa position est utilisée par `features_musique` (coupure d'année).
    """
    if not isinstance(musique, str) or not musique.strip():
        return []
    out = []
    for m in _TOKEN.finditer(musique.replace(" ", "")):
        if m.group(1):
            out.append((np.nan, "ANNEE", False))
            continue
        tok, disc = m.group(2), m.group(3).lower()
        if tok.isdigit():
            v = float(tok)
            place = 10.0 if v == 0 else v
            out.append((place, disc, False))
        else:
            out.append((_INCIDENT, disc, True))
    return out


def features_musique(musique: str | float | None, discipline_course: str | None = None) -> dict:
    perf = parser(musique)
    annee_avant_premiere = bool(perf) and perf[0][1] == "ANNEE"
    courses = [p for p in perf if p[1] != "ANNEE"]
    n = len(courses)
    f = {
        "mus_n": float(n),
        "mus_inedit": float(n == 0),
        # Marqueur d'année AVANT toute performance => pas couru cette année (coupure)
        "mus_reprise": float(annee_avant_premiere),
    }
    if n == 0:
        f.update({k: np.nan for k in [
            "mus_derniere", "mus_moy3", "mus_moy5", "mus_victoires5", "mus_top3_5",
            "mus_incidents5", "mus_meme_disc5", "mus_derniere_gagnee"]})
        return f
    places = np.array([c[0] for c in courses])
    incid = np.array([c[2] for c in courses])
    discs = [c[1] for c in courses]
    p5 = places[:5]
    f["mus_derniere"] = places[0]
    f["mus_moy3"] = float(np.mean(places[:3]))
    f["mus_moy5"] = float(np.mean(p5))
    f["mus_victoires5"] = float(np.sum(p5 == 1))
    f["mus_top3_5"] = float(np.sum(p5 <= 3))
    f["mus_incidents5"] = float(np.sum(incid[:5]))
    f["mus_derniere_gagnee"] = float(places[0] == 1)
    if discipline_course:
        lettre = _lettre_discipline(discipline_course)
        f["mus_meme_disc5"] = float(np.mean([d == lettre for d in discs[:5]])) if lettre else np.nan
    else:
        f["mus_meme_disc5"] = np.nan
    return f


def _lettre_discipline(discipline: str) -> str | None:
    d = str(discipline).upper()
    if "MONTE" in d:
        return "m"
    if "ATTELE" in d or d == "TROT":
        return "a"
    if "PLAT" in d:
        return "p"
    if "HAIE" in d:
        return "h"
    if "STEEPLE" in d:
        return "s"
    if "CROSS" in d:
        return "c"
    return None


def features_musique_df(df: pd.DataFrame) -> pd.DataFrame:
    """Applique `features_musique` à toutes les lignes (colonne `musique`)."""
    disc = df["discipline"] if "discipline" in df.columns else pd.Series([None] * len(df), index=df.index)
    rows = [features_musique(m, d) for m, d in zip(df["musique"], disc)]
    return pd.DataFrame(rows, index=df.index)
