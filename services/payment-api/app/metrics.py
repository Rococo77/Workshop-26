"""Instrumentation Prometheus — signaux consommés par la détection ML.

Les features clés de détection sont dérivées de :
  - http_requests_total{status}         -> taux de requêtes, ratio 5xx/4xx
  - http_request_duration_seconds       -> latence p95
  - payment_tx_total{result}            -> santé métier (échecs de transaction)
"""
from __future__ import annotations

import time

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

HTTP_REQUESTS = Counter(
    "http_requests_total", "Requêtes HTTP", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "Latence HTTP", ["method", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
PAYMENT_TX = Counter("payment_tx_total", "Transactions métier", ["result"])


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # On regroupe par route (template), pas par URL brute, pour éviter
        # l'explosion de cardinalité sous attaque (chemins aléatoires).
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            HTTP_LATENCY.labels(request.method, path).observe(elapsed)
            HTTP_REQUESTS.labels(request.method, path, str(status_code)).inc()
