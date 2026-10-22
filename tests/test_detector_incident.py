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


def test_point_anormal_isole_sans_incident(monkeypatch):
    """Un faux positif isolé n'ouvre pas d'incident : il faut CONFIRM_POINTS
    points anormaux consécutifs, et un point normal remet le compteur à zéro."""
    sent = []
    verdicts = iter([True, False, True, True])
    monkeypatch.setattr(detector, "_service_down", lambda c: False)
    monkeypatch.setattr(detector.sources, "honeytoken_kinds", lambda c: [])
    monkeypatch.setattr(detector.sources, "collect_features", lambda c: {})
    monkeypatch.setattr(detector.sources, "classify_attack", lambda c: "dos_flood")
    monkeypatch.setattr(detector._model, "score", lambda f: (next(verdicts), 0.6, {}))
    monkeypatch.setattr(detector._model, "top_drivers", lambda c: [])
    monkeypatch.setattr(detector, "_send_incident", lambda c, p: sent.append(p["type"]))
    monkeypatch.setattr(detector, "_open_incident", None)
    monkeypatch.setattr(detector, "_streak", 0)
    monkeypatch.setattr(detector, "_last_sent", 0.0)
    monkeypatch.setattr(detector.config, "CONFIRM_POINTS", 2)

    detector._tick(None)  # anormal isolé
    detector._tick(None)  # normal : compteur remis à zéro
    detector._tick(None)  # anormal (1/2)
    assert sent == []
    detector._tick(None)  # anormal (2/2) : incident confirmé
    assert sent == ["dos_flood"]


def test_honeytoken_incident_immediat_sans_ml(monkeypatch):
    """Compte leurre utilisé : incident dès le premier point, le modèle n'est
    pas consulté (aucun usage légitime possible)."""
    sent = []
    monkeypatch.setattr(detector, "_service_down", lambda c: False)
    monkeypatch.setattr(detector.sources, "honeytoken_kinds", lambda c: ["login"])
    monkeypatch.setattr(detector._model, "score", lambda f: pytest.fail("ML consulté"))
    monkeypatch.setattr(detector, "_send_incident", lambda c, p: sent.append(p))
    monkeypatch.setattr(detector, "_open_incident", None)
    monkeypatch.setattr(detector, "_last_sent", 0.0)

    detector._tick(None)
    assert [p["type"] for p in sent] == ["honeytoken_triggered"]
    assert "login" in sent[0]["detail"]


def test_retour_au_normal_clot_l_incident(monkeypatch):
    """Retour au normal après un incident : clôture envoyée au moteur (levée
    du mode dégradé, rejeu de la file), une seule fois."""
    closed = []
    monkeypatch.setattr(detector, "_service_down", lambda c: False)
    monkeypatch.setattr(detector.sources, "honeytoken_kinds", lambda c: [])
    monkeypatch.setattr(detector.sources, "collect_features", lambda c: {})
    monkeypatch.setattr(detector._model, "score", lambda f: (False, 0.1, {}))
    monkeypatch.setattr(detector, "_close_incident", lambda c: closed.append(True))
    monkeypatch.setattr(detector, "_open_incident", "dos_flood")

    detector._tick(None)
    detector._tick(None)
    assert closed == [True]
