#!/usr/bin/env python3
"""Entraînement & évaluation du détecteur d'anomalies (dossier technique).

Reproduit, hors ligne, le modèle utilisé par le service `ml-detector` afin de
documenter : les données, la préparation, le modèle retenu, les résultats et
les limites (exigence sujet §3.3).

Sortie :
  - ml/models/anomaly_isoforest.joblib  (modèle + normalisation)
  - métriques d'évaluation sur un jeu d'attaques synthétiques étiquetées.

Usage : python3 ml/train.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from joblib import dump
from sklearn.ensemble import IsolationForest

RNG = np.random.default_rng(42)
FEATURES = ("req_rate", "err_ratio", "p95_latency", "auth_fail_rate", "waf_block_rate")


def nominal(n: int = 3000) -> np.ndarray:
    """Trafic ordinaire : charge légère, peu d'erreurs, pas de blocage WAF."""
    return np.column_stack([
        RNG.normal(5.0, 1.5, n).clip(0.2, None),      # req/s
        np.abs(RNG.normal(0.0, 0.01, n)).clip(0, 1),  # ratio 5xx
        RNG.normal(0.06, 0.02, n).clip(0.005, None),  # p95 (s)
        np.abs(RNG.normal(0.05, 0.08, n)).clip(0, None),
        np.abs(RNG.normal(0.0, 0.05, n)).clip(0, None),
    ])


def attacks(n: int = 300) -> np.ndarray:
    """Jeu d'attaques synthétiques (pour ÉVALUATION, pas pour l'entraînement) :
    flood (req/s et latence hautes, 429), injection (403 WAF), brute force (auth)."""
    flood = np.column_stack([
        RNG.normal(80, 20, n).clip(20, None),
        np.abs(RNG.normal(0.3, 0.1, n)).clip(0, 1),
        RNG.normal(2.0, 0.6, n).clip(0.5, None),
        np.abs(RNG.normal(0.1, 0.1, n)),
        RNG.normal(15, 5, n).clip(0, None),
    ])
    injection = np.column_stack([
        RNG.normal(12, 4, n).clip(1, None),
        np.abs(RNG.normal(0.02, 0.02, n)).clip(0, 1),
        RNG.normal(0.1, 0.03, n).clip(0.01, None),
        np.abs(RNG.normal(0.2, 0.2, n)),
        RNG.normal(10, 4, n).clip(0, None),
    ])
    return np.vstack([flood, injection])


def main() -> None:
    X_train = nominal()
    mean, std = X_train.mean(axis=0), X_train.std(axis=0) + 1e-9
    Xtr = (X_train - mean) / std

    clf = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
    clf.fit(Xtr)

    # Évaluation : rappel sur attaques, taux de faux positifs sur trafic nominal.
    X_nom = (nominal(1000) - mean) / std
    X_atk = (attacks(300) - mean) / std
    fp = np.mean(clf.predict(X_nom) == -1)
    recall = np.mean(clf.predict(X_atk) == -1)

    print("=== Détecteur d'anomalies — IsolationForest ===")
    print(f"features           : {', '.join(FEATURES)}")
    print(f"points nominaux    : {len(X_train)} (entraînement non supervisé)")
    print(f"rappel attaques    : {recall:.1%}  (part d'attaques correctement signalées)")
    print(f"faux positifs      : {fp:.1%}      (trafic nominal signalé à tort)")
    print("\nLimites : modèle calé sur un profil de charge légère (démonstrateur).")
    print("En production : réentraînement sur trafic réel, fenêtres multi-échelles,")
    print("features additionnelles (entropie des chemins, géo-IP, saisonnalité).")

    out = Path(__file__).parent / "models"
    out.mkdir(exist_ok=True)
    dump({"model": clf, "mean": mean, "std": std, "features": FEATURES},
         out / "anomaly_isoforest.joblib")
    print(f"\nModèle sauvegardé -> {out / 'anomaly_isoforest.joblib'}")


if __name__ == "__main__":
    main()
