"""Rapport d'incident automatique : chronologie depuis le premier point
anormal, temps de reprise jusqu'au canari réussi, champs non prouvables
laissés « à compléter » (la qualification « majeur » reste humaine)."""

from __future__ import annotations

from conftest import load_service_module

report = load_service_module("rem", "services/remediation-engine", "report")

EVENT = {
    "report_id": "INC-20261022-101530-dos_flood",
    "ts_received": "2026-10-22T10:15:30+00:00",
    "detected_at": "2026-10-22T10:15:20+00:00",
    "type": "dos_flood",
    "service": "payment-api",
    "source_ip": "192.168.137.42",
    "anomaly_score": 0.91,
    "detail": "features anormales: req_rate, waf_block_rate",
    "timeline": [
        {"ts": "2026-10-22T10:15:31+00:00", "msg": "blocage IP source 192.168.137.42 au WAF: OK"},
        {"ts": "2026-10-22T10:15:42+00:00", "msg": "transaction canari réussie (essai 1)"},
    ],
    "outcome": "recovered",
}
EVENT["steps"] = [t["msg"] for t in EVENT["timeline"]]


def test_temps_de_reprise_depuis_la_detection():
    r = report.build(EVENT)
    assert r["recovery_seconds"] == 22.0  # 10:15:20 -> 10:15:42
    assert r["chronology"][0]["msg"].startswith("premier point anormal")
    assert len(r["chronology"]) == 4  # détection, confirmation, 2 étapes


def test_reprise_non_prouvee_sans_canari():
    ev = {**EVENT, "outcome": "failed", "timeline": EVENT["timeline"][:1]}
    r = report.build(ev)
    assert r["recovery_seconds"] is None
    assert "non prouvée" in report.to_markdown(r)


def test_markdown_format_notification_initiale():
    md = report.to_markdown(report.build(EVENT))
    assert "Notification initiale" in md
    assert "192.168.137.42" in md
    assert "10:15:42 : transaction canari réussie" in md
    assert "à compléter" in md  # classification « majeur » : décision humaine


def test_compromission_sans_temps_de_reprise():
    """Fuite de données : le service n'est pas tombé, le rapport ne parle pas
    de « reprise » mais de compromission à traiter."""
    ev = {**EVENT, "type": "honeytoken_triggered", "timeline": EVENT["timeline"][:1]}
    md = report.to_markdown(report.build(ev))
    assert "sans objet (service resté disponible)" in md
    assert "compromission à traiter" in md
