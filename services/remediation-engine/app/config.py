"""Configuration et garde-fous du moteur de remédiation."""

from __future__ import annotations

import ipaddress
import os

REMEDIATION_API_TOKEN: str = os.getenv("REMEDIATION_API_TOKEN", "dev-token")
WAF_CONTAINER: str = os.getenv("WAF_CONTAINER", "ra-waf")
WAF_DYNAMIC_DIR: str = os.getenv("WAF_DYNAMIC_DIR", "/waf-dynamic")
CANARY_TARGET: str = os.getenv("CANARY_TARGET", "http://payment-api:8000")

# Garde-fou : plages JAMAIS bloquées. 172.16.0.0/12 couvre les réseaux bridge
# Docker : derrière un port publié (Docker Desktop, CI), tout client apparaît
# avec l'IP de la passerelle du bridge -> la bloquer couperait TOUT le monde.
# Le réseau pédagogique (192.168.137.0/24) reste bloquable.
PROTECTED_NETWORKS: tuple = tuple(
    ipaddress.ip_network(n.strip())
    for n in os.getenv("PROTECTED_NETWORKS", "127.0.0.0/8,::1/128,172.16.0.0/12").split(",")
    if n.strip()
)

# Garde-fou : seuls ces conteneurs peuvent être redémarrés par l'automate.
# La base de données et les composants d'état ne sont JAMAIS redémarrés
# automatiquement (risque de perte de cohérence > bénéfice). Allowlist stricte.
RESTARTABLE_CONTAINERS: frozenset[str] = frozenset({"ra-payment-api", "ra-auth", "ra-frontend"})

# Playbooks connus. Un type d'incident inconnu est journalisé mais n'entraîne
# aucune action privilégiée (principe de moindre surprise / moindre privilège).
KNOWN_PLAYBOOKS: frozenset[str] = frozenset(
    {"dos_flood", "service_unavailable", "injection_attempt", "honeytoken_triggered"}
)

# Services qui portent les pièges honeytokens (journal "HONEYTOKEN ... ip=").
HONEYTOKEN_CONTAINERS: tuple[str, ...] = ("ra-auth", "ra-payment-api")
