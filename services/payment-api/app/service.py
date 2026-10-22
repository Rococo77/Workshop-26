"""Logique métier : virement atomique entre deux comptes.

Séparé du routage (le contrôleur ne porte pas de logique métier).
Verrouillage pessimiste ordonné par id pour éviter les interblocages et
garantir la cohérence du solde sous concurrence.

Deux chemins :
  - `transfer` : règlement immédiat (canari, validation faciale désactivée) ;
  - `create_pending` -> `settle_pending` : virement client, réglé seulement
    après reconnaissance faciale. Les fonds ne bougent qu'au règlement.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import psycopg

from . import db


class BusinessError(Exception):
    """Erreur métier attendue (ex. solde insuffisant) -> 4xx, pas 500."""


def account_id_by_iban(iban: str) -> int:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM account WHERE iban_fake = %s", (iban.strip().upper(),)
        ).fetchone()
    if row is None:
        raise BusinessError("destination account not found")
    return row["id"]


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


def _validate(src_account: int, dst_account: int, amount: Decimal) -> None:
    if amount <= 0:
        raise BusinessError("amount must be positive")
    if src_account == dst_account:
        raise BusinessError("source and destination must differ")


def _move_funds(
    conn: psycopg.Connection, *, username: str, src_account: int, dst_account: int, amount: Decimal
) -> None:
    # Verrou ordonné (id croissant) -> pas de deadlock croisé.
    first, second = sorted((src_account, dst_account))
    conn.execute(
        "SELECT id FROM account WHERE id IN (%s, %s) ORDER BY id FOR UPDATE", (first, second)
    )

    src = _get_account_for_user(conn, src_account, username)
    dst = conn.execute("SELECT id, balance FROM account WHERE id = %s", (dst_account,)).fetchone()
    if dst is None:
        raise BusinessError("destination account not found")

    if Decimal(src["balance"]) < amount:
        raise BusinessError("insufficient funds")

    conn.execute("UPDATE account SET balance = balance - %s WHERE id = %s", (amount, src_account))
    conn.execute("UPDATE account SET balance = balance + %s WHERE id = %s", (amount, dst_account))


def _new_reference() -> str:
    return f"TX-{uuid.uuid4().hex[:12]}"


CANARY_USERS = ("_canary_src", "_canary_dst")


def canary_route() -> tuple[str, int, int]:
    """(propriétaire source, compte source, compte destination) du canari.

    Comptes retrouvés par utilisateur (et non par id en dur : sur une base
    existante, les ids 1/2 appartiennent à d'autres clients). La source est le
    compte le mieux approvisionné : le canari fait l'aller-retour et ne vide
    jamais un compte, quel que soit le nombre de vérifications de reprise."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT u.username, a.id, a.balance FROM account a "
            "JOIN app_user u ON u.id = a.owner_id "
            "WHERE u.username = ANY(%s) ORDER BY a.balance DESC, a.id",
            (list(CANARY_USERS),),
        ).fetchall()
    by_user = {r["username"]: r for r in reversed(rows)}  # un compte par utilisateur
    if len(by_user) != len(CANARY_USERS):
        raise LookupError("comptes canari absents (migration 06_canary_accounts.sql)")
    src, dst = sorted(by_user.values(), key=lambda r: r["balance"], reverse=True)
    return src["username"], src["id"], dst["id"]


def transfer(
    *, username: str, src_account: int, dst_account: int, amount: Decimal, is_canary: bool = False
) -> dict:
    _validate(src_account, dst_account, amount)

    with db.get_conn() as conn:
        _move_funds(
            conn,
            username=username,
            src_account=src_account,
            dst_account=dst_account,
            amount=amount,
        )

        reference = _new_reference()
        tx = conn.execute(
            "INSERT INTO payment_tx "
            "(src_account, dst_account, amount, status, reference, is_canary, settled_at) "
            "VALUES (%s, %s, %s, 'settled', %s, %s, now()) "
            "RETURNING id, reference, status, amount, created_at",
            (src_account, dst_account, amount, reference, is_canary),
        ).fetchone()

    return tx


# --------------------------------------------------------------------------
#  Virement en attente de validation faciale
# --------------------------------------------------------------------------
def expire_pending() -> None:
    """Rejette les virements en attente dont la fenêtre de validation est passée."""
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE payment_tx SET status = 'rejected', reject_reason = 'expired' "
            "WHERE status = 'pending' AND expires_at < now()"
        )


def create_pending(
    *, username: str, src_account: int, dst_account: int, amount: Decimal, ttl_seconds: int
) -> dict:
    _validate(src_account, dst_account, amount)

    with db.get_conn() as conn:
        src = conn.execute(
            "SELECT a.id, a.balance FROM account a JOIN app_user u ON u.id = a.owner_id "
            "WHERE a.id = %s AND u.username = %s",
            (src_account, username),
        ).fetchone()
        if src is None:
            raise BusinessError("source account not found or not owned")
        if conn.execute("SELECT 1 FROM account WHERE id = %s", (dst_account,)).fetchone() is None:
            raise BusinessError("destination account not found")
        # Contrôle anticipé (UX) ; le solde fait foi au règlement, sous verrou.
        if Decimal(src["balance"]) < amount:
            raise BusinessError("insufficient funds")

        return conn.execute(
            "INSERT INTO payment_tx (src_account, dst_account, amount, status, reference, "
            "expires_at) VALUES (%s, %s, %s, 'pending', %s, now() + make_interval(secs => %s)) "
            "RETURNING id, reference, status, amount, expires_at, confirm_attempts",
            (src_account, dst_account, amount, _new_reference(), ttl_seconds),
        ).fetchone()


def get_pending(tx_id: int, username: str) -> dict:
    """Virement en attente du client, sinon BusinessError (introuvable / clos)."""
    expire_pending()
    with db.get_conn() as conn:
        tx = conn.execute(
            "SELECT t.id, t.reference, t.status, t.amount, t.expires_at, t.confirm_attempts, "
            "t.reject_reason FROM payment_tx t "
            "JOIN account s ON s.id = t.src_account JOIN app_user u ON u.id = s.owner_id "
            "WHERE t.id = %s AND u.username = %s",
            (tx_id, username),
        ).fetchone()
    if tx is None:
        raise BusinessError("transaction not found")
    if tx["status"] != "pending":
        raise BusinessError(f"transaction {tx['reject_reason'] or tx['status']}")
    return tx


def settle_pending(tx_id: int, username: str) -> dict:
    """Règle un virement en attente après validation faciale. Atomique : le
    verrou sur la ligne empêche un double règlement par deux confirmations."""
    try:
        with db.get_conn() as conn:
            tx = conn.execute(
                "SELECT id, src_account, dst_account, amount FROM payment_tx "
                "WHERE id = %s AND status = 'pending' AND expires_at >= now() FOR UPDATE",
                (tx_id,),
            ).fetchone()
            if tx is None:
                raise BusinessError("transaction not pending")
            _move_funds(
                conn,
                username=username,
                src_account=tx["src_account"],
                dst_account=tx["dst_account"],
                amount=Decimal(tx["amount"]),
            )
            return conn.execute(
                "UPDATE payment_tx SET status = 'settled', settled_at = now() WHERE id = %s "
                "RETURNING id, reference, status, amount",
                (tx_id,),
            ).fetchone()
    except BusinessError as exc:
        if str(exc) == "insufficient funds":
            reject_pending(tx_id, "insufficient_funds")
        raise


def record_failed_attempt(tx_id: int, max_attempts: int) -> int:
    """Compte un échec de reconnaissance ; rejette le virement au dernier.
    Renvoie le nombre d'essais restants."""
    with db.get_conn() as conn:
        row = conn.execute(
            "UPDATE payment_tx SET confirm_attempts = confirm_attempts + 1, "
            "status = CASE WHEN confirm_attempts + 1 >= %(max)s THEN 'rejected' ELSE status END, "
            "reject_reason = CASE WHEN confirm_attempts + 1 >= %(max)s THEN 'face_mismatch' "
            "ELSE reject_reason END "
            "WHERE id = %(id)s AND status = 'pending' RETURNING confirm_attempts",
            {"id": tx_id, "max": max_attempts},
        ).fetchone()
    return 0 if row is None else max(0, max_attempts - row["confirm_attempts"])


def reject_pending(tx_id: int, reason: str) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE payment_tx SET status = 'rejected', reject_reason = %s "
            "WHERE id = %s AND status = 'pending'",
            (reason, tx_id),
        )


# --------------------------------------------------------------------------
#  Mode dégradé : file d'attente pendant une remédiation (migration 08)
# --------------------------------------------------------------------------
def degraded(max_minutes: int) -> bool:
    """Mode dégradé actif ? Expire seul au bout de `max_minutes` : si le
    moteur ne le lève pas (redémarré pendant l'incident), les paiements ne
    restent pas en file indéfiniment. Base non migrée : mode normal."""
    try:
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT degraded AND since > now() - make_interval(mins => %s) AS active "
                "FROM platform_mode WHERE id = 1",
                (max_minutes,),
            ).fetchone()
    except psycopg.errors.UndefinedTable:
        return False
    return bool(row and row["active"])


def set_degraded(enabled: bool) -> None:
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE platform_mode SET degraded = %s, since = now() WHERE id = 1", (enabled,)
        )


def queue_pending(tx_id: int, username: str) -> dict:
    """Virement validé (visage OK) mis en file au lieu d'être réglé. Même
    garde que settle_pending (statut + délai) : une seule transition possible."""
    with db.get_conn() as conn:
        tx = conn.execute(
            "UPDATE payment_tx t SET status = 'queued', queued_at = now() "
            "FROM account a JOIN app_user u ON u.id = a.owner_id "
            "WHERE t.id = %s AND t.status = 'pending' AND t.expires_at >= now() "
            "AND a.id = t.src_account AND u.username = %s "
            "RETURNING t.id, t.reference, t.status, t.amount",
            (tx_id, username),
        ).fetchone()
    if tx is None:
        raise BusinessError("transaction not pending")
    return tx


def replay_queue(limit: int = 1000) -> dict:
    """Règle les virements en file, du plus ancien au plus récent, un par
    transaction SQL. SKIP LOCKED : deux rejeux simultanés ne règlent jamais
    deux fois le même virement. Solde devenu insuffisant -> rejeté."""
    done = {"settled": 0, "rejected": 0}
    for _ in range(limit):
        with db.get_conn() as conn:
            tx = conn.execute(
                "SELECT t.id, t.src_account, t.dst_account, t.amount, u.username "
                "FROM payment_tx t JOIN account a ON a.id = t.src_account "
                "JOIN app_user u ON u.id = a.owner_id "
                "WHERE t.status = 'queued' ORDER BY t.id LIMIT 1 FOR UPDATE OF t SKIP LOCKED"
            ).fetchone()
            if tx is None:
                break
            try:
                _move_funds(
                    conn,
                    username=tx["username"],
                    src_account=tx["src_account"],
                    dst_account=tx["dst_account"],
                    amount=Decimal(tx["amount"]),
                )
            except BusinessError as exc:
                reason = "replay_failed"
                if str(exc) == "insufficient funds":
                    reason = "insufficient_funds"
                conn.execute(
                    "UPDATE payment_tx SET status = 'rejected', reject_reason = %s WHERE id = %s",
                    (reason, tx["id"]),
                )
                done["rejected"] += 1
                continue
            conn.execute(
                "UPDATE payment_tx SET status = 'settled', settled_at = now() WHERE id = %s",
                (tx["id"],),
            )
            done["settled"] += 1
    return done
