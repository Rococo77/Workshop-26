"""API du moteur de remédiation.

Reçoit les incidents du détecteur ML, exécute le playbook adapté, vérifie la
reprise par transaction canari, expose l'état pour le dashboard + Prometheus.
"""

from __future__ import annotations

import logging
from collections import OrderedDict, deque
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from pydantic import BaseModel, Field

from . import config, playbooks, report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("remediation")

app = FastAPI(title="Resilience-Alpha Remediation Engine", version="1.0.0")

ACTIONS = Counter("remediation_actions_total", "Remédiations exécutées", ["playbook", "result"])
LAST_RECOVERY = Gauge("remediation_last_recovery_timestamp", "Horodatage dernière reprise prouvée")
ACTIVE_BLOCKS = Gauge("remediation_blocked_ips", "Nombre d'IP bloquées au WAF")

# Historique court en mémoire pour le dashboard (pas de persistance requise).
_events: deque[dict] = deque(maxlen=50)
# ponytail: rapports en mémoire (perdus au redémarrage du moteur), volume
# persistant ou envoi à un outil de ticketing si l'archivage DORA est exigé.
_reports: OrderedDict[str, dict] = OrderedDict()
# Incident qui a activé le mode dégradé (rapport à compléter à la clôture).
_degraded_by: str | None = None


class Incident(BaseModel):
    type: str = Field(description="dos_flood | service_unavailable | injection_attempt")
    service: str = Field(default="payment-api")
    source_ip: str | None = None
    detail: str | None = None
    anomaly_score: float | None = None
    # Premier point anormal vu par le détecteur (début de la chronologie).
    detected_at: str | None = None


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
    global _degraded_by
    _auth(x_remediation_token)
    log.info(
        "incident reçu: %s (service=%s, ip=%s, score=%s)",
        incident.type,
        incident.service,
        incident.source_ip,
        incident.anomaly_score,
    )
    received = datetime.now(UTC)

    result = playbooks.dispatch(incident.type, incident.service, incident.source_ip)

    outcome = "recovered" if result.recovered else ("contained" if result.contained else "failed")
    ACTIONS.labels(playbook=result.incident_type, result=outcome).inc()
    if result.recovered:
        LAST_RECOVERY.set_to_current_time()

    event = {
        "ts": datetime.now(UTC).isoformat(),
        "ts_received": received.isoformat(),
        "detected_at": incident.detected_at,
        "report_id": f"INC-{received:%Y%m%d-%H%M%S}-{result.incident_type}",
        "type": result.incident_type,
        "service": incident.service,
        "source_ip": incident.source_ip,
        "anomaly_score": incident.anomaly_score,
        "detail": incident.detail,  # causes de l'anomalie (features du modèle)
        "steps": result.steps,
        "timeline": result.timeline,
        "recovered": result.recovered,
        "contained": result.contained,
        "outcome": outcome,
    }
    if result.degraded:
        _degraded_by = event["report_id"]
    _events.appendleft(event)
    _reports[event["report_id"]] = report.build(event)
    while len(_reports) > 20:
        _reports.popitem(last=False)
    log.info("rapport d'incident généré: %s", event["report_id"])
    return event


@app.post("/incident/close")
def close_incident(x_remediation_token: str | None = Header(default=None)) -> dict:
    """Le détecteur revoit un trafic normal : on lève le mode dégradé puis on
    rejoue la file (dans cet ordre : un virement validé entre les deux est
    réglé directement, aucun n'est oublié)."""
    global _degraded_by
    from . import actions

    _auth(x_remediation_token)
    actions.set_degraded(False)
    done = actions.replay_queue()
    if done is None:
        # API injoignable : la file reste en base, rejouée à son démarrage.
        return {"replayed": None}
    if _degraded_by or done["settled"] or done["rejected"]:
        msg = (
            f"clôture : mode dégradé levé, {done['settled']} virement(s) en file réglé(s), "
            f"{done['rejected']} rejeté(s)"
        )
        log.info(msg)
        _append_step(_degraded_by, msg)
    _degraded_by = None
    return {"replayed": done}


def _append_step(report_id: str | None, msg: str) -> None:
    entry = {"ts": datetime.now(UTC).isoformat(), "msg": msg}
    for ev in _events:
        if ev["report_id"] == report_id:
            ev["steps"].append(msg)
    if report_id in _reports:
        _reports[report_id]["actions"].append(msg)
        _reports[report_id]["chronology"].append(entry)


@app.get("/reports")
def list_reports() -> list[dict]:
    """Rapports du plus récent au plus ancien (lecture seule, sans jeton,
    comme /status : réseaux internes uniquement)."""
    return [
        {k: r[k] for k in ("id", "type", "nature", "detected_at", "recovery_seconds", "outcome")}
        for r in reversed(_reports.values())
    ]


@app.get("/reports/{report_id}")
def get_report(report_id: str) -> dict:
    r = _reports.get(report_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    return {**r, "markdown": report.to_markdown(r)}
