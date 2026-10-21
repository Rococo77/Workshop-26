"""Vérification du JWT émis par le service auth (secret partagé HS256), et
émission des tokens côté payment-api (inscription, second facteur visage)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .config import settings

_bearer = HTTPBearer(auto_error=True)

# Claim `typ` des jetons "en attente de second facteur" (voir security.py du
# service auth : le jeton complet, lui, ne porte pas ce claim).
_FACE_PENDING_TYP = "face_pending"


class Principal(BaseModel):
    username: str
    role: str


def _decode(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="resilience-alpha-auth",
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from None


def current_principal(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Principal:
    payload = _decode(creds.credentials)
    if payload.get("typ") == _FACE_PENDING_TYP:
        # Jeton intermédiaire (mot de passe validé, visage pas encore vérifié) :
        # ne doit donner accès à AUCUNE route métier.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "face verification required")
    return Principal(username=payload["sub"], role=payload.get("role", "customer"))


def current_customer(principal: Principal = Depends(current_principal)) -> Principal:
    """Opérations bancaires réservées au rôle customer : operator et admin
    supervisent la plateforme (/supervision) mais n'opèrent pas de paiements."""
    if principal.role != "customer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "customer role required")
    return principal


def current_pending_face(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Principal:
    """Second facteur (POST /auth/login/face) : exige explicitement un jeton
    `face_pending` émis par le service auth après vérification du mot de
    passe. Un jeton d'accès normal est refusé (symétrique à current_principal)."""
    payload = _decode(creds.credentials)
    if payload.get("typ") != _FACE_PENDING_TYP:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    return Principal(username=payload["sub"], role=payload.get("role", "customer"))


def create_access_token(*, subject: str, role: str) -> str:
    """Émission d'un jeton d'accès complet par payment-api (fin d'inscription
    ou second facteur visage validé) : même forme que celui du service auth
    (secret et claims partagés), aucun claim `typ`."""
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
        "iss": "resilience-alpha-auth",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
