"""Service d'authentification — émission de JWT, métriques Prometheus.

Expose volontairement `auth_login_failures_total` : signal clé pour la
détection d'anomalie (brute force / credential stuffing).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field

from . import db
from .security import create_access_token, create_pending_face_token, verify_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("auth")

app = FastAPI(title="Resilience-Alpha Auth", version="1.0.0")

LOGIN_ATTEMPTS = Counter("auth_login_attempts_total", "Tentatives de connexion", ["result"])
LOGIN_FAILURES = Counter("auth_login_failures_total", "Échecs de connexion", ["reason"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class FaceRequiredResponse(BaseModel):
    status: str = "face_required"
    pending_token: str
    role: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/login")
def login(req: LoginRequest) -> TokenResponse | FaceRequiredResponse:
    """Mot de passe seul pour operator/admin (pas de compte bancaire, pas de
    visage enrôlé). Pour un client (`customer`), le mot de passe n'ouvre
    qu'un jeton intermédiaire `face_pending` : le second facteur (visage)
    est vérifié par payment-api, seul service relié à `face-api`
    (POST /auth/login/face), qui émet alors le jeton d'accès complet."""
    try:
        user = db.fetch_user(req.username)
    except Exception as exc:  # indisponibilité base -> 503 explicite
        log.error("auth db unavailable: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "auth backend unavailable"
        ) from exc

    if user is None or not verify_password(req.password, user["password_hash"]):
        LOGIN_ATTEMPTS.labels(result="failure").inc()
        LOGIN_FAILURES.labels(reason="bad_credentials").inc()
        # Message volontairement générique (pas d'oracle username/password).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    if user["locked"]:
        LOGIN_ATTEMPTS.labels(result="failure").inc()
        LOGIN_FAILURES.labels(reason="locked").inc()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account locked")

    if user["role"] != "customer":
        LOGIN_ATTEMPTS.labels(result="success").inc()
        token = create_access_token(subject=user["username"], role=user["role"])
        return TokenResponse(access_token=token, role=user["role"])

    if not db.has_face_enrollment(user["username"]):
        # Ne devrait pas arriver (l'auto-inscription enrôle le visage dans
        # le même appel) : garde-fou, pas un cas nominal.
        LOGIN_ATTEMPTS.labels(result="failure").inc()
        LOGIN_FAILURES.labels(reason="face_not_enrolled").inc()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "face verification not configured")

    # Mot de passe correct mais second facteur requis : pas un échec.
    LOGIN_ATTEMPTS.labels(result="pending_face").inc()
    pending = create_pending_face_token(subject=user["username"], role=user["role"])
    return FaceRequiredResponse(pending_token=pending, role=user["role"])


@app.exception_handler(Exception)
def unhandled(_, exc: Exception) -> JSONResponse:  # filet de sécurité, pas de stacktrace exposée
    log.exception("unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "internal error"})
