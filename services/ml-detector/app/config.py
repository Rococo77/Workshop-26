"""Configuration du détecteur d'anomalies."""

from __future__ import annotations

import os

PROMETHEUS_URL: str = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
LOKI_URL: str = os.getenv("LOKI_URL", "http://loki:3100")
REMEDIATION_URL: str = os.getenv("REMEDIATION_URL", "http://remediation-engine:9000")
REMEDIATION_API_TOKEN: str = os.getenv("REMEDIATION_API_TOKEN", "dev-token")

DETECTION_INTERVAL_SECONDS: float = float(os.getenv("DETECTION_INTERVAL_SECONDS", "10"))
ANOMALY_CONTAMINATION: float = float(os.getenv("ANOMALY_CONTAMINATION", "0.05"))

# Cooldown après envoi d'un incident : évite de noyer le moteur de remédiation
# pendant qu'il agit et vérifie la reprise.
COOLDOWN_SECONDS: float = float(os.getenv("COOLDOWN_SECONDS", "45"))

# Points anormaux consécutifs exigés avant d'ouvrir un incident : un faux positif
# isolé (~4 % des points nominaux en évaluation) ne déclenche aucune action.
CONFIRM_POINTS: int = int(os.getenv("CONFIRM_POINTS", "2"))

# Ordre des features (doit rester cohérent entre entraînement et inférence).
FEATURE_NAMES: tuple[str, ...] = (
    "req_rate",  # requêtes/s sur l'API métier
    "err_ratio",  # part de réponses 5xx
    "p95_latency",  # latence p95 (s)
    "auth_fail_rate",  # échecs d'auth/s
    "waf_block_rate",  # requêtes rejetées par le WAF/s (403+429)
)
