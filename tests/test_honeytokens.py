"""Honeytokens : un compte leurre n'ouvre jamais de session, et une réponse
qui contient une valeur leurre ne sort pas de l'API (remplacée par une 500).
Chaque déclenchement incrémente honeytoken_triggers_total (lu par le détecteur)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("psycopg")
pytest.importorskip("pydantic_settings")

from conftest import load_service_module  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from prometheus_client import REGISTRY  # noqa: E402

load_service_module("payment_api", "services/payment-api", "config")
honeytokens = load_service_module("payment_api", "services/payment-api", "honeytokens")
# Même métrique dans les deux services : en production deux processus, ici un
# seul registre. Le compteur de payment-api reste utilisable hors registre.
REGISTRY.unregister(honeytokens.HONEYTOKEN)

load_service_module("auth_svc", "services/auth", "config")
auth_db = load_service_module("auth_svc", "services/auth", "db")
auth_main = load_service_module("auth_svc", "services/auth", "main")


def _count(counter, kind: str) -> float:
    return counter.labels(kind=kind)._value.get()


def _guarded_app() -> TestClient:
    app = FastAPI()
    app.add_middleware(honeytokens.ExfiltrationGuard)

    @app.get("/dump")
    def dump():
        return [{"iban": "FR76-FAKE-0003"}, {"iban": "FR76-FAKE-7341"}]

    @app.get("/ok")
    def ok():
        return [{"iban": "FR76-FAKE-0003"}]

    return TestClient(app)


def test_reponse_avec_valeur_leurre_bloquee(monkeypatch):
    monkeypatch.setattr(honeytokens, "markers", lambda: [b"FR76-FAKE-7341"])
    before = _count(honeytokens.HONEYTOKEN, "exfiltration")
    r = _guarded_app().get("/dump", headers={"X-Real-IP": "192.168.137.42"})
    assert r.status_code == 500
    assert b"7341" not in r.content
    assert _count(honeytokens.HONEYTOKEN, "exfiltration") == before + 1


def test_reponse_legitime_inchangee(monkeypatch):
    monkeypatch.setattr(honeytokens, "markers", lambda: [b"FR76-FAKE-7341"])
    r = _guarded_app().get("/ok")
    assert r.status_code == 200
    assert r.json() == [{"iban": "FR76-FAKE-0003"}]


def test_connexion_compte_leurre_refusee_et_signalee(monkeypatch):
    monkeypatch.setattr(auth_db, "is_honeytoken", lambda u: True)
    monkeypatch.setattr(auth_db, "fetch_user", lambda u: pytest.fail("compte leurre lu"))
    before = _count(auth_main.HONEYTOKEN, "login")
    r = TestClient(auth_main.app).post(
        "/login", json={"username": "m.lefevre.dsi", "password": "nimporte"}
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"  # même réponse qu'un mauvais mot de passe
    assert _count(auth_main.HONEYTOKEN, "login") == before + 1
