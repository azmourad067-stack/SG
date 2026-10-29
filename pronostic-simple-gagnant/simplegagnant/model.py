"""Modèle de probabilité en deux étapes (méthode de Benter, 1994).

Étape 1 – « fondamental » : logit conditionnel sur les variables du cheval,
          du jockey, de la forme… SANS les cotes. Il fournit un avis
          indépendant du marché, résumé par un score s_i.
Étape 2 – « combinaison » : logit conditionnel sur [s_i, log q_i, dérives de
          cote], estimé sur une période DIFFÉRENTE (plus récente) de celle de
          l'étape 1, afin que le poids donné au score ne soit pas gonflé par
          le surajustement de l'étape 1.

Pourquoi combiner avec le marché ? Les cotes résument l'information de tous
les parieurs ; un modèle fondamental seul est presque toujours moins précis
que le marché. La valeur se trouve dans l'écart entre les deux, et l'étape 2
apprend combien croire chacun. Si le score fondamental n'apporte rien, son
coefficient en étape 2 tend vers 0 et le modèle ne trouve (honnêtement) pas
de valeur.

Un modèle « marché seul » (étape 2 sans score) sert de référence : si le
modèle complet ne le bat pas hors échantillon, il n'y a pas d'avantage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .clogit import LogitConditionnel, log_vraisemblance
from .config import ConfigModele


@dataclass
class Preparateur:
    """Imputation (médiane), indicateurs de valeurs manquantes et standardisation,
    appris sur la fenêtre d'entraînement uniquement."""
    colonnes: list[str]
    medianes: dict = field(default_factory=dict)
    moyennes: np.ndarray | None = None
    ecarts: np.ndarray | None = None
    avec_indicateur: list[str] = field(default_factory=list)

    def fit(self, df: pd.DataFrame) -> "Preparateur":
        self.medianes = {c: float(df[c].median()) if df[c].notna().any() else 0.0 for c in self.colonnes}
        self.avec_indicateur = [c for c in self.colonnes if df[c].isna().mean() > 0.05]
        X = self._brut(df)
        self.moyennes = X.mean(axis=0)
        self.ecarts = X.std(axis=0)
        self.ecarts[self.ecarts < 1e-9] = 1.0
        return self

    def _brut(self, df: pd.DataFrame) -> np.ndarray:
        cols = [df[c].fillna(self.medianes[c]).to_numpy(float) for c in self.colonnes]
        cols += [df[c].isna().to_numpy(float) for c in self.avec_indicateur]
        return np.column_stack(cols) if cols else np.zeros((len(df), 0))

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        return (self._brut(df) - self.moyennes) / self.ecarts

    @property
    def noms(self) -> list[str]:
        return self.colonnes + [f"{c}__manquant" for c in self.avec_indicateur]


class ModeleDeuxEtapes:
    def __init__(self, cols_fond: list[str], cols_marche: list[str], cfg: ConfigModele | None = None,
                 utiliser_fondamental: bool = True):
        self.cols_fond = cols_fond
        self.cols_marche = cols_marche
        self.cfg = cfg or ConfigModele()
        self.utiliser_fondamental = utiliser_fondamental and len(cols_fond) > 0

    # ------------------------------------------------------------------ fit
    def fit(self, df: pd.DataFrame) -> "ModeleDeuxEtapes":
        df = df.sort_values(["date", "course_id"], kind="mergesort")
        jours = np.sort(df["date"].unique())
        coupure = jours[int(len(jours) * (1 - self.cfg.part_calibration))]
        A = df[df["date"] < coupure]
        B = df[df["date"] >= coupure]
        self.periode_ = (str(pd.Timestamp(jours[0]).date()), str(pd.Timestamp(coupure).date()),
                         str(pd.Timestamp(jours[-1]).date()))

        if self.utiliser_fondamental:
            self.prep1 = Preparateur(self.cols_fond).fit(A)
            self.etape1 = LogitConditionnel(self.cfg.l2_fondamental).fit(
                self.prep1.transform(A), A["gagnant"].to_numpy(), A["course_id"].to_numpy())
        self.prep2 = Preparateur([c for c in self.cols_marche if c != "log_q"]).fit(B)
        if self.utiliser_fondamental:
            s = self._score_fond(B)
            self.score_moy_, self.score_ect_ = float(s.mean()), float(s.std() or 1.0)
        X2 = self._X2(B)
        # Le marché (log q) sert de point de départ (offset) : les coefficients
        # mesurent l'ÉCART au marché et la pénalité L2 les ramène vers 0, donc
        # vers les cotes, tant que les données ne prouvent pas le contraire.
        self.etape2 = LogitConditionnel(self.cfg.l2_combinaison).fit(
            X2, B["gagnant"].to_numpy(), B["course_id"].to_numpy(), offset=self._offset(B))
        return self

    def _score_fond(self, df: pd.DataFrame) -> np.ndarray:
        return self.etape1.scores(self.prep1.transform(df))

    def _offset(self, df: pd.DataFrame) -> np.ndarray | None:
        return df["log_q"].to_numpy(float) if "log_q" in self.cols_marche else None

    def _X2(self, df: pd.DataFrame) -> np.ndarray:
        # Colonnes : score fondamental standardisé, log q (son coefficient est
        # l'écart à 1 : > 0 => les favoris sont sous-estimés par le marché),
        # dérives de cote standardisées.
        parts = []
        if self.utiliser_fondamental:
            parts.append((self._score_fond(df) - self.score_moy_) / self.score_ect_)
        if "log_q" in self.cols_marche:
            parts.append(df["log_q"].to_numpy(float))
        if self.prep2.colonnes:
            parts.append(self.prep2.transform(df))
        return np.column_stack(parts)

    # -------------------------------------------------------------- predict
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Retourne p_modele (et p_fond si étape 1) pour des lignes triées par course."""
        out = pd.DataFrame(index=df.index)
        g = df["course_id"].to_numpy()
        out["p_modele"] = self.etape2.predict_proba(self._X2(df), g, offset=self._offset(df))
        if self.utiliser_fondamental:
            out["p_fond"] = self.etape1.predict_proba(self.prep1.transform(df), g)
        return out

    def coefficients(self) -> dict:
        d = {}
        noms2 = []
        if self.utiliser_fondamental:
            d["etape1"] = dict(zip(self.prep1.noms, np.round(self.etape1.coef_, 4)))
            noms2.append("score_fondamental")
        if "log_q" in self.cols_marche:
            noms2.append("log_q (écart à 1)")
        noms2 += [f"{n} (std)" for n in self.prep2.noms]
        d["etape2"] = dict(zip(noms2, np.round(self.etape2.coef_, 4)))
        return d


def evaluer(df: pd.DataFrame, p: np.ndarray) -> float:
    return log_vraisemblance(p, df["gagnant"].to_numpy(), df["course_id"].to_numpy())
