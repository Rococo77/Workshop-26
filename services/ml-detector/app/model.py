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


def _nominal_profile(n: int = 4000) -> np.ndarray:
    """Trafic nominal synthétique. Ordre = config.FEATURE_NAMES.

    Couvre toute la plage de fonctionnement ordinaire, du REPOS (idle, ~0.1 req/s)
    à la charge normale (~15 req/s), avec peu d'erreurs, faible latence et aucun
    blocage WAF. Ainsi le modèle ne flague ni l'idle ni la charge nominale ; seuls
    les régimes extrêmes (flood, erreurs, blocages massifs) deviennent des outliers.
    """
    # En régime ordinaire, err/auth_fail/waf_block valent le plus souvent 0
    # (cas de l'idle réel). On modélise cette masse à zéro par un mélange,
    # sinon le vecteur "tout à zéro" devient un outlier artificiel.
    req_rate = _RNG.uniform(0.1, 15.0, n)            # repos -> charge normale
    p95 = _RNG.uniform(0.01, 0.20, n)                # 10-200 ms
    err_ratio = np.where(_RNG.random(n) < 0.90, 0.0,
                         np.abs(_RNG.normal(0.01, 0.02, n))).clip(0, 1)
    auth_fail = np.where(_RNG.random(n) < 0.70, 0.0,
                         np.abs(_RNG.normal(0.10, 0.20, n)))
    waf_block = np.where(_RNG.random(n) < 0.85, 0.0,
                         np.abs(_RNG.normal(0.10, 0.30, n)))
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
