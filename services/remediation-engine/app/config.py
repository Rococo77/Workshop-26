"""Configuration et garde-fous du moteur de remédiation."""
from __future__ import annotations

import os

REMEDIATION_API_TOKEN: str = os.getenv("REMEDIATION_API_TOKEN", "dev-token")
WAF_CONTAINER: str = os.getenv("WAF_CONTAINER", "ra-waf")
WAF_DYNAMIC_DIR: str = os.getenv("WAF_DYNAMIC_DIR", "/waf-dynamic")
CANARY_TARGET: str = os.getenv("CANARY_TARGET", "http://payment-api:8000")

# Garde-fou : seuls ces conteneurs peuvent être redémarrés par l'automate.
# La base de données et les composants d'état ne sont JAMAIS redémarrés
# automatiquement (risque de perte de cohérence > bénéfice). Allowlist stricte.
RESTARTABLE_CONTAINERS: frozenset[str] = frozenset(
    {"ra-payment-api", "ra-auth", "ra-frontend"}
)

# Playbooks connus. Un type d'incident inconnu est journalisé mais n'entraîne
# aucune action privilégiée (principe de moindre surprise / moindre privilège).
KNOWN_PLAYBOOKS: frozenset[str] = frozenset(
    {"dos_flood", "service_unavailable", "injection_attempt"}
)
