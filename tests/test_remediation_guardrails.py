"""Garde-fous du moteur de remédiation : le test qui protège de l'automate
qui en fait trop. Une IP invalide ne doit jamais être écrite dans la blocklist,
et seul un conteneur de l'allowlist peut être redémarré.
"""

from __future__ import annotations

import pytest

pytest.importorskip("docker")
pytest.importorskip("httpx")

from conftest import load_service_module  # noqa: E402

config = load_service_module("rem", "services/remediation-engine", "config")
actions = load_service_module("rem", "services/remediation-engine", "actions")


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


def test_socket_docker_indisponible_echec_propre(tmp_path, monkeypatch):
    """Régression : sans démon Docker, le moteur ne doit ni crasher à l'import
    ni lever d'exception pendant une remédiation — l'action échoue proprement."""
    monkeypatch.setenv("DOCKER_HOST", f"unix://{tmp_path}/absent.sock")
    monkeypatch.setattr(actions, "_docker", None)  # force la recréation du client
    monkeypatch.setattr(actions.config, "WAF_DYNAMIC_DIR", str(tmp_path))

    assert actions.restart_container("ra-payment-api") is False
    assert actions.block_ip("203.0.113.7") is False  # blocklist écrite, reload KO
    assert actions.top_attacker_ip() is None


def test_block_ip_refuse_plages_protegees(tmp_path, monkeypatch):
    """Passerelle du bridge Docker (= tous les clients derrière un port publié)
    et loopback : les bloquer couperait tout le monde."""
    monkeypatch.setattr(actions.config, "WAF_DYNAMIC_DIR", str(tmp_path))
    for ip in ("172.18.0.1", "127.0.0.1", "::1"):
        assert actions.block_ip(ip) is False
    assert not (tmp_path / "blocklist.conf").exists()


def test_block_ip_repond_444_et_non_403(tmp_path, monkeypatch):
    """403 = signature CRS : une IP déjà bloquée ne doit pas produire de 403,
    sinon son trafic serait requalifié en injection."""
    monkeypatch.setattr(actions.config, "WAF_DYNAMIC_DIR", str(tmp_path))
    monkeypatch.setattr(actions, "_blocked_ips", set())
    monkeypatch.setattr(actions, "_reload_waf", lambda: True)
    assert actions.block_ip("192.168.137.42") is True
    conf = (tmp_path / "blocklist.conf").read_text(encoding="utf-8")
    assert 'if ($remote_addr = "192.168.137.42") { return 444; }' in conf
    assert "deny" not in conf


def test_top_attacker_ignore_ip_deja_bloquee_et_passerelle(monkeypatch):
    from types import SimpleNamespace

    raw = "\n".join(
        [
            '192.168.137.42 - - [d] "GET / HTTP/1.1" 403 1',
            '192.168.137.42 - - [d] "GET / HTTP/1.1" 403 1',
            '172.18.0.1 - - [d] "GET / HTTP/1.1" 429 1',
            '172.18.0.1 - - [d] "GET / HTTP/1.1" 429 1',
            '192.168.137.43 - - [d] "GET / HTTP/1.1" 429 1',
        ]
    ).encode()
    waf = SimpleNamespace(logs=lambda since: raw)
    client = SimpleNamespace(containers=SimpleNamespace(get=lambda name: waf))
    monkeypatch.setattr(actions, "_client", lambda: client)
    monkeypatch.setattr(actions, "_blocked_ips", {"192.168.137.42"})
    assert actions.top_attacker_ip() == "192.168.137.43"
