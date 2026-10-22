"""Honeytokens côté API métier (comptes leurres, migration 07).

Deux pièges :
  - un virement vers l'IBAN d'un compte leurre : l'attaquant se sert de
    données volées -> refus (même message qu'un IBAN inconnu) + alerte ;
  - une réponse HTTP qui contient une valeur leurre : des données de la base
    sont en train de sortir -> réponse remplacée par une erreur 500 + alerte.
Aucune réponse légitime ne contient ces valeurs : personne ne possède les
comptes leurres, aucun virement n'aboutit vers eux.
"""

from __future__ import annotations

import logging
import time

import psycopg
from starlette.concurrency import run_in_threadpool

from . import db
from .metrics import HONEYTOKEN

log = logging.getLogger("payment-api.honeytoken")

_CACHE_SECONDS = 60
_markers: list[bytes] = []
_loaded_at = 0.0


def markers() -> list[bytes]:
    """Valeurs leurres, relues en base au plus une fois par minute. Base
    indisponible ou non migrée : on garde la dernière liste connue."""
    global _markers, _loaded_at
    if time.monotonic() - _loaded_at > _CACHE_SECONDS:
        try:
            with db.get_conn() as conn:
                rows = conn.execute("SELECT value FROM honeytoken").fetchall()
            _markers = [r["value"].encode() for r in rows]
        except psycopg.Error as exc:
            log.warning("liste des honeytokens indisponible: %s", exc)
        _loaded_at = time.monotonic()
    return _markers


def is_honey_account(account_id: int) -> bool:
    try:
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM honeytoken h JOIN account a "
                "ON a.iban_fake = h.value WHERE a.id = %s) AS hit",
                (account_id,),
            ).fetchone()
    except psycopg.errors.UndefinedTable:
        return False
    return bool(row["hit"])


def trigger(kind: str, ip: str | None, detail: str) -> None:
    HONEYTOKEN.labels(kind=kind).inc()
    log.warning("HONEYTOKEN %s %s ip=%s", kind, detail, ip or "-")


class ExfiltrationGuard:
    """Middleware ASGI : retient chaque réponse HTTP jusqu'à son dernier
    fragment, et la remplace si elle contient une valeur leurre."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        found = await run_in_threadpool(markers)
        if not found:
            return await self.app(scope, receive, send)

        start: dict | None = None
        chunks: list[bytes] = []

        async def guarded_send(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                return
            if message["type"] != "http.response.body":
                return await send(message)
            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            body = b"".join(chunks)
            hit = next((m for m in found if m in body), None)
            if hit is None:
                await send(start)
                await send({"type": "http.response.body", "body": body})
                return
            ip = dict(scope["headers"]).get(b"x-real-ip", b"-").decode()
            await run_in_threadpool(
                trigger, "exfiltration", ip, f"path={scope['path']} valeur={hit.decode()}"
            )
            blocked = b'{"detail":"internal error"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(blocked)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": blocked})

        await self.app(scope, receive, guarded_send)
