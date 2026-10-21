"""Relais temps réel des vérifications faciales (indicateur LED ESP8266) :
`events.publish`/`broadcast_loop` avec de faux clients WebSocket, sans
conteneur ni connexion réelle."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

pytest.importorskip("fastapi")

from conftest import load_service_module  # noqa: E402

events = load_service_module("payment_api", "services/payment-api", "events")


class _FakeWebSocket:
    def __init__(self, *, fail=False):
        self.sent: list[str] = []
        self.fail = fail

    async def send_text(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("client parti")
        self.sent.append(text)


async def _drain_once():
    """Laisse `broadcast_loop` traiter les événements déjà publiés."""
    await asyncio.sleep(0.05)


def test_broadcast_loop_relays_events_to_registered_clients():
    async def scenario():
        ws = _FakeWebSocket()
        events.register(ws)
        task = asyncio.create_task(events.broadcast_loop())
        await asyncio.sleep(0)  # laisse broadcast_loop capturer la boucle (publish() en dépend)
        try:
            events.publish({"ok": True, "purpose": "login"})
            await _drain_once()
            return ws.sent
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            events.unregister(ws)

    sent = asyncio.run(scenario())
    assert sent == ['{"ok": true, "purpose": "login"}']


def test_broadcast_loop_drops_clients_whose_send_fails():
    async def scenario():
        broken = _FakeWebSocket(fail=True)
        healthy = _FakeWebSocket()
        events.register(broken)
        events.register(healthy)
        task = asyncio.create_task(events.broadcast_loop())
        await asyncio.sleep(0)
        try:
            events.publish({"ok": False, "purpose": "confirm"})
            await _drain_once()
            events.publish({"ok": True, "purpose": "confirm"})
            await _drain_once()
            return healthy.sent
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            events.unregister(broken)
            events.unregister(healthy)

    # Le client en échec ne doit ni planter la diffusion, ni empêcher le
    # second événement d'atteindre le client sain.
    sent = asyncio.run(scenario())
    assert sent == [
        '{"ok": false, "purpose": "confirm"}',
        '{"ok": true, "purpose": "confirm"}',
    ]
