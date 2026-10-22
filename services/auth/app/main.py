"""Service d'authentification — émission de JWT, métriques Prometheus.

Expose volontairement `auth_login_failures_total` : signal clé pour la
détection d'anomalie (brute force / credential stuffing).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field

from . import db
from .security import create_access_token, verify_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("auth")

app = FastAPI(title="Resilience-Alpha Auth", version="1.0.0")

LOGIN_ATTEMPTS = Counter("auth_login_attempts_total", "Tentatives de connexion", ["result"])
LOGIN_FAILURES = Counter("auth_login_failures_total", "Échecs de connexion", ["reason"])
# Série créée à 0 au démarrage : sans elle, increase() ignore le premier déclenchement.
HONEYTOKEN = Counter("honeytoken_triggers_total", "Comptes leurres utilisés", ["kind"])
HONEYTOKEN.labels(kind="login")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/login")
def login(req: LoginRequest, request: Request) -> TokenResponse:
    """Réservé à operator/admin (pas de compte bancaire, pas de visage
    enrôlé) : mot de passe seul, utilisé par l'écran de supervision. Le
    parcours client (identifiant -> visage -> mot de passe, §10.1) vit
    entièrement dans payment-api (POST /auth/login/identify|face|password),
    seul service relié à `face-api` et à la table `face_enrollment`."""
    try:
        honeytoken = db.is_honeytoken(req.username)
        user = None if honeytoken else db.fetch_user(req.username)
    except Exception as exc:  # indisponibilité base -> 503 explicite
        log.error("auth db unavailable: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "auth backend unavailable"
        ) from exc

    if honeytoken:
        # Compte leurre : seul quelqu'un qui a lu la base le connaît. Preuve de
        # fuite -> alerte (Prometheus + journal SIEM, IP pour le confinement).
        # Réponse identique à un mauvais mot de passe : l'attaquant ne sait rien.
        HONEYTOKEN.labels(kind="login").inc()
        log.warning(
            "HONEYTOKEN login username=%s ip=%s",
            req.username,
            request.headers.get("x-real-ip", "-"),
        )
    if (
        user is None
        or not verify_password(req.password, user["password_hash"])
        or user["role"] == "customer"
    ):
        # `customer` inclus ici (pas de branche dédiée) : ce compte doit
        # passer par payment-api, pas par cet endpoint -> même message
        # générique, pas d'oracle sur l'existence ou le rôle du compte.
        LOGIN_ATTEMPTS.labels(result="failure").inc()
        LOGIN_FAILURES.labels(reason="bad_credentials").inc()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    if user["locked"]:
        LOGIN_ATTEMPTS.labels(result="failure").inc()
        LOGIN_FAILURES.labels(reason="locked").inc()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account locked")

    LOGIN_ATTEMPTS.labels(result="success").inc()
    token = create_access_token(subject=user["username"], role=user["role"])
    return TokenResponse(access_token=token, role=user["role"])


@app.exception_handler(Exception)
def unhandled(_, exc: Exception) -> JSONResponse:  # filet de sécurité, pas de stacktrace exposée
    log.exception("unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "internal error"})
