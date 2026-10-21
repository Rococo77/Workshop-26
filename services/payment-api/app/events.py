"""Diffusion temps réel des résultats de vérification faciale (login,
confirmation de virement) vers des clients WebSocket (ex. indicateur LED
ESP8266, voir `firmware/face-led/`).

Découplé du code HTTP synchrone : `login_face`/`confirm_transaction` (dans
`main.py`) font des appels psycopg bloquants, donc restent des `def`
classiques, exécutés hors de la boucle asyncio (threadpool de Starlette).
`publish()` doit donc pouvoir être appelée depuis un AUTRE thread que celui
de la boucle : on utilise `call_soon_threadsafe` plutôt qu'une file
bloquante (qui laisserait un thread d'exécuteur bloqué indéfiniment sur
`queue.get()`, jamais vraiment interrompu par l'annulation de la tâche).
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger("payment-api.events")

_queue: asyncio.Queue[dict] | None = None
_loop: asyncio.AbstractEventLoop | None = None
_clients: set[WebSocket] = set()


def publish(event: dict) -> None:
    """Appelé depuis le code synchrone (login_face, confirm_transaction),
    potentiellement un thread différent de celui de la boucle asyncio. Sans
    boucle capturée (`broadcast_loop` jamais démarrée), l'événement est
    simplement perdu plutôt que de bloquer l'appelant."""
    if _loop is not None and _queue is not None:
        _loop.call_soon_threadsafe(_queue.put_nowait, event)


def register(websocket: WebSocket) -> None:
    _clients.add(websocket)


def unregister(websocket: WebSocket) -> None:
    _clients.discard(websocket)


async def broadcast_loop() -> None:
    """Tâche de fond (démarrée au lancement de l'app, voir `main.py`) :
    relaie chaque événement publié à tous les clients connectés. Un client
    dont l'envoi échoue (déconnecté) est retiré. La file est (re)créée ici,
    liée à la boucle asyncio courante (jamais réutilisée entre deux boucles,
    ex. entre deux tests)."""
    global _loop, _queue
    _loop = asyncio.get_running_loop()
    _queue = asyncio.Queue()
    while True:
        event = await _queue.get()
        payload = json.dumps(event)
        for ws in list(_clients):
            try:
                await ws.send_text(payload)
            except Exception as exc:  # client parti sans fermeture propre
                log.info("client WebSocket retiré (envoi échoué): %s", exc)
                _clients.discard(ws)
