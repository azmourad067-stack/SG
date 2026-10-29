"""Paramètres de l'outil.

Tous les seuils sont regroupés ici pour être modifiés en un seul endroit
(ou surchargés en ligne de commande / via un fichier JSON).

Rappel sur les cotes PMU : une cote (ou « rapport pour 1 € ») INCLUT la mise.
Une cote de 5,0 signifie qu'un pari de 1 € gagnant rapporte 5 € (4 € de gain net).
Le prélèvement de l'opérateur est déjà retiré de la masse avant le calcul du
rapport : il est donc intégré automatiquement quand on utilise les rapports
réellement payés. Le paramètre `commission_gains` sert pour un opérateur qui
prélèverait EN PLUS une commission sur les gains nets (bourse aux paris, etc.).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ConfigSelection:
    # --- Exclusion des favoris sous-payés -------------------------------
    # Aucun cheval dont la cote de décision est inférieure au seuil n'est
    # recommandé, quelle que soit sa probabilité.
    # cote_min_auto = True : le seuil est recalculé dans CHAQUE pli du backtest
    # (et à l'entraînement final) à partir des seules données d'entraînement,
    # par la règle de `backtest.justifier_cote_min`, borné à [cote_min_plancher ;
    # cote_min_plafond]. False : on utilise `cote_min` tel quel.
    # Sur l'historique PMU disponible, la règle donne 3,0 dans chaque pli (valeur par défaut).
    cote_min: float = 3.0
    cote_min_auto: bool = True
    cote_min_plancher: float = 2.0
    cote_min_plafond: float = 6.0
    # Les très gros outsiders ont des probabilités mal estimées (peu de
    # victoires pour calibrer) et une forte variance : plafond par défaut.
    # cote_max_auto = True : plafond appris pli par pli, symétrique du seuil bas
    # (on exclut les tranches de grosses cotes où le marché SURESTIME les chevaux).
    cote_max: float = 40.0
    cote_max_auto: bool = False
    cote_max_plancher: float = 15.0
    cote_max_plafond: float = 100.0
    # Marge de sécurité : on ne parie que si l'espérance de gain par euro
    # (EV = p * rapport_attendu - 1) dépasse cette marge.
    marge_ev: float = 0.10
    # Probabilité minimale estimée par le modèle (évite les paris « loterie »).
    proba_min: float = 0.03
    # Nombre maximal de chevaux joués dans une même course.
    max_paris_par_course: int = 1


@dataclass
class ConfigMise:
    # "fixe" : 1 unité par pari ; "kelly" : Kelly fractionné sur bankroll.
    methode: str = "fixe"
    mise_fixe: float = 1.0
    bankroll_initiale: float = 100.0
    fraction_kelly: float = 0.25          # quart de Kelly : réduit fortement la variance
    plafond_pari_pct: float = 0.02        # au plus 2 % de la bankroll sur un cheval
    plafond_course_pct: float = 0.04      # au plus 4 % de la bankroll sur une course
    mise_minimale: float = 0.0            # ex. 1.5 € minimum PMU si vous jouez en euros


@dataclass
class ConfigModele:
    # Pénalité L2 du logit conditionnel (régularisation, limite le surajustement).
    # Équivaut à un a priori gaussien de précision l2 sur chaque coefficient
    # (variables standardisées). En étape 2, la pénalité ramène vers le marché.
    # Valeurs fixées a priori, PAS optimisées sur la période de test.
    l2_fondamental: float = 10.0
    l2_combinaison: float = 20.0
    # Part la plus récente de la fenêtre d'entraînement réservée à l'étape 2
    # (combinaison modèle fondamental + marché), jamais vue par l'étape 1.
    part_calibration: float = 0.3
    # Lissage bayésien des taux (jockey, entraîneur…) : nb de courses « fictives »
    lissage: float = 30.0


@dataclass
class ConfigDonnees:
    # Disciplines conservées pour le modèle et les paris (None = toutes).
    # Ex. ["PLAT"] pour la version spécialisée plat. Les variables d'historique
    # (jockeys, chevaux) sont calculées AVANT ce filtre, sur toutes les courses.
    disciplines: list | None = None
    # "general" ou "plat" : le profil plat ajoute des variables propres au galop
    # (corde x distance, poids/décharge, handicap, oeillères 1re fois, forme en
    # plat, changement de jockey) et des corrections de marché par rang de cote.
    profil: str = "general"


@dataclass
class ConfigBacktest:
    jours_entrainement_min: int = 21      # fenêtre initiale avant le 1er test
    jours_par_pli: int = 7                # taille de chaque pli de test
    fenetre: str = "croissante"           # "croissante" ou "glissante"
    jours_fenetre_glissante: int = 365
    commission_gains: float = 0.0         # commission supplémentaire sur gains nets
    # Remise (cashback) éventuelle sur les mises, ex. 0.01 pour 1 % (fidélité
    # PMU+ en ligne : 0,5 à 2,5 % selon le statut). 0 par défaut : non garanti.
    remise_mises: float = 0.0
    n_simulations_hasard: int = 2000
    n_bootstrap: int = 5000
    graine: int = 42


@dataclass
class Config:
    selection: ConfigSelection = field(default_factory=ConfigSelection)
    mise: ConfigMise = field(default_factory=ConfigMise)
    modele: ConfigModele = field(default_factory=ConfigModele)
    backtest: ConfigBacktest = field(default_factory=ConfigBacktest)
    donnees: ConfigDonnees = field(default_factory=ConfigDonnees)

    @classmethod
    def plat(cls) -> "Config":
        """Profil spécialisé plat (voir config_plat.json)."""
        cfg = cls()
        cfg.donnees.disciplines = ["PLAT"]
        cfg.donnees.profil = "plat"
        cfg.selection.cote_max_auto = True
        return cfg

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: str | Path | None, base: "Config | None" = None) -> "Config":
        cfg = base or cls()
        if path is None:
            return cfg
        data = json.loads(Path(path).read_text())
        for section, values in data.items():
            obj = getattr(cfg, section)
            for k, v in values.items():
                if not hasattr(obj, k):
                    raise KeyError(f"Paramètre inconnu : {section}.{k}")
                setattr(obj, k, v)
        return cfg
