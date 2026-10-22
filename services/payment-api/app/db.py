"""Accès base pour l'API métier — requêtes paramétrées, transactions courtes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import settings


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(settings.dsn, row_factory=dict_row, connect_timeout=5)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def verify_login_password(username: str, password: str) -> dict | None:
    """Dernière étape du login client (§10.1 : mot de passe après le visage).
    `None` si l'identifiant n'existe pas. Comparaison faite par pgcrypto
    (même format de hash que celui créé par `accounts.create_customer`),
    pas de lecture du hash en clair côté Python."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT (password_hash = crypt(%s, password_hash)) AS ok, locked "
            "FROM app_user WHERE username = %s",
            (password, username),
        ).fetchone()
    return row
