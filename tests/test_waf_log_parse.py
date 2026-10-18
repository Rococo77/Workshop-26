"""Corrélation SIEM : l'extraction de l'IP source et du statut depuis les logs
WAF conditionne le blocage de la bonne IP. On teste le parsing nginx.
"""
from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from conftest import load_module  # noqa: E402

sources = load_module("det_sources", "services/ml-detector/app/sources.py")


def test_parse_ligne_access_nginx():
    line = '192.168.137.42 - - [18/Oct/2026:10:00:00 +0000] "POST /auth/login HTTP/1.1" 403 153'
    m = sources._ACCESS_RE.match(line)
    assert m is not None
    assert m.group(1) == "192.168.137.42"
    assert m.group(2) == "403"


def test_ignore_ligne_non_access():
    assert sources._ACCESS_RE.match("ModSecurity: warning. Matched ...") is None
