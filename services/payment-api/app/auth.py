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

# Claim `typ` des jetons "en attente d'une étape suivante" (le jeton d'accès
# complet, lui, ne porte aucun claim `typ`). Parcours client (§10.1) :
# identifiant -> face_pending -> visage -> password_pending -> mot de passe.
_FACE_PENDING_TYP = "face_pending"
_PASSWORD_PENDING_TYP = "password_pending"


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
    if payload.get("typ"):
        # Jeton intermédiaire (identification ou visage en cours, pas encore
        # un login complet) : ne doit donner accès à AUCUNE route métier.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login not complete")
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
    """Étape visage (POST /auth/login/face) : exige explicitement un jeton
    `face_pending` émis après l'identification (identifiant seul). Un jeton
    d'accès normal est refusé (symétrique à current_principal)."""
    payload = _decode(creds.credentials)
    if payload.get("typ") != _FACE_PENDING_TYP:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    return Principal(username=payload["sub"], role=payload.get("role", "customer"))


def current_pending_password(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Principal:
    """Dernière étape (POST /auth/login/password) : exige un jeton
    `password_pending` émis après un visage reconnu — le mot de passe n'est
    jamais vérifié avant l'identifiant et le visage (ordre imposé, §10.1)."""
    payload = _decode(creds.credentials)
    if payload.get("typ") != _PASSWORD_PENDING_TYP:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    return Principal(username=payload["sub"], role=payload.get("role", "customer"))


def create_pending_face_token(*, subject: str, role: str) -> str:
    """Jeton intermédiaire émis après l'identifiant seul (étape 1) : ne donne
    accès à AUCUNE route métier, seulement à POST /auth/login/face. Durée de
    vie courte pour limiter la fenêtre de rejeu."""
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "typ": _FACE_PENDING_TYP,
        "iat": now,
        "exp": now + timedelta(seconds=settings.face_pending_expire_seconds),
        "iss": "resilience-alpha-auth",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_pending_password_token(*, subject: str, role: str) -> str:
    """Jeton intermédiaire émis après un visage reconnu (étape 3) : ne donne
    accès qu'à POST /auth/login/password, dernière étape du parcours."""
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "typ": _PASSWORD_PENDING_TYP,
        "iat": now,
        "exp": now + timedelta(seconds=settings.face_pending_expire_seconds),
        "iss": "resilience-alpha-auth",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


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
