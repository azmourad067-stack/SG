"""Logit conditionnel (« multinomial logit » par course).

C'est le modèle de référence des courses hippiques (Bolton & Chapman 1986,
Benter 1994) : chaque partant i d'une course reçoit un score u_i = x_i·β et
P(i gagne) = exp(u_i) / Σ_j exp(u_j) sur les partants de SA course.
Les probabilités d'une course somment donc à 1 par construction.

Implémentation numpy + L-BFGS (scipy), avec pénalité L2.
Les ex aequo (dead-heat) partagent le poids de la course.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize


def _bornes_groupes(groupes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Codes 0..G-1 et indices de début, en exigeant des groupes contigus."""
    change = np.r_[True, groupes[1:] != groupes[:-1]]
    debuts = np.flatnonzero(change)
    codes = np.cumsum(change) - 1
    if len(np.unique(groupes)) != len(debuts):
        raise ValueError("Les partants d'une même course doivent être contigus (trier par course).")
    return codes, debuts


def _log_softmax_groupes(u: np.ndarray, codes: np.ndarray, debuts: np.ndarray):
    m = np.maximum.reduceat(u, debuts)
    e = np.exp(u - m[codes])
    s = np.add.reduceat(e, debuts)
    lse = np.log(s) + m
    return u - lse[codes], e / s[codes]


class LogitConditionnel:
    def __init__(self, l2: float = 1.0):
        self.l2 = l2
        self.coef_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray, groupes: np.ndarray,
            offset: np.ndarray | None = None) -> "LogitConditionnel":
        """offset : terme fixe ajouté au score (ex. log q du marché). Avec la
        pénalité L2, les coefficients sont alors « tirés » vers le marché :
        sans preuve suffisante dans les données, le modèle redonne les cotes."""
        X = np.asarray(X, float)
        y = np.asarray(y, float)
        off = np.zeros(len(y)) if offset is None else np.asarray(offset, float)
        codes, debuts = _bornes_groupes(np.asarray(groupes))
        nb_g = np.add.reduceat(y, debuts)
        ok = nb_g[codes] > 0                    # courses sans gagnant connu : ignorées
        X, y, groupes, off = X[ok], y[ok], np.asarray(groupes)[ok], off[ok]
        codes, debuts = _bornes_groupes(groupes)
        nb_g = np.add.reduceat(y, debuts)
        w = y / nb_g[codes]                     # dead-heat : chaque gagnant pèse 1/k
        n_courses = len(debuts)

        def objectif(beta):
            u = off + X @ beta
            logp, p = _log_softmax_groupes(u, codes, debuts)
            nll = -np.sum(w * logp) / n_courses + 0.5 * self.l2 * beta @ beta / n_courses
            # gradient : Σ_courses (x_gagnant - Σ p_i x_i)
            grad = -(X.T @ (w - p)) / n_courses + self.l2 * beta / n_courses
            return nll, grad

        res = minimize(objectif, np.zeros(X.shape[1]), jac=True, method="L-BFGS-B",
                       options={"maxiter": 2000})
        self.coef_ = res.x
        self.convergence_ = bool(res.success)
        self.nll_ = float(res.fun)
        return self

    def scores(self, X: np.ndarray, offset: np.ndarray | None = None) -> np.ndarray:
        s = np.asarray(X, float) @ self.coef_
        return s if offset is None else s + np.asarray(offset, float)

    def predict_proba(self, X: np.ndarray, groupes: np.ndarray, offset: np.ndarray | None = None) -> np.ndarray:
        codes, debuts = _bornes_groupes(np.asarray(groupes))
        _, p = _log_softmax_groupes(self.scores(X, offset), codes, debuts)
        return p


def log_vraisemblance(p: np.ndarray, y: np.ndarray, groupes: np.ndarray) -> float:
    """Log-vraisemblance moyenne par course des gagnants (plus haut = meilleur)."""
    codes, debuts = _bornes_groupes(np.asarray(groupes))
    y = np.asarray(y, float)
    nb_g = np.add.reduceat(y, debuts)
    w = np.divide(y, nb_g[codes], out=np.zeros_like(y), where=nb_g[codes] > 0)
    n = int(np.sum(nb_g > 0))
    return float(np.sum(w * np.log(np.clip(p, 1e-12, 1))) / max(n, 1))
