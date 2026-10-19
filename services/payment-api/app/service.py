"""Logique métier : virement atomique entre deux comptes.

Séparé du routage (le contrôleur ne porte pas de logique métier).
Verrouillage pessimiste ordonné par id pour éviter les interblocages et
garantir la cohérence du solde sous concurrence.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import psycopg

from . import db


class BusinessError(Exception):
    """Erreur métier attendue (ex. solde insuffisant) -> 4xx, pas 500."""


def _get_account_for_user(conn: psycopg.Connection, account_id: int, username: str) -> dict:
    row = conn.execute(
        "SELECT a.id, a.balance FROM account a "
        "JOIN app_user u ON u.id = a.owner_id "
        "WHERE a.id = %s AND u.username = %s FOR UPDATE",
        (account_id, username),
    ).fetchone()
    if row is None:
        raise BusinessError("source account not found or not owned")
    return row


def transfer(
    *, username: str, src_account: int, dst_account: int, amount: Decimal, is_canary: bool = False
) -> dict:
    if amount <= 0:
        raise BusinessError("amount must be positive")
    if src_account == dst_account:
        raise BusinessError("source and destination must differ")

    # Verrou ordonné (id croissant) -> pas de deadlock croisé.
    first, second = sorted((src_account, dst_account))

    with db.get_conn() as conn:
        conn.execute(
            "SELECT id FROM account WHERE id IN (%s, %s) ORDER BY id FOR UPDATE", (first, second)
        )

        src = _get_account_for_user(conn, src_account, username)
        dst = conn.execute(
            "SELECT id, balance FROM account WHERE id = %s", (dst_account,)
        ).fetchone()
        if dst is None:
            raise BusinessError("destination account not found")

        if Decimal(src["balance"]) < amount:
            raise BusinessError("insufficient funds")

        conn.execute(
            "UPDATE account SET balance = balance - %s WHERE id = %s", (amount, src_account)
        )
        conn.execute(
            "UPDATE account SET balance = balance + %s WHERE id = %s", (amount, dst_account)
        )

        reference = f"TX-{uuid.uuid4().hex[:12]}"
        tx = conn.execute(
            "INSERT INTO payment_tx "
            "(src_account, dst_account, amount, status, reference, is_canary) "
            "VALUES (%s, %s, %s, 'settled', %s, %s) "
            "RETURNING id, reference, status, amount, created_at",
            (src_account, dst_account, amount, reference, is_canary),
        ).fetchone()

    return tx
