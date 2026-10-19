"""Résolution de l'IP attaquante : l'extraction de l'IP et du statut depuis les
logs WAF (côté moteur de remédiation) conditionne le blocage de la bonne IP.
On teste le parsing nginx.
"""

from __future__ import annotations

import pytest

pytest.importorskip("docker")
pytest.importorskip("httpx")

from conftest import load_service_module  # noqa: E402

actions = load_service_module("rem", "services/remediation-engine", "actions")


def test_parse_ligne_access_nginx():
    line = '192.168.137.42 - - [18/Oct/2026:10:00:00 +0000] "POST /auth/login HTTP/1.1" 403 153'
    m = actions._ACCESS_RE.match(line)
    assert m is not None
    assert m.group(1) == "192.168.137.42"
    assert m.group(2) == "403"


def test_ignore_ligne_non_access():
    assert actions._ACCESS_RE.match("ModSecurity: warning. Matched ...") is None


def test_exporter_borne_le_label_method():
    """Méthode inventée par le client -> "OTHER" : cardinalité bornée."""
    pytest.importorskip("prometheus_client")
    exporter = load_service_module("wafm", "services/waf-metrics", "exporter")

    def count(method):
        return exporter.RESPONSES.labels(status="200", method=method)._value.get()

    before = count("OTHER")
    exporter._parse('1.2.3.4 - - [d] "FOOBAR / HTTP/1.1" 200 1')
    exporter._parse('1.2.3.4 - - [d] "GET / HTTP/1.1" 200 1')
    assert count("OTHER") == before + 1
    assert count("GET") == 1
    methods = {s.labels["method"] for m in exporter.RESPONSES.collect() for s in m.samples}
    assert "FOOBAR" not in methods
