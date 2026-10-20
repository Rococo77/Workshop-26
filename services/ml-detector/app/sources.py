"""Collecte des signaux de détection depuis Prometheus (métriques temps réel).

Tous les signaux du chemin critique (détection ET qualification) viennent de
Prometheus : fiable, sans latence d'ingestion. Loki reste utilisé par ailleurs
pour la corrélation SIEM et le dashboard, mais n'est pas sur le chemin critique.
L'IP attaquante est résolue côté moteur de remédiation (lecture directe des logs
du conteneur WAF), au plus près de l'action de blocage.
"""

from __future__ import annotations

import logging

import httpx

from . import config

log = logging.getLogger("detector.sources")


def _prom_scalar(client: httpx.Client, query: str) -> float:
    """Exécute une requête instantanée Prometheus et renvoie une valeur scalaire."""
    try:
        r = client.get(f"{config.PROMETHEUS_URL}/api/v1/query", params={"query": query}, timeout=5)
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

    Fenêtre de 30 s (scrape 5 s -> 6 points) : avec 1 min, l'anomalie restait
    visible ~1 min après la fin d'une attaque. Les features sont des taux par
    seconde : la fenêtre change le lissage, pas l'échelle (profil nominal inchangé).
    """
    waf_total = _prom_scalar(client, "sum(rate(nginx_http_response_count_total[30s]))")
    api_rate = _prom_scalar(client, 'sum(rate(http_requests_total{service="payment-api"}[30s]))')
    req_rate = max(waf_total, api_rate)  # charge entrante réelle

    err_rate = _prom_scalar(
        client, 'sum(rate(http_requests_total{service="payment-api",status=~"5.."}[30s]))'
    )
    err_ratio = (err_rate / api_rate) if api_rate > 0 else 0.0
    p95 = _prom_scalar(
        client,
        "histogram_quantile(0.95, sum(rate("
        'http_request_duration_seconds_bucket{service="payment-api"}[30s])) by (le))',
    )
    auth_fail = _prom_scalar(client, "sum(rate(auth_login_failures_total[30s]))")
    waf_block = _prom_scalar(
        client, 'sum(rate(nginx_http_response_count_total{status=~"403|429"}[30s]))'
    )

    return {
        "req_rate": req_rate if req_rate == req_rate else 0.0,
        "err_ratio": err_ratio if err_ratio == err_ratio else 0.0,  # garde NaN
        "p95_latency": p95 if p95 == p95 else 0.0,
        "auth_fail_rate": auth_fail,
        "waf_block_rate": waf_block,
    }


def classify_attack(client: httpx.Client) -> str:
    """Qualifie le type d'attaque une fois l'anomalie détectée par le modèle.

    Distinction clé (disponibilité vs compromission) à partir des métriques WAF :
      - majorité de 403 (signatures bloquées par le CRS)  -> injection_attempt
      - sinon (volume / 429 de rate-limit dominants)       -> dos_flood
    Déterministe (Prometheus), sans dépendance à la latence d'ingestion de Loki.
    """
    q = 'sum(rate(nginx_http_response_count_total{status="%s"}[30s]))'
    block_403 = _prom_scalar(client, q % "403")
    block_429 = _prom_scalar(client, q % "429")
    total = block_403 + block_429
    if total > 0 and block_403 / total >= 0.4:
        return "injection_attempt"
    return "dos_flood"
