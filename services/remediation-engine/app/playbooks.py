"""Playbooks de remédiation — orchestration des actions par type d'incident.

Principe directeur (sujet §2) : on NE confond PAS restauration de disponibilité
et traitement d'une compromission.
  - dos_flood / service_unavailable  -> rétablir le service (contenir + relancer).
  - injection_attempt                -> contenir et tracer, sans prétendre que
                                        "le service est revenu" (pas de même réponse).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import actions

log = logging.getLogger("remediation.playbooks")


@dataclass
class RemediationResult:
    incident_type: str
    steps: list[str] = field(default_factory=list)
    # Étapes horodatées : chronologie du rapport d'incident (report.py).
    timeline: list[dict] = field(default_factory=list)
    recovered: bool = False
    contained: bool = False

    def step(self, msg: str) -> None:
        log.info("[%s] %s", self.incident_type, msg)
        self.steps.append(msg)
        self.timeline.append({"ts": datetime.now(UTC).isoformat(), "msg": msg})


def _wait_recovery(result: RemediationResult, attempts: int = 6, delay: float = 2.0) -> bool:
    """Vérification active avec backoff court : la reprise est PROUVÉE, pas supposée."""
    for i in range(1, attempts + 1):
        if actions.verify_canary():
            result.step(f"transaction canari réussie (essai {i}) -> service utilisable")
            return True
        result.step(f"canari KO (essai {i}/{attempts}), nouvelle tentative")
        time.sleep(delay)
    return False


def handle_dos_flood(source_ip: str | None, service: str) -> RemediationResult:
    r = RemediationResult("dos_flood")
    # Si le détecteur n'a pas fourni d'IP, on la résout depuis les logs WAF.
    if not source_ip:
        source_ip = actions.top_attacker_ip()
    if source_ip:
        ok = actions.block_ip(source_ip)
        r.contained = ok
        r.step(f"blocage IP source {source_ip} au WAF: {'OK' if ok else 'ÉCHEC'}")
    else:
        # Sous Docker Desktop, tous les clients arrivent via la passerelle du bridge
        # (adresse protégée) : bloquer couperait tout le monde.
        r.step(
            "aucune IP attaquante attribuable (clients vus derrière la passerelle Docker)"
            " — mitigation par rate-limit WAF"
        )

    # Si l'API a saturé au point de devenir malsaine, on la relance une fois.
    container = {"payment-api": "ra-payment-api", "auth": "ra-auth"}.get(service)
    if container and not actions.verify_canary():
        if actions.restart_container(container):
            r.step(f"redémarrage {container} (saturation) effectué")

    r.recovered = _wait_recovery(r)
    return r


def handle_service_unavailable(service: str) -> RemediationResult:
    r = RemediationResult("service_unavailable")
    container = {"payment-api": "ra-payment-api", "auth": "ra-auth", "frontend": "ra-frontend"}.get(
        service, "ra-payment-api"
    )
    if actions.restart_container(container):
        r.step(f"redémarrage {container} effectué")
        r.contained = True
    else:
        r.step(f"redémarrage {container} refusé/échoué")
    r.recovered = _wait_recovery(r)
    return r


def handle_injection_attempt(source_ip: str | None) -> RemediationResult:
    """Tentative d'injection = enjeu de compromission, pas de disponibilité.
    On contient (blocage source) et on trace ; on ne 'répare' pas un service
    qui, lui, répond toujours. La preuve attendue est le confinement + le log."""
    r = RemediationResult("injection_attempt")
    if not source_ip:
        source_ip = actions.top_attacker_ip()
    if source_ip:
        ok = actions.block_ip(source_ip)
        r.contained = ok
        r.step(
            f"blocage IP source {source_ip}: {'OK' if ok else 'ÉCHEC'} "
            f"(CRS a déjà rejeté les requêtes malveillantes)"
        )
    else:
        r.step("injection confinée par le WAF/CRS ; pas d'IP isolée à bloquer")
    # Service toujours disponible : on vérifie qu'il l'est resté.
    r.recovered = actions.verify_canary()
    r.step(f"intégrité du service: canari {'OK' if r.recovered else 'KO'}")
    return r


def handle_honeytoken(source_ip: str | None) -> RemediationResult:
    """Compte leurre utilisé = la base de comptes a fuité. Enjeu de
    confidentialité : on confine la source et on trace ; la fuite elle-même
    ne se « répare » pas, elle se traite par des humains (investigation,
    rotation des secrets, notifications)."""
    r = RemediationResult("honeytoken_triggered")
    r.step("compte leurre utilisé : preuve d'une fuite de la base de comptes")
    source_ip = source_ip or actions.honeytoken_source_ip()
    if source_ip:
        ok = actions.block_ip(source_ip)
        r.step(f"blocage IP source {source_ip} au WAF: {'OK' if ok else 'ÉCHEC'}")
    else:
        r.step("source non attribuable (passerelle Docker) : blocage IP impossible")
    # Le leurre n'ouvre aucun accès (connexion et virement refusés) : confiné.
    r.contained = True
    r.recovered = actions.verify_canary()
    r.step(f"intégrité du service: canari {'OK' if r.recovered else 'KO'}")
    r.step(
        "à traiter par l'équipe : origine de la fuite, rotation des secrets (Vault), "
        "notification CNIL / autorité (DORA)"
    )
    return r


def dispatch(incident_type: str, service: str, source_ip: str | None) -> RemediationResult:
    if incident_type == "dos_flood":
        return handle_dos_flood(source_ip, service)
    if incident_type == "service_unavailable":
        return handle_service_unavailable(service)
    if incident_type == "injection_attempt":
        return handle_injection_attempt(source_ip)
    if incident_type == "honeytoken_triggered":
        return handle_honeytoken(source_ip)
    # Inconnu : aucune action privilégiée.
    r = RemediationResult(incident_type)
    r.step("type d'incident inconnu — aucune action automatique (garde-fou)")
    return r
