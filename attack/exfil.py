#!/usr/bin/env python3
"""Scénario Red Team — tentative d'exfiltration / accès non autorisé.

Essaie :
  1. d'atteindre l'endpoint interne /api/internal/canary (doit renvoyer 404 : non exposé),
  2. de lister massivement les transactions sans jeton (doit renvoyer 401/403),
  3. de contourner la pagination (limit géant) — bornée côté API.

Objectif : prouver que l'exposition est maîtrisée (sujet §4) et que la tentative
laisse une trace exploitable pour l'investigation. À distinguer d'un déni de
service : ici la réponse défensive est le CONFINEMENT, pas la restauration.

Usage :
    python3 exfil.py --target http://192.168.137.1:8080
"""
from __future__ import annotations

import argparse
import urllib.request


def _probe(method: str, url: str, headers: dict | None = None) -> str:
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return f"{resp.status} ({len(resp.read())} octets)"
    except urllib.error.HTTPError as exc:
        return f"{exc.code} (refusé)"
    except Exception as exc:
        return f"error ({exc})"


def main() -> None:
    p = argparse.ArgumentParser(description="Tentative d'exfiltration")
    p.add_argument("--target", required=True)
    args = p.parse_args()
    t = args.target

    print(f"[exfil] cible={t}")
    print("  endpoint interne canari :", _probe("POST", f"{t}/api/internal/canary"))
    print("  liste tx sans jeton     :", _probe("GET", f"{t}/api/transactions"))
    print("  dump pagination géante  :", _probe("GET", f"{t}/api/transactions?limit=100000"))
    print("  accès direct base (/api/../): ", _probe("GET", f"{t}/api/accounts/me"))
    print("[exfil] attendu : 404 (interne masqué), 401/403 (auth requise), limit borné.")


if __name__ == "__main__":
    main()
