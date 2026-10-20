"""BFF de supervision — agrégation LECTURE SEULE pour le dashboard React.

N'exécute aucune action privilégiée : il interroge en GET l'état du détecteur,
du moteur de remédiation et de Prometheus, puis renvoie une vue consolidée.
Exposé via le WAF (observation jury), sans pouvoir déclencher de remédiation.
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bff")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
DETECTOR_URL = os.getenv("DETECTOR_URL", "http://ml-detector:9100")
REMEDIATION_URL = os.getenv("REMEDIATION_URL", "http://remediation-engine:9000")
WAF_URL = os.getenv("WAF_URL", "http://waf:8080")

app = FastAPI(title="Resilience-Alpha Supervision BFF", version="1.0.0")


def _get_json(client: httpx.Client, url: str, default):
    try:
        r = client.get(url, timeout=4)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("source indisponible %s: %s", url, exc)
        return default


def _services_up(client: httpx.Client) -> dict[str, bool]:
    data = _get_json(client, f"{PROMETHEUS_URL}/api/v1/query?query=up", {"data": {"result": []}})
    out: dict[str, bool] = {}
    for item in data.get("data", {}).get("result", []):
        svc = item["metric"].get("service") or item["metric"].get("job", "?")
        out[svc] = float(item["value"][1]) == 1.0
    # Le WAF n'expose pas de /metrics : sonde directe du point d'entrée réel.
    try:
        out["waf"] = client.get(f"{WAF_URL}/waf-health", timeout=3).status_code == 200
    except httpx.HTTPError:
        out["waf"] = False
    return out


def _alerts(client: httpx.Client) -> list[dict]:
    """Alertes Prometheus en cours (pending/firing), réduites à l'utile."""
    data = _get_json(client, f"{PROMETHEUS_URL}/api/v1/alerts", {"data": {"alerts": []}})
    return [
        {
            "name": a.get("labels", {}).get("alertname", "?"),
            "severity": a.get("labels", {}).get("severity", "info"),
            "summary": a.get("annotations", {}).get("summary", ""),
            "state": a.get("state", ""),
            "since": a.get("activeAt"),
        }
        for a in data.get("data", {}).get("alerts", [])
    ]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/overview")
def overview() -> dict:
    """Vue consolidée : services, détection, alertes, remédiation."""
    with httpx.Client(timeout=5) as client:
        services = _services_up(client)
        detector = _get_json(client, f"{DETECTOR_URL}/state", {})
        alerts = _alerts(client)
        remediation = _get_json(
            client, f"{REMEDIATION_URL}/status", {"events": [], "blocked_ips": []}
        )
    return {
        "services": services,
        "detector": detector,
        "alerts": alerts,
        "remediation": remediation,
    }
