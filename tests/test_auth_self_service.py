"""Auto-inscription et connexion mot de passe + visage (second facteur) :
validations pures, émission/vérification des jetons JWT, et filtrage par
`purpose` du compteur anti-force-brute — sans conteneur ni base réelle."""

from __future__ import annotations

import contextlib
import time

import pytest

jwt = pytest.importorskip("jwt")
fastapi = pytest.importorskip("fastapi")
pytest.importorskip("pydantic_settings")
pytest.importorskip("psycopg")

from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402
from conftest import load_service_module  # noqa: E402

config = load_service_module("payment_api", "services/payment-api", "config")
db = load_service_module("payment_api", "services/payment-api", "db")
accounts = load_service_module("payment_api", "services/payment-api", "accounts")
biometrics = load_service_module("payment_api", "services/payment-api", "biometrics")
auth = load_service_module("payment_api", "services/payment-api", "auth")


# ------------------------------------------------------------ accounts.py
@pytest.mark.parametrize("username", ["ab", "_system", "a!b", "x" * 33, ""])
def test_invalid_usernames_are_rejected(username):
    with pytest.raises(accounts.AccountError) as exc:
        accounts.validate_username(username)
    assert exc.value.code == "invalid_username"


@pytest.mark.parametrize("username", ["alice", "al.ice_2", "A" + "b" * 31])
def test_valid_usernames_are_accepted(username):
    accounts.validate_username(username)  # ne lève pas


def test_short_password_is_rejected():
    with pytest.raises(accounts.AccountError) as exc:
        accounts.validate_password("short1!")
    assert exc.value.code == "weak_password"


def test_long_enough_password_is_accepted():
    accounts.validate_password("0123456789")  # ne lève pas


# ------------------------------------------------------------ auth.py (JWT)
def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _raw_token(**claims) -> str:
    now = time.time()
    payload = {
        "sub": "jordan",
        "role": "customer",
        "iat": now,
        "exp": now + 60,
        "iss": "resilience-alpha-auth",
        **claims,
    }
    return jwt.encode(payload, config.settings.jwt_secret, algorithm=config.settings.jwt_algorithm)


def test_create_access_token_has_no_typ_claim():
    token = auth.create_access_token(subject="jordan", role="customer")
    payload = jwt.decode(
        token,
        config.settings.jwt_secret,
        algorithms=[config.settings.jwt_algorithm],
        issuer="resilience-alpha-auth",
    )
    assert "typ" not in payload


def test_normal_token_is_accepted_by_current_principal():
    token = auth.create_access_token(subject="jordan", role="customer")
    principal = auth.current_principal(_creds(token))
    assert (principal.username, principal.role) == ("jordan", "customer")


def test_pending_face_token_is_rejected_by_current_principal():
    """Un jeton intermédiaire ne doit ouvrir AUCUNE route métier normale."""
    token = _raw_token(typ="face_pending")
    with pytest.raises(fastapi.HTTPException) as exc:
        auth.current_principal(_creds(token))
    assert exc.value.status_code == 401


def test_normal_token_is_rejected_by_current_pending_face():
    """Symétrique : le second facteur n'accepte pas un jeton d'accès normal."""
    token = auth.create_access_token(subject="jordan", role="customer")
    with pytest.raises(fastapi.HTTPException) as exc:
        auth.current_pending_face(_creds(token))
    assert exc.value.status_code == 401


def test_pending_face_token_is_accepted_by_current_pending_face():
    token = _raw_token(typ="face_pending")
    principal = auth.current_pending_face(_creds(token))
    assert principal.username == "jordan"


# --------------------------------------------- biometrics.py (purpose filter)
class _FakeConn:
    """Capture la requête exécutée sans toucher une vraie base."""

    def __init__(self, row):
        self._row = row
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql, self.params = sql, params
        return self

    def fetchone(self):
        return self._row


def test_recent_failures_filters_by_purpose(monkeypatch):
    fake = _FakeConn({"n": 3})

    @contextlib.contextmanager
    def fake_get_conn():
        yield fake

    monkeypatch.setattr(biometrics.db, "get_conn", fake_get_conn)

    assert biometrics.recent_failures("jordan", 15, purpose="login") == 3
    assert fake.params == ("jordan", "login", 15)

    biometrics.recent_failures("jordan", 15)  # défaut inchangé : 'confirm'
    assert fake.params == ("jordan", "confirm", 15)


# ------------------------------------------- biometrics.py (pool multi-poses)
class _FakeMultiConn:
    """Journalise tous les appels `execute()` ; `fetchone()` consomme les
    résultats fournis dans l'ordre, `fetchall()` renvoie un jeu fixe."""

    def __init__(self, fetchone_results=(), fetchall_result=None):
        self._fetchone_results = list(fetchone_results)
        self._fetchall_result = [] if fetchall_result is None else fetchall_result
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return self._fetchone_results.pop(0) if self._fetchone_results else None

    def fetchall(self):
        return self._fetchall_result


def _patch_get_conn(monkeypatch, fake):
    @contextlib.contextmanager
    def fake_get_conn():
        yield fake

    monkeypatch.setattr(biometrics.db, "get_conn", fake_get_conn)


def test_save_enrollment_writes_all_poses_atomically(monkeypatch):
    # L'utilisateur existe (id=42), aucune empreinte déjà enregistrée.
    fake = _FakeMultiConn(fetchone_results=[{"id": 42}, None])
    _patch_get_conn(monkeypatch, fake)

    poses = {"face": [0.1], "right": [0.2], "up": [0.3], "down": [0.4], "left": [0.5]}
    assert biometrics.save_enrollment("jordan", "Facenet512", poses) is True

    inserts = [c for c in fake.calls if c[0].startswith("INSERT")]
    assert len(inserts) == 5
    assert {params[1] for _, params in inserts} == set(poses)  # une ligne par pose


def test_save_enrollment_refuses_silently_if_already_enrolled(monkeypatch):
    # L'utilisateur existe, une empreinte existe déjà pour une pose au moins.
    fake = _FakeMultiConn(fetchone_results=[{"id": 42}, {"exists": 1}])
    _patch_get_conn(monkeypatch, fake)

    assert biometrics.save_enrollment("jordan", "Facenet512", {"face": [0.1]}) is False
    assert not any(c[0].startswith("INSERT") for c in fake.calls)


def test_get_enrollment_groups_poses_into_a_dict(monkeypatch):
    rows = [
        {"pose": "face", "model_name": "Facenet512", "embedding": [0.1], "created_at": 2},
        {"pose": "left", "model_name": "Facenet512", "embedding": [0.2], "created_at": 1},
    ]
    fake = _FakeMultiConn(fetchall_result=rows)
    _patch_get_conn(monkeypatch, fake)

    enrollment = biometrics.get_enrollment("jordan")
    assert enrollment["poses"] == {"face": [0.1], "left": [0.2]}
    assert enrollment["model_name"] == "Facenet512"


def test_get_enrollment_returns_none_when_no_pose_is_enrolled(monkeypatch):
    fake = _FakeMultiConn(fetchall_result=[])
    _patch_get_conn(monkeypatch, fake)
    assert biometrics.get_enrollment("ghost") is None
