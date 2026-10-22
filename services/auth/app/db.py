"""Accès base — pool de connexions psycopg3, requêtes paramétrées uniquement."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import settings


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Connexion courte, fermée systématiquement. Pas de pool externe ici :
    volume faible, simplicité > sur-ingénierie pour un démonstrateur."""
    conn = psycopg.connect(settings.dsn, row_factory=dict_row, connect_timeout=5)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_user(username: str) -> dict | None:
    """Lecture d'un utilisateur. Requête paramétrée (anti-injection)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role, locked " "FROM app_user WHERE username = %s",
            (username,),
        ).fetchone()
    return row


def is_honeytoken(username: str) -> bool:
    """Compte leurre (table `honeytoken`, migration 07) : personne ne s'en sert.
    Base non migrée : aucun leurre, la connexion ne doit pas tomber pour autant."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM honeytoken WHERE value = %s) AS hit", (username,)
            ).fetchone()
    except psycopg.errors.UndefinedTable:
        return False
    return bool(row["hit"])
