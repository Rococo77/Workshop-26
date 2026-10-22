"""BFF de supervision — agrégation LECTURE SEULE pour le dashboard React.

N'exécute aucune action privilégiée : il interroge en GET l'état du détecteur,
du moteur de remédiation et de Prometheus, puis renvoie une vue consolidée.
Exposé via le WAF (observation jury), sans pouvoir déclencher de remédiation.
"""

from __future__ import annotations

import logging
import os
import re

import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bff")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
DETECTOR_URL = os.getenv("DETECTOR_URL", "http://ml-detector:9100")
REMEDIATION_URL = os.getenv("REMEDIATION_URL", "http://remediation-engine:9000")
WAF_URL = os.getenv("WAF_URL", "http://waf:8080")
# Assistant RAG (profil `ai`) : rédige le résumé direction d'un rapport.
RAG_URL = os.getenv("RAG_URL", "http://rag-assistant:8200")
REPORT_ID = re.compile(r"INC-[0-9]{8}-[0-9]{6}-[a-z_]+")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# La vue détaillée (IP bloquées, alertes, étapes des playbooks) est réservée à
# l'exploitation ; les clients n'ont accès qu'à /status (ok / perturbé).
SUPERVISION_ROLES = frozenset({"operator", "admin"})
CRITICAL = ("auth", "payment-api", "waf")

app = FastAPI(title="Resilience-Alpha Supervision BFF", version="1.0.0")
_bearer = HTTPBearer(auto_error=False)


def require_supervisor(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """JWT émis par le service auth (secret partagé), rôle operator ou admin."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    try:
        payload = jwt.decode(
            creds.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer="resilience-alpha-auth",
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from None
    if payload.get("role") not in SUPERVISION_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "supervision role required")
    return payload["sub"]


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


@app.get("/status")
def public_status() -> dict:
    """État du service vu par un client : uniquement ok / perturbé, sans détail
    interne (ni IP, ni alertes, ni mécanique de remédiation)."""
    with httpx.Client(timeout=5) as client:
        services = _services_up(client)
    return {"ok": all(services.get(name, True) for name in CRITICAL)}


@app.get("/overview")
def overview(_: str = Depends(require_supervisor)) -> dict:
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


@app.get("/reports")
def reports(_: str = Depends(require_supervisor)) -> list[dict]:
    """Rapports d'incident générés par le moteur (notification initiale DORA)."""
    with httpx.Client(timeout=5) as client:
        return _get_json(client, f"{REMEDIATION_URL}/reports", [])


def _report_id(report_id: str) -> str:
    if not REPORT_ID.fullmatch(report_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    return report_id


@app.get("/reports/{report_id}")
def report_detail(report_id: str, _: str = Depends(require_supervisor)) -> dict:
    try:
        r = httpx.get(f"{REMEDIATION_URL}/reports/{_report_id(report_id)}", timeout=5)
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "remediation unavailable") from exc
    if r.status_code != 200:
        raise HTTPException(r.status_code, "report not found")
    return r.json()


@app.post("/reports/{report_id}/summary")
def report_summary(report_id: str, _: str = Depends(require_supervisor)) -> dict:
    """Résumé direction rédigé par l'assistant LLM (profil `ai`). Le LLM lit
    le rapport en GET, il n'a aucun droit d'action. Sans Ollama : 503 propre."""
    try:
        r = httpx.post(
            f"{RAG_URL}/incident-summary", json={"report_id": _report_id(report_id)}, timeout=120
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "assistant unavailable") from exc
    if r.status_code != 200:
        raise HTTPException(r.status_code, "assistant unavailable")
    return r.json()
