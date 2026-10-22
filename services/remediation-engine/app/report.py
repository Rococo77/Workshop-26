"""Rapport d'incident automatique, au format d'une notification initiale DORA.

Construit à partir du seul journal de remédiation (horodatages des étapes,
causes transmises par le détecteur, preuve canari). Champs alignés sur le
contenu de la notification initiale d'un incident TIC majeur (DORA art. 19,
règlement délégué (UE) 2025/301, modèle du règlement d'exécution (UE) 2025/302).
Ce que le prototype ne peut pas établir seul (clients touchés, impact
financier, classification « majeur ») est marqué « à compléter ».
"""

from __future__ import annotations

from datetime import datetime

NATURE = {
    "dos_flood": "Déni de service applicatif (saturation du point d'entrée)",
    "service_unavailable": "Indisponibilité de l'API de paiement",
    "injection_attempt": "Tentative d'injection applicative (bloquée par le WAF)",
    "honeytoken_triggered": "Compte leurre utilisé : fuite de données probable",
}
# Disponibilité vs compromission (sujet §2) : la réponse attendue diffère.
CATEGORY = {
    "dos_flood": "disponibilité",
    "service_unavailable": "disponibilité",
    "injection_attempt": "intégrité / confidentialité (tentative)",
    "honeytoken_triggered": "confidentialité (compromission)",
}
TODO = "à compléter par le responsable de la notification"


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def build(event: dict) -> dict:
    """Rapport structuré à partir d'un événement du moteur (voir main.py)."""
    received = _parse(event["ts_received"])
    detected = _parse(event.get("detected_at")) or received
    proof = next((t for t in event["timeline"] if "canari réussie" in t["msg"]), None)
    recovered_at = _parse(proof["ts"]) if proof else None
    recovery_s = round((recovered_at - detected).total_seconds(), 1) if recovered_at else None

    chronology = [{"ts": detected.isoformat(), "msg": "premier point anormal (détecteur ML)"}]
    if received != detected:
        chronology.append({"ts": received.isoformat(), "msg": "incident confirmé, remédiation"})
    chronology += event["timeline"]

    return {
        "id": event["report_id"],
        "kind": "notification initiale",
        "type": event["type"],
        "nature": NATURE.get(event["type"], event["type"]),
        "category": CATEGORY.get(event["type"], "à qualifier"),
        "detected_at": detected.isoformat(),
        "recovered_at": recovered_at.isoformat() if recovered_at else None,
        "recovery_seconds": recovery_s,
        "service": event["service"],
        "source_ip": event.get("source_ip"),
        "cause": event.get("detail") or "profil anormal",
        "anomaly_score": event.get("anomaly_score"),
        "outcome": event["outcome"],
        "chronology": chronology,
        "actions": list(event["steps"]),
    }


def _hhmmss(ts: str) -> str:
    return datetime.fromisoformat(ts).strftime("%H:%M:%S")


def to_markdown(r: dict) -> str:
    duration = f"{r['recovery_seconds']} s" if r["recovery_seconds"] is not None else "non prouvée"
    outcome = {
        "recovered": "service rétabli, reprise prouvée par transaction canari",
        "contained": "menace confinée, reprise non prouvée",
        "failed": "reprise non prouvée : procédure manuelle du PRA",
    }.get(r["outcome"], r["outcome"])
    lines = [
        f"# Notification initiale d'incident TIC : {r['id']}",
        "",
        "Générée automatiquement par le moteur de remédiation (DORA art. 19).",
        "",
        "## 1. Identification",
        "",
        "| Champ | Valeur |",
        "|---|---|",
        "| Entité | Plateforme de paiement fictive RESILIENCE-ALPHA |",
        f"| Référence | {r['id']} |",
        "| Type de notification | Initiale |",
        f"| Détection | {r['detected_at'][:19].replace('T', ' ')} UTC |",
        f"| Classification « majeur » | {TODO} |",
        "",
        "## 2. Description",
        "",
        f"- Nature : {r['nature']}",
        f"- Catégorie : {r['category']}",
        f"- Service touché : {r['service']}",
        f"- Cause relevée : {r['cause']}",
        f"- Source : {r['source_ip'] or 'non attribuable (derrière la passerelle Docker)'}",
        "- Mode de découverte : détection automatique (modèle IsolationForest, Prometheus)",
        "",
        "## 3. Chronologie (heures UTC)",
        "",
        *[f"- {_hhmmss(e['ts'])} : {e['msg']}" for e in r["chronology"]],
        "",
        "## 4. Actions engagées",
        "",
        *[f"- {a}" for a in r["actions"]],
        "",
        "## 5. Impact et reprise",
        "",
        f"- Issue : {outcome}",
        f"- Temps de reprise (détection, puis canari réussi) : {duration}",
        f"- Clients touchés, impact financier, données perdues : {TODO}",
        f"- États membres concernés : {TODO}",
        "",
        "Limite : rapport factuel tiré du journal. La qualification « majeur » "
        "et l'envoi à l'autorité restent une décision humaine.",
    ]
    return "\n".join(lines) + "\n"
