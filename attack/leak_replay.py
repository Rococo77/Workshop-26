#!/usr/bin/env python3
"""Scénario Red Team : réutilisation d'identifiants issus d'une fuite.

Hypothèse : l'attaquant a obtenu un extrait de la table des utilisateurs
(fuite simulée, aucune donnée réelle) et tente de s'en servir. L'extrait
contient des comptes leurres (honeytokens) que personne n'utilise : la
première tentative sur l'un d'eux prouve la fuite et déclenche l'alerte.

Effet attendu : connexions refusées (401), incident `honeytoken_triggered`
dans la supervision, IP source bloquée au WAF si elle est attribuable.

Usage :
    python3 leak_replay.py --target http://192.168.137.1:8080
"""

from __future__ import annotations

import argparse
import json
import urllib.request

# Extrait « volé » : un compte réel d'exploitation et deux comptes leurres.
LEAKED = [
    ("operator", "Operator2025!"),
    ("m.lefevre.dsi", "Lefevre2026"),
    ("tresorerie.groupe", "Tresorerie#1"),
]


def _login(target: str, username: str, password: str) -> int:
    req = urllib.request.Request(
        f"{target}/auth/login",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Réutilisation d'identifiants fuités")
    p.add_argument("--target", required=True)
    args = p.parse_args()

    print(f"[leak] cible={args.target}")
    for username, password in LEAKED:
        print(f"  {username:<20} -> {_login(args.target, username, password)}")
    print("[leak] attendu : 401 partout, incident « compte leurre utilisé » côté supervision.")


if __name__ == "__main__":
    main()
