"""Collecteur de l'API publique « turfinfo » du PMU → format canonique.

À LANCER SUR VOTRE MACHINE : cette API n'était pas joignable depuis
l'environnement où l'outil a été développé.

Points d'accès utilisés (non documentés officiellement par le PMU ; relevés
dans des projets open source et vérifiés sur de vraies réponses JSON) :
  {BASE}/rest/client/{V}/programme/{JJMMAAAA}
  {BASE}/rest/client/{V}/programme/{JJMMAAAA}/R{r}/C{c}/participants
  {BASE}/rest/client/{V}/programme/{JJMMAAAA}/R{r}/C{c}/rapports-definitifs
paramètre `specialisation` : OFFLINE (points de vente, masse PMU « en dur »)
ou INTERNET (masse séparée de pmu.fr, cotes et rapports différents).

PIÈGE MAJEUR (fuite d'information) : sur une course passée, le champ
`dernierRapportDirect` contient la cote FINALE, horodatée après le départ.
Pour l'historique, la cote de DÉCISION est donc `dernierRapportReference`
(relevée environ 30 min avant le départ, horodatage vérifié ici), ou mieux,
vos propres relevés de cotes faits en direct (commande `releve-cotes`).

Conditions d'utilisation : les données PMU sont protégées (droit des bases
de données). Usage personnel, débit faible (1 requête/s par défaut), pas de
redistribution.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "https://online.turfinfo.api.pmu.fr/rest/client/1/programme"
UA = "Mozilla/5.0 (usage personnel ; outil d'analyse simplegagnant)"


class ClientPMU:
    def __init__(self, cache: str | Path = "cache_pmu", specialisation: str = "OFFLINE",
                 pause: float = 1.0, base: str = BASE):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.specialisation = specialisation
        self.pause = pause
        self.base = base
        self._dernier = 0.0

    def _get(self, chemin: str, utiliser_cache: bool = True) -> dict | list | None:
        fichier = self.cache / self.specialisation / (chemin.replace("/", "_") + ".json")
        if utiliser_cache and fichier.exists():
            return json.loads(fichier.read_text())
        attente = self.pause - (time.time() - self._dernier)
        if attente > 0:
            time.sleep(attente)
        url = f"{self.base}/{chemin}?specialisation={self.specialisation}"
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        for essai in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    self._dernier = time.time()
                    if r.status == 204:
                        return None
                    data = json.loads(r.read().decode("utf-8"))
                    break
            except urllib.error.HTTPError as e:
                self._dernier = time.time()
                if e.code in (204, 400, 404):
                    return None
                if essai == 2:
                    raise
                time.sleep(5 * (essai + 1))
            except urllib.error.URLError:
                if essai == 2:
                    raise
                time.sleep(5 * (essai + 1))
        if utiliser_cache:
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(json.dumps(data))
        return data

    def programme(self, jour: date, utiliser_cache: bool = True):
        return self._get(jour.strftime("%d%m%Y"), utiliser_cache)

    def participants(self, jour: date, r: int, c: int, utiliser_cache: bool = True):
        return self._get(f"{jour.strftime('%d%m%Y')}/R{r}/C{c}/participants", utiliser_cache)

    def rapports(self, jour: date, r: int, c: int):
        return self._get(f"{jour.strftime('%d%m%Y')}/R{r}/C{c}/rapports-definitifs")


# --------------------------------------------------------------------------- #
# Conversion JSON PMU -> lignes canoniques                                     #
# --------------------------------------------------------------------------- #
def _ferrure(v) -> str:
    v = str(v or "").upper()
    if "ANTERIEURS_POSTERIEURS" in v or v in ("D4", "DEFERRE_4"):
        return "D4"
    if "ANTERIEURS" in v:
        return "DA"
    if "POSTERIEURS" in v:
        return "DP"
    return "FERRE"


def _discipline(c: dict) -> str:
    d = str(c.get("discipline") or c.get("specialite") or "").upper()
    s = str(c.get("specialite") or "").upper()
    if "ATTELE" in d or "ATTELE" in s:
        return "TROT_ATTELE"
    if "MONTE" in d or "MONTE" in s:
        return "TROT_MONTE"
    if "HAIE" in d or "HAIE" in s:
        return "HAIES"
    if "STEEPLE" in d or "STEEPLE" in s:
        return "STEEPLE"
    if "CROSS" in d or "CROSS" in s:
        return "CROSS"
    return "PLAT" if "PLAT" in d or "PLAT" in s else (d or "INCONNUE")


def _ms(v) -> pd.Timestamp | None:
    return pd.Timestamp(int(v), unit="ms", tz="UTC") if v else None


def lignes_course(jour: date, reunion: dict, course: dict, participants: dict,
                  rapports: list | None, internet: bool, mode: str = "historique") -> list[dict]:
    """mode="historique" : cote_decision = cote de référence (antérieure au départ) ;
    mode="direct" : cote_decision = dernière cote affichée maintenant (course à venir)."""
    r, c = reunion["numOfficiel"], course["numOrdre"]
    depart = _ms(course.get("heureDepart"))
    hippo = (reunion.get("hippodrome") or {}).get("libelleCourt", "")
    type_sg = "E_SIMPLE_GAGNANT" if internet else "SIMPLE_GAGNANT"
    payes: dict[int, float] = {}
    rembourse = False
    for bloc in rapports or []:
        if bloc.get("typePari") == type_sg:
            rembourse = bool(bloc.get("rembourse"))
            for rap in bloc.get("rapports", []):
                for num in str(rap.get("combinaison", "")).replace(" ", "").split("-"):
                    if num.isdigit():
                        # dividendePourUnEuro est exprimé en centimes
                        payes[int(num)] = rap["dividendePourUnEuro"] / 100.0
    lignes = []
    for p in participants.get("participants", []):
        ref = p.get("dernierRapportReference") or {}
        direct = p.get("dernierRapportDirect") or {}
        t_ref, t_dir = _ms(ref.get("dateRapport")), _ms(direct.get("dateRapport"))
        if mode == "historique":
            # Cote de référence seulement si elle a bien été relevée AVANT le départ
            cote_dec = ref.get("rapport") if (t_ref is not None and depart is not None and t_ref < depart) else np.nan
            cote_fin = direct.get("rapport") if (t_dir is not None and depart is not None and t_dir >= depart) else np.nan
        else:
            cote_dec, cote_fin = direct.get("rapport", np.nan), np.nan
        gains = (p.get("gainsParticipant") or {}).get("gainsCarriere")
        lignes.append({
            "course_id": f"{jour.isoformat()}_R{r}C{c}",
            "date": jour.isoformat(),
            "heure_depart": depart.isoformat() if depart is not None else None,
            "hippodrome": hippo,
            "discipline": _discipline(course),
            "distance": course.get("distance"),
            "corde_sens": course.get("corde"),
            "autostart": float("AUTOSTART" in str(course.get("categorieParticularite", "")).upper()
                               or "AUTOSTART" in str(course.get("conditions", "")).upper()),
            "num": p.get("numPmu"),
            "cheval": p.get("nom"),
            "jockey": p.get("driver") or p.get("jockey"),
            "entraineur": p.get("entraineur"),
            "musique": p.get("musique"),
            "corde": p.get("placeCorde"),
            "ferrure": _ferrure(p.get("deferre")),
            "oeilleres": p.get("oeilleres"),
            "age": p.get("age"),
            "sexe": p.get("sexe"),
            # Poids attribué et poids réellement porté (décharge / surcharge), en kg
            "poids": (p["handicapPoids"] / 10.0) if p.get("handicapPoids") else
                     ((p["poidsConditionMonte"] / 10.0) if p.get("poidsConditionMonte") else np.nan),
            "poids_porte": (p["poidsConditionMonte"] / 10.0) if p.get("poidsConditionMonte") else np.nan,
            "changement_jockey": float(bool(p.get("driverChange"))) if "driverChange" in p else np.nan,
            "nb_courses": p.get("nombreCourses"),
            "nb_victoires": p.get("nombreVictoires"),
            "nb_places": p.get("nombrePlaces"),
            "categorie": course.get("categorieParticularite"),
            "allocation": course.get("montantPrix"),
            "type_piste": course.get("typePiste"),
            "terrain": (course.get("penetrometre") or {}).get("intitule"),
            "valeur_handicap": p.get("handicapValeur"),
            "gains": gains / 100.0 if gains is not None else np.nan,
            "distance_handicap": p.get("handicapDistance"),
            "cote_decision": cote_dec,
            "heure_cote_decision": (t_ref.isoformat() if (mode == "historique" and t_ref is not None)
                                    else datetime.now(timezone.utc).isoformat()),
            "cote_finale": cote_fin,
            "non_partant": int(str(p.get("statut", "")).upper() == "NON_PARTANT"),
            "position": p.get("ordreArrivee"),
            "gagnant": int(p.get("numPmu") in payes) if payes else np.nan,
            "rapport_gagnant": payes.get(p.get("numPmu"), np.nan),
            "sg_rembourse": int(rembourse),
        })
    return lignes


def collecter(debut: date, fin: date, sortie: str | Path, specialisation: str = "OFFLINE",
              cache: str | Path = "cache_pmu", disciplines: tuple[str, ...] | None = None,
              pause: float = 1.0) -> pd.DataFrame:
    """Collecte l'historique jour par jour et écrit le CSV canonique."""
    client = ClientPMU(cache, specialisation, pause)
    internet = specialisation.upper() == "INTERNET"
    toutes = []
    jour = debut
    while jour <= fin:
        prog = client.programme(jour)
        n = 0
        for reunion in ((prog or {}).get("programme") or {}).get("reunions", []):
            for course in reunion.get("courses", []):
                if disciplines and _discipline(course) not in disciplines:
                    continue
                if not course.get("rapportsDefinitifsDisponibles"):
                    continue
                r, c = reunion["numOfficiel"], course["numOrdre"]
                part = client.participants(jour, r, c)
                if not part:
                    continue
                rap = client.rapports(jour, r, c)
                toutes += lignes_course(jour, reunion, course, part, rap, internet, "historique")
                n += 1
        print(f"{jour.isoformat()} : {n} courses")
        jour += timedelta(days=1)
    df = pd.DataFrame(toutes)
    if not df.empty:
        # Courses dont le Simple Gagnant a été remboursé : pas de pari possible
        df = df[df["sg_rembourse"] == 0].drop(columns=["sg_rembourse"])
        df.to_csv(sortie, index=False)
    return df


def courses_du_jour(jour: date, specialisation: str = "OFFLINE", cache: str | Path = "cache_pmu",
                    pause: float = 1.0) -> pd.DataFrame:
    """Partants et cotes ACTUELLES des courses non encore courues du jour (pour pronostiquer)."""
    client = ClientPMU(cache, specialisation, pause)
    prog = client.programme(jour, utiliser_cache=False)
    lignes = []
    maintenant = pd.Timestamp.now(tz="UTC")
    for reunion in ((prog or {}).get("programme") or {}).get("reunions", []):
        for course in reunion.get("courses", []):
            depart = _ms(course.get("heureDepart"))
            if depart is None or depart <= maintenant:
                continue
            part = client.participants(jour, reunion["numOfficiel"], course["numOrdre"], utiliser_cache=False)
            if part:
                lignes += lignes_course(jour, reunion, course, part, None,
                                        specialisation.upper() == "INTERNET", "direct")
    df = pd.DataFrame(lignes)
    return df.drop(columns=["gagnant", "rapport_gagnant", "position", "sg_rembourse"], errors="ignore")


def releve_cotes(jour: date, fichier: str | Path, specialisation: str = "OFFLINE",
                 cache: str | Path = "cache_pmu") -> int:
    """Ajoute un relevé horodaté des cotes actuelles à un CSV (à planifier toutes les 5 min).
    Ces relevés constituent un historique HONNÊTE de cotes de décision (T-15, T-5…)."""
    df = courses_du_jour(jour, specialisation, cache)
    if df.empty:
        return 0
    df = df[["course_id", "num", "heure_depart", "cote_decision", "heure_cote_decision"]]
    nouveau = not Path(fichier).exists()
    df.to_csv(fichier, mode="a", header=nouveau, index=False, quoting=csv.QUOTE_MINIMAL)
    return len(df)


def appliquer_releves(df: pd.DataFrame, releves: str | Path, minutes_avant: int = 15) -> pd.DataFrame:
    """Remplace cote_decision par la cote relevée le plus près possible de
    `minutes_avant` minutes avant le départ, SANS jamais dépasser cet instant."""
    r = pd.read_csv(releves, parse_dates=["heure_depart", "heure_cote_decision"])
    r = r[r["heure_cote_decision"] <= r["heure_depart"] - pd.Timedelta(minutes=minutes_avant)]
    r = r.sort_values("heure_cote_decision").groupby(["course_id", "num"]).tail(1)
    df = df.drop(columns=["cote_decision"]).merge(
        r[["course_id", "num", "cote_decision"]], on=["course_id", "num"], how="left")
    return df
