"""Détecteur d'anomalies — boucle de détection + API d'état/metrics.

Chaîne : collecte signaux -> score IsolationForest -> si anomalie, qualification
(SIEM/Loki) -> envoi d'un incident au moteur de remédiation (avec cooldown).
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from . import config, sources
from .model import AnomalyModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("detector")

ANOMALY_SCORE = Gauge("anomaly_score", "Score d'anomalie normalisé [0..1]")
DETECTIONS = Counter("anomaly_detections_total", "Anomalies détectées", ["incident_type"])
INCIDENTS_SENT = Counter("incidents_sent_total", "Incidents transmis à la remédiation", ["result"])

_model = AnomalyModel()
_state: dict = {"last_features": {}, "last_score": 0.0, "last_decision": "normal", "last_ts": None}
_stop = threading.Event()
_last_sent = 0.0
# Incident en cours (None = situation normale) et issue de sa dernière remédiation.
_open_incident: str | None = None
_last_outcome: str | None = None
_streak = 0  # points anormaux consécutifs (confirmation avant incident)
_streak_since: str | None = None  # horodatage du premier point de la série


def _should_send(incident_type: str, in_cooldown: bool) -> bool:
    """Un incident = une remédiation. Tant que l'anomalie persiste, on ne relance
    que si la remédiation précédente a échoué, ou si la nature de l'incident
    change (ex. DoS puis API injoignable). Avant : relance à chaque cooldown."""
    if in_cooldown:
        return False
    return incident_type != _open_incident or _last_outcome == "failed"


def _service_down(client: httpx.Client) -> bool:
    try:
        r = client.get(
            f"{config.PROMETHEUS_URL}/api/v1/query",
            params={"query": 'up{job="payment-api"}'},
            timeout=5,
        )
        data = r.json()["data"]["result"]
        return bool(data) and float(data[0]["value"][1]) == 0.0
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return False


def _send_incident(client: httpx.Client, payload: dict) -> None:
    global _last_sent, _open_incident, _last_outcome
    _open_incident = payload["type"]
    _last_outcome = "failed"  # écrasé par l'issue réelle si le moteur répond
    try:
        r = client.post(
            f"{config.REMEDIATION_URL}/incident",
            json=payload,
            headers={"X-Remediation-Token": config.REMEDIATION_API_TOKEN},
            timeout=60,
        )
        r.raise_for_status()
        INCIDENTS_SENT.labels(result="ok").inc()
        _last_sent = time.monotonic()
        _last_outcome = r.json().get("outcome", "failed")
        log.info("incident transmis et traité: %s", _last_outcome)
    except httpx.HTTPError as exc:
        INCIDENTS_SENT.labels(result="error").inc()
        log.error("envoi incident échoué: %s", exc)


def _detection_loop() -> None:
    log.info("boucle de détection démarrée (intervalle=%ss)", config.DETECTION_INTERVAL_SECONDS)
    with httpx.Client(timeout=10) as client:
        while not _stop.is_set():
            try:
                _tick(client)
            except Exception as exc:  # une boucle robuste ne meurt pas sur une erreur
                log.exception("erreur dans la boucle de détection: %s", exc)
            _stop.wait(config.DETECTION_INTERVAL_SECONDS)


def _tick(client: httpx.Client) -> None:
    global _open_incident, _streak, _streak_since
    now = time.monotonic()
    in_cooldown = (now - _last_sent) < config.COOLDOWN_SECONDS

    # Cas 1 : service totalement injoignable -> incident direct (pas besoin du ML).
    if _service_down(client):
        ANOMALY_SCORE.set(1.0)
        _update_state({}, 1.0, "service_unavailable")
        DETECTIONS.labels(incident_type="service_unavailable").inc()
        if _should_send("service_unavailable", in_cooldown):
            _send_incident(
                client,
                {
                    "type": "service_unavailable",
                    "service": "payment-api",
                    "detail": "API de paiement injoignable (up==0)",
                    "anomaly_score": 1.0,
                    "detected_at": datetime.now(UTC).isoformat(),
                },
            )
        return

    # Cas 2 : compte leurre utilisé -> fuite de la base prouvée (pas besoin du ML).
    kinds = sources.honeytoken_kinds(client)
    if kinds:
        ANOMALY_SCORE.set(1.0)
        _update_state({}, 1.0, "honeytoken_triggered")
        DETECTIONS.labels(incident_type="honeytoken_triggered").inc()
        if _should_send("honeytoken_triggered", in_cooldown):
            _send_incident(
                client,
                {
                    "type": "honeytoken_triggered",
                    "service": "payment-api",
                    "detail": "compte leurre utilisé: " + ", ".join(kinds),
                    "anomaly_score": 1.0,
                    "detected_at": datetime.now(UTC).isoformat(),
                },
            )
        return

    # Cas 3 : détection ML sur le vecteur de features.
    features = sources.collect_features(client)
    is_anomaly, score, contributions = _model.score(features)
    ANOMALY_SCORE.set(score)

    if not is_anomaly:
        _streak = 0
        _update_state(features, score, "normal")
        _open_incident = None  # incident clos : le prochain sera traité
        return

    _streak += 1
    if _streak == 1:
        _streak_since = datetime.now(UTC).isoformat()
    if _streak < config.CONFIRM_POINTS:
        _update_state(features, score, "normal")
        log.info(
            "point anormal non confirmé (%d/%d) score=%.2f", _streak, config.CONFIRM_POINTS, score
        )
        return

    incident_type = sources.classify_attack(client)
    # L'IP attaquante est résolue par le moteur de remédiation (logs WAF).
    drivers = _model.top_drivers(contributions)
    _update_state(features, score, incident_type)
    DETECTIONS.labels(incident_type=incident_type).inc()
    log.warning("ANOMALIE: type=%s score=%.2f drivers=%s", incident_type, score, drivers)

    if _should_send(incident_type, in_cooldown):
        _send_incident(
            client,
            {
                "type": incident_type,
                "service": "payment-api",
                "source_ip": None,
                "anomaly_score": round(score, 3),
                "detected_at": _streak_since,
                "detail": "features anormales: " + ", ".join(drivers)
                if drivers
                else "profil anormal",
            },
        )


def _update_state(features: dict, score: float, decision: str) -> None:
    _state.update(
        {
            "last_features": features,
            "last_score": round(score, 3),
            "last_decision": decision,
            "last_ts": datetime.now(UTC).isoformat(),
        }
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    thread = threading.Thread(target=_detection_loop, daemon=True)
    thread.start()
    yield
    _stop.set()


app = FastAPI(title="Resilience-Alpha ML Detector", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/state")
def state() -> dict:
    return _state
