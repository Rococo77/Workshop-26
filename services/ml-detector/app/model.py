"""Modèle de détection d'anomalies — IsolationForest sur signaux d'exploitation.

Choix : IsolationForest (non supervisé) car on dispose d'un trafic nominal
abondant mais de très peu d'exemples d'attaque étiquetés — exactement le cas
d'usage de la détection d'outliers. Le modèle est entraîné sur un profil de
trafic nominal (généré de façon déterministe, reproductible) représentant le
comportement ordinaire de la plateforme.

Explicabilité : à chaque alerte, on calcule l'écart normalisé (z-score) de
chaque feature par rapport au profil nominal pour dire POURQUOI c'est anormal.
"""
from __future__ import annotations

import logging

import numpy as np
from sklearn.ensemble import IsolationForest

from . import config

log = logging.getLogger("detector.model")
_RNG = np.random.default_rng(seed=42)  # reproductibilité


def _nominal_profile(n: int = 3000) -> np.ndarray:
    """Trafic nominal synthétique. Ordre = config.FEATURE_NAMES.

    Valeurs calées sur un démonstrateur au repos/charge légère :
      req_rate ~ 2-8 req/s, err_ratio ~ 0, p95 ~ 20-120 ms,
      auth_fail ~ 0-0.3/s, waf_block ~ 0.
    """
    req_rate = _RNG.normal(5.0, 1.5, n).clip(0.2, None)
    err_ratio = np.abs(_RNG.normal(0.0, 0.01, n)).clip(0, 1)
    p95 = _RNG.normal(0.06, 0.02, n).clip(0.005, None)
    auth_fail = np.abs(_RNG.normal(0.05, 0.08, n)).clip(0, None)
    waf_block = np.abs(_RNG.normal(0.0, 0.05, n)).clip(0, None)
    return np.column_stack([req_rate, err_ratio, p95, auth_fail, waf_block])


class AnomalyModel:
    def __init__(self) -> None:
        self._baseline = _nominal_profile()
        self._mean = self._baseline.mean(axis=0)
        self._std = self._baseline.std(axis=0) + 1e-9
        self._clf = IsolationForest(
            n_estimators=200,
            contamination=config.ANOMALY_CONTAMINATION,
            random_state=42,
        )
        self._clf.fit(self._standardize(self._baseline))
        log.info("IsolationForest entraîné sur %d points nominaux", len(self._baseline))

    def _standardize(self, x: np.ndarray) -> np.ndarray:
        return (x - self._mean) / self._std

    def score(self, features: dict[str, float]) -> tuple[bool, float, dict[str, float]]:
        """Retourne (is_anomaly, score_normalisé[0..1], contributions z-score).

        score_normalisé : plus il est haut, plus c'est anormal (0.5 = frontière).
        """
        vec = np.array([[features[name] for name in config.FEATURE_NAMES]], dtype=float)
        std_vec = self._standardize(vec)

        is_anomaly = bool(self._clf.predict(std_vec)[0] == -1)
        # decision_function > 0 = normal ; < 0 = anomalie. On mappe vers [0,1].
        raw = float(self._clf.decision_function(std_vec)[0])
        norm = float(np.clip(0.5 - raw, 0.0, 1.0))

        contributions = {
            name: round(float(std_vec[0, i]), 2)
            for i, name in enumerate(config.FEATURE_NAMES)
        }
        return is_anomaly, norm, contributions

    def top_drivers(self, contributions: dict[str, float], k: int = 2) -> list[str]:
        """Features qui expliquent le plus l'anomalie (plus grand écart positif)."""
        ordered = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)
        return [f"{name} (z={z})" for name, z in ordered[:k] if z > 1.0]
