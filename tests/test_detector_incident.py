"""Un incident = une remédiation : tant que l'anomalie persiste, le détecteur ne
relance le moteur que si la remédiation précédente a échoué ou si la nature de
l'incident change. Régression : relance systématique à chaque cooldown (45 s).
"""

from __future__ import annotations

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from conftest import load_service_module  # noqa: E402

load_service_module("det", "services/ml-detector", "config")
detector = load_service_module("det", "services/ml-detector", "main")


def test_une_remediation_par_incident(monkeypatch):
    monkeypatch.setattr(detector, "_open_incident", None)
    assert detector._should_send("dos_flood", in_cooldown=False)  # nouvel incident

    monkeypatch.setattr(detector, "_open_incident", "dos_flood")
    monkeypatch.setattr(detector, "_last_outcome", "recovered")
    assert not detector._should_send("dos_flood", in_cooldown=False)  # déjà rétabli
    assert detector._should_send("service_unavailable", in_cooldown=False)  # autre nature

    monkeypatch.setattr(detector, "_last_outcome", "failed")
    assert detector._should_send("dos_flood", in_cooldown=False)  # échec -> on relance
    assert not detector._should_send("dos_flood", in_cooldown=True)  # mais pas en rafale
