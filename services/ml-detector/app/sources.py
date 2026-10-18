"""Collecte des signaux : métriques Prometheus + journaux WAF via Loki.

Le détecteur joue aussi le rôle de corrélation SIEM légère : il relit les
journaux du WAF pour qualifier l'attaque (403 = injection bloquée, 429 = flood)
et identifier l'IP source dominante à transmettre au moteur de remédiation.
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter

import httpx

from . import config

log = logging.getLogger("detector.sources")

# Début de ligne access nginx : "<ip> - - [date] \"METHOD path\" <status> ..."
_ACCESS_RE = re.compile(r'^(\d{1,3}(?:\.\d{1,3}){3})\s.*"\s*\S+ [^"]*"\s+(\d{3})')


def _prom_scalar(client: httpx.Client, query: str) -> float:
    """Exécute une requête instantanée Prometheus et renvoie une valeur scalaire."""
    try:
        r = client.get(f"{config.PROMETHEUS_URL}/api/v1/query",
                        params={"query": query}, timeout=5)
        r.raise_for_status()
        result = r.json()["data"]["result"]
        if not result:
            return 0.0
        return float(result[0]["value"][1])
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
        log.warning("requête Prometheus échouée (%s): %s", query[:40], exc)
        return 0.0


def collect_features(client: httpx.Client) -> dict[str, float]:
    """Vecteur de features aligné sur config.FEATURE_NAMES.

    req_rate et waf_block_rate proviennent des métriques du WAF (exporter de logs
    nginx -> Prometheus) : signal fiable et temps réel, non dampé par le
    rate-limiting (le WAF voit TOUT le trafic entrant, y compris ce qu'il rejette).
    Repli sur les métriques de l'API métier si l'exporter n'est pas encore prêt.
    """
    waf_total = _prom_scalar(client, "sum(rate(nginx_http_response_count_total[1m]))")
    api_rate = _prom_scalar(
        client, 'sum(rate(http_requests_total{service="payment-api"}[1m]))')
    req_rate = max(waf_total, api_rate)  # charge entrante réelle

    err_rate = _prom_scalar(
        client, 'sum(rate(http_requests_total{service="payment-api",status=~"5.."}[1m]))')
    err_ratio = (err_rate / api_rate) if api_rate > 0 else 0.0
    p95 = _prom_scalar(
        client,
        'histogram_quantile(0.95, sum(rate('
        'http_request_duration_seconds_bucket{service="payment-api"}[1m])) by (le))')
    auth_fail = _prom_scalar(client, "sum(rate(auth_login_failures_total[1m]))")
    waf_block = _prom_scalar(
        client, 'sum(rate(nginx_http_response_count_total{status=~"403|429"}[1m]))')

    return {
        "req_rate": req_rate if req_rate == req_rate else 0.0,
        "err_ratio": err_ratio if err_ratio == err_ratio else 0.0,  # garde NaN
        "p95_latency": p95 if p95 == p95 else 0.0,
        "auth_fail_rate": auth_fail,
        "waf_block_rate": waf_block,
    }


def _query_waf_logs(client: httpx.Client, window_s: int = 60) -> list[str]:
    now = time.time_ns()
    start = now - window_s * 1_000_000_000
    try:
        r = client.get(
            f"{config.LOKI_URL}/loki/api/v1/query_range",
            params={"query": '{service="waf"}', "start": str(start),
                    "end": str(now), "limit": "5000", "direction": "backward"},
            timeout=5,
        )
        r.raise_for_status()
        lines: list[str] = []
        for stream in r.json()["data"]["result"]:
            lines += [entry[1] for entry in stream["values"]]
        return lines
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("requête Loki échouée: %s", exc)
        return []


def classify_attack(client: httpx.Client, window_s: int = 60) -> tuple[str, str | None]:
    """Qualifie l'attaque et extrait l'IP source dominante depuis les logs WAF.

    Retourne (incident_type, source_ip). Heuristique de QUALIFICATION une fois
    l'anomalie détectée par le modèle — ce n'est pas le détecteur lui-même.
    """
    lines = _query_waf_logs(client, window_s)
    status_by_ip: dict[str, Counter] = {}
    for line in lines:
        m = _ACCESS_RE.match(line)
        if not m:
            continue
        ip, st = m.group(1), m.group(2)
        status_by_ip.setdefault(ip, Counter())[st] += 1

    if not status_by_ip:
        return "dos_flood", None  # pas de log exploitable : défaut flood

    # IP la plus bruyante toutes requêtes confondues.
    top_ip = max(status_by_ip, key=lambda ip: sum(status_by_ip[ip].values()))
    counts = status_by_ip[top_ip]
    forbidden = counts.get("403", 0)
    total = sum(counts.values())

    # Majorité de 403 => signatures d'injection bloquées par le CRS.
    if total > 0 and forbidden / total >= 0.4:
        return "injection_attempt", top_ip
    return "dos_flood", top_ip
