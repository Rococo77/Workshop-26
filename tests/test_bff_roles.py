"""Contrôle d'accès de la supervision : la vue détaillée (IP bloquées, alertes,
étapes des playbooks) est réservée aux rôles operator et admin. Un client ou un
visiteur sans jeton n'y accède pas ; un jeton forgé avec un autre secret non plus.
"""

from __future__ import annotations

import secrets
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
jwt = pytest.importorskip("jwt")

from conftest import load_service_module  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402

bff = load_service_module("bff", "services/supervision-bff", "main")


def _creds(role: str, key: str | None = None) -> HTTPAuthorizationCredentials:
    token = jwt.encode(
        {"sub": "u", "role": role, "iss": "resilience-alpha-auth", "exp": int(time.time()) + 60},
        key or bff.JWT_SECRET,
        algorithm="HS256",
    )
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_supervision_autorisee(role):
    assert bff.require_supervisor(_creds(role)) == "u"


@pytest.mark.parametrize(
    ("creds", "code"),
    [
        (None, 401),  # pas de jeton
        ("customer", 403),  # client : seulement /status
        ("forged", 401),  # signé avec un autre secret
    ],
)
def test_supervision_refusee(creds, code):
    if creds == "customer":
        creds = _creds("customer")
    elif creds == "forged":
        creds = _creds("operator", key=secrets.token_hex(16))  # autre clé
    with pytest.raises(HTTPException) as exc:
        bff.require_supervisor(creds)
    assert exc.value.status_code == code
