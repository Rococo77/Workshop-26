"""API du moteur de remédiation.

Reçoit les incidents du détecteur ML, exécute le playbook adapté, vérifie la
reprise par transaction canari, expose l'état pour le dashboard + Prometheus.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from pydantic import BaseModel, Field

from . import config, playbooks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("remediation")

app = FastAPI(title="Resilience-Alpha Remediation Engine", version="1.0.0")

ACTIONS = Counter("remediation_actions_total", "Remédiations exécutées", ["playbook", "result"])
LAST_RECOVERY = Gauge("remediation_last_recovery_timestamp", "Horodatage dernière reprise prouvée")
ACTIVE_BLOCKS = Gauge("remediation_blocked_ips", "Nombre d'IP bloquées au WAF")

# Historique court en mémoire pour le dashboard (pas de persistance requise).
_events: deque[dict] = deque(maxlen=50)


class Incident(BaseModel):
    type: str = Field(description="dos_flood | service_unavailable | injection_attempt")
    service: str = Field(default="payment-api")
    source_ip: str | None = None
    detail: str | None = None
    anomaly_score: float | None = None


def _auth(token: str | None) -> None:
    # Jeton interne (allowlist d'appelants) — le détecteur est le seul client.
    if token != config.REMEDIATION_API_TOKEN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid remediation token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    from . import actions

    ACTIVE_BLOCKS.set(len(actions.blocked_ips()))
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/status")
def get_status() -> dict:
    from . import actions

    return {
        "blocked_ips": actions.blocked_ips(),
        "events": list(_events),
        "known_playbooks": sorted(config.KNOWN_PLAYBOOKS),
    }


@app.post("/incident")
def receive_incident(
    incident: Incident, x_remediation_token: str | None = Header(default=None)
) -> dict:
    _auth(x_remediation_token)
    log.info(
        "incident reçu: %s (service=%s, ip=%s, score=%s)",
        incident.type,
        incident.service,
        incident.source_ip,
        incident.anomaly_score,
    )

    result = playbooks.dispatch(incident.type, incident.service, incident.source_ip)

    outcome = "recovered" if result.recovered else ("contained" if result.contained else "failed")
    ACTIONS.labels(playbook=result.incident_type, result=outcome).inc()
    if result.recovered:
        LAST_RECOVERY.set_to_current_time()

    event = {
        "ts": datetime.now(UTC).isoformat(),
        "type": result.incident_type,
        "service": incident.service,
        "source_ip": incident.source_ip,
        "anomaly_score": incident.anomaly_score,
        "detail": incident.detail,  # causes de l'anomalie (features du modèle)
        "steps": result.steps,
        "recovered": result.recovered,
        "contained": result.contained,
        "outcome": outcome,
    }
    _events.appendleft(event)
    return event
