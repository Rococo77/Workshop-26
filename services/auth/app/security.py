"""Primitives de sécurité : hachage mot de passe (bcrypt) et émission JWT."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from .config import settings


def verify_password(plain: str, hashed: str) -> bool:
    """Vérifie un mot de passe contre un hash bcrypt ($2a$/$2b$), y compris les
    hash générés par pgcrypto. bcrypt directement, passlib étant non maintenu."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Hash malformé ou mot de passe hors format -> échec propre, pas de 500.
        return False


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(*, subject: str, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
        "iss": "resilience-alpha-auth",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_pending_face_token(*, subject: str, role: str) -> str:
    """Jeton intermédiaire émis après vérification du mot de passe d'un
    client : ne donne accès à AUCUNE route métier (claim `typ`), seulement
    au second facteur POST /auth/login/face (payment-api). Durée de vie
    courte pour limiter la fenêtre de rejeu."""
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "typ": "face_pending",
        "iat": now,
        "exp": now + timedelta(seconds=settings.face_pending_expire_seconds),
        "iss": "resilience-alpha-auth",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
