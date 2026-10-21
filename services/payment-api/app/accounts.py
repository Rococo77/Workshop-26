"""Création de comptes client : partagée entre l'auto-inscription (API web)
et l'outil d'enrôlement opérateur (`enroll_cli`, hors parcours web).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from . import db

# Identifiant simple : lettres/chiffres/points/underscores, commence par une
# lettre. Le préfixe `_` est réservé aux comptes système (canari).
_USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.]{2,31}$")
_MIN_PASSWORD_LENGTH = 10


class AccountError(Exception):
    """Erreur métier attendue (nom déjà pris, mot de passe trop faible...)
    -> 4xx, pas 500. `code` est remonté tel quel au front."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def validate_username(username: str) -> None:
    if not _USERNAME_RE.match(username):
        raise AccountError("invalid_username")


def validate_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise AccountError("weak_password")


def next_iban() -> str:
    with db.get_conn() as conn:
        n = conn.execute("SELECT count(*) AS n FROM account").fetchone()["n"]
    return f"FR76-FAKE-{n + 1:04d}"


def create_customer(
    username: str, password: str, iban: str, balance: Decimal, consent_at: datetime
) -> int:
    """Crée un client (rôle `customer`) et son compte. `consent_at` : date à
    laquelle le consentement au traitement de la donnée biométrique a été
    recueilli (RGPD art. 9) — toujours requis, aucun enrôlement sans
    consentement tracé. Lève `AccountError("username_taken")` si le nom est
    déjà pris. Renvoie l'id du nouvel utilisateur."""
    with db.get_conn() as conn:
        user = conn.execute(
            "INSERT INTO app_user (username, password_hash, role, biometric_consent_at) "
            "VALUES (%s, crypt(%s, gen_salt('bf')), 'customer', %s) "
            "ON CONFLICT (username) DO NOTHING RETURNING id",
            (username, password, consent_at),
        ).fetchone()
        if user is None:
            raise AccountError("username_taken")
        conn.execute(
            "INSERT INTO account (owner_id, iban_fake, balance, currency) "
            "VALUES (%s, %s, %s, 'EUR')",
            (user["id"], iban.strip().upper(), balance),
        )
        return user["id"]
