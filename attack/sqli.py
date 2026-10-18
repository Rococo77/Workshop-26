#!/usr/bin/env python3
"""Scénario Red Team — tentative d'injection SQL applicative.

Envoie des charges utiles d'injection sur l'endpoint d'authentification et les
paramètres de l'API. Attendu : rejet par le WAF/CRS (HTTP 403) -> pic de 403
dans les journaux -> qualification `injection_attempt` -> confinement (blocage
IP) SANS confusion avec une perte de disponibilité (le service répond toujours).

Démonstration que la plateforme résiste à l'injection : les requêtes
paramétrées côté API + le CRS côté WAF neutralisent la charge.

Usage :
    python3 sqli.py --target http://192.168.137.1:8080 --rounds 60
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from collections import Counter

PAYLOADS = [
    "' OR '1'='1",
    "admin'--",
    "'; DROP TABLE app_user;--",
    "' UNION SELECT username, password_hash FROM app_user--",
    "' OR 1=1 LIMIT 1;--",
    "\" OR \"\"=\"",
    "'; SELECT pg_sleep(5);--",
]


def _attempt(target: str, payload: str) -> str:
    data = json.dumps({"username": payload, "password": payload}).encode()
    req = urllib.request.Request(
        f"{target}/auth/login", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return str(resp.status)
    except urllib.error.HTTPError as exc:
        return str(exc.code)
    except Exception:
        return "error"


def main() -> None:
    p = argparse.ArgumentParser(description="Tentative d'injection SQL")
    p.add_argument("--target", required=True)
    p.add_argument("--rounds", type=int, default=60)
    args = p.parse_args()

    print(f"[sqli] cible={args.target} rounds={args.rounds}")
    stats = Counter()
    for i in range(args.rounds):
        payload = PAYLOADS[i % len(PAYLOADS)]
        stats[_attempt(args.target, payload)] += 1
        time.sleep(0.2)

    print("[sqli] terminé — réponses :")
    for code, n in sorted(stats.items()):
        tag = " (bloqué WAF)" if code == "403" else ""
        print(f"        {code}: {n}{tag}")
    print("[sqli] 401/403 attendus : aucune injection ne doit réussir.")


if __name__ == "__main__":
    main()
