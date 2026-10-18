"""Garde-fous du moteur de remédiation : le test qui protège de l'automate
qui en fait trop. Une IP invalide ne doit jamais être écrite dans la blocklist,
et seul un conteneur de l'allowlist peut être redémarré.
"""
from __future__ import annotations

import pytest

pytest.importorskip("docker")
pytest.importorskip("httpx")

from conftest import load_module  # noqa: E402

actions = load_module("rem_actions", "services/remediation-engine/app/actions.py")
config = load_module("rem_config", "services/remediation-engine/app/config.py")


def test_block_ip_refuse_ip_invalide(tmp_path, monkeypatch):
    monkeypatch.setattr(actions.config, "WAF_DYNAMIC_DIR", str(tmp_path))
    # IP malformée -> refus avant toute écriture / reload.
    assert actions.block_ip("not-an-ip") is False
    assert not (tmp_path / "blocklist.conf").exists()


def test_restart_refuse_hors_allowlist():
    assert actions.restart_container("ra-postgres") is False  # base jamais redémarrée
    assert actions.restart_container("n-importe-quoi") is False


def test_allowlist_contient_les_services_metier():
    assert "ra-payment-api" in config.RESTARTABLE_CONTAINERS
    assert "ra-postgres" not in config.RESTARTABLE_CONTAINERS
