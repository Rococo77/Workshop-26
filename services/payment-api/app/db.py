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


def customer_needs_reenrollment(username: str) -> bool:
    """Étape 1 du login client (§10.1) : un visage a-t-il déjà été réinitialisé
    par le back-office (plus aucune empreinte enrôlée) ? `False` pour un
    identifiant inexistant, non-client ou verrouillé — traité comme un login
    normal, pas de bascule vers le parcours de ré-enrôlement."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT locked, EXISTS(SELECT 1 FROM face_enrollment e "
            "WHERE e.user_id = u.id) AS enrolled "
            "FROM app_user u WHERE u.username = %s AND u.role = 'customer'",
            (username,),
        ).fetchone()
    return row is not None and not row["locked"] and not row["enrolled"]


def list_users() -> list[dict]:
    """Back-office (§10.1) : tous les comptes (customer/operator/admin) et
    l'état du visage enrôlé — non pertinent pour operator/admin (jamais
    enrôlés), affiché `enrolled: false` pour eux par simple absence de ligne."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT u.username, u.role, u.locked, "
            "EXISTS(SELECT 1 FROM face_enrollment e WHERE e.user_id = u.id) AS enrolled, "
            "(SELECT min(e.created_at) FROM face_enrollment e "
            "WHERE e.user_id = u.id) AS enrolled_at "
            "FROM app_user u ORDER BY u.role, u.username"
        ).fetchall()
    return [
        {
            "username": r["username"],
            "role": r["role"],
            "locked": r["locked"],
            "enrolled": r["enrolled"],
            "enrolled_at": r["enrolled_at"].isoformat() if r["enrolled_at"] else None,
        }
        for r in rows
    ]


def set_account_locked(username: str, locked: bool) -> bool:
    """Active/désactive un compte, tous rôles confondus. `False` si le
    compte n'existe pas."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE app_user SET locked = %s WHERE username = %s", (locked, username)
        )
        return cur.rowcount > 0


def set_account_role(username: str, role: str) -> bool:
    """Change le rôle d'un compte. `role` doit déjà avoir été validé par
    l'appelant (customer/operator/admin) : la contrainte CHECK en base n'est
    qu'un filet de sécurité, pas la première ligne de validation."""
    with get_conn() as conn:
        cur = conn.execute("UPDATE app_user SET role = %s WHERE username = %s", (role, username))
        return cur.rowcount > 0
