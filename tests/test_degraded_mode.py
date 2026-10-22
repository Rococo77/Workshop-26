"""Mode dégradé : le DoS active la file d'attente, la clôture de l'incident la
lève puis règle les virements en file, et le rapport d'incident le consigne.
Le règlement lui-même (SQL, verrous) est vérifié par scripts/ci-e2e.sh."""

from __future__ import annotations

import pytest

pytest.importorskip("docker")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("prometheus_client")

from conftest import load_service_module  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

engine = load_service_module("rem", "services/remediation-engine", "main")
actions = engine.playbooks.actions  # même module que celui des playbooks
TOKEN = {"X-Remediation-Token": engine.config.REMEDIATION_API_TOKEN}


@pytest.fixture
def calls(monkeypatch):
    log = []
    monkeypatch.setattr(actions, "set_degraded", lambda on: log.append(("degraded", on)) or True)
    monkeypatch.setattr(
        actions, "replay_queue", lambda: log.append(("replay",)) or {"settled": 2, "rejected": 0}
    )
    monkeypatch.setattr(actions, "top_attacker_ip", lambda: None)
    monkeypatch.setattr(actions, "verify_canary", lambda: True)
    return log


def test_dos_active_puis_cloture_rejoue(calls):
    client = TestClient(engine.app)
    ev = client.post("/incident", json={"type": "dos_flood"}, headers=TOKEN).json()
    assert ("degraded", True) in calls
    assert any("mode dégradé" in s for s in ev["steps"])

    client.post("/incident/close", headers=TOKEN)
    # Levée AVANT le rejeu : un virement validé entre les deux est réglé directement.
    assert calls[-2:] == [("degraded", False), ("replay",)]

    report = client.get(f"/reports/{ev['report_id']}").json()
    closing = [a for a in report["actions"] if a.startswith("clôture")]
    assert closing == ["clôture : mode dégradé levé, 2 virement(s) en file réglé(s), 0 rejeté(s)"]


def test_cloture_exige_le_jeton(calls):
    r = TestClient(engine.app).post("/incident/close", headers={"X-Remediation-Token": "x"})
    assert r.status_code == 401
    assert calls == []
