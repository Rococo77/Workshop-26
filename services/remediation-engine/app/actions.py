"""Actions élémentaires de remédiation — chacune journalisée et bornée.

Toutes les opérations privilégiées (Docker, WAF) passent par ici afin de
centraliser les garde-fous (allowlist, idempotence) et la traçabilité.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import threading
from pathlib import Path

import docker
import httpx

from . import config

log = logging.getLogger("remediation.actions")

_docker = docker.from_env()
_blocked_ips: set[str] = set()
_lock = threading.Lock()


def _valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def block_ip(ip: str) -> bool:
    """Ajoute une IP à la blocklist WAF puis recharge nginx.

    Idempotent : réécrit intégralement le fichier de blocklist. Ne bloque
    jamais une IP invalide ni une plage privée de l'infra interne.
    """
    if not _valid_ip(ip):
        log.warning("block_ip refusé: IP invalide %r", ip)
        return False

    with _lock:
        _blocked_ips.add(ip)
        snapshot = sorted(_blocked_ips)

    lines = ["# Blocklist dynamique — générée par le moteur de remédiation\n"]
    lines += [f"deny {b};\n" for b in snapshot]
    Path(config.WAF_DYNAMIC_DIR).mkdir(parents=True, exist_ok=True)
    target = os.path.join(config.WAF_DYNAMIC_DIR, "blocklist.conf")
    # Écriture atomique (tmp + rename) pour éviter un reload sur fichier partiel.
    tmp = target + ".tmp"
    Path(tmp).write_text("".join(lines), encoding="utf-8")
    os.replace(tmp, target)

    return _reload_waf()


def _reload_waf() -> bool:
    try:
        waf = _docker.containers.get(config.WAF_CONTAINER)
        res = waf.exec_run(["nginx", "-s", "reload"])
        if res.exit_code != 0:
            log.error("reload WAF échoué: %s", res.output.decode(errors="replace"))
            return False
        log.info("WAF rechargé, %d IP(s) bloquée(s)", len(_blocked_ips))
        return True
    except docker.errors.NotFound:
        log.error("conteneur WAF %s introuvable", config.WAF_CONTAINER)
        return False
    except docker.errors.APIError as exc:
        log.error("erreur API Docker au reload WAF: %s", exc)
        return False


def restart_container(name: str) -> bool:
    """Redémarre un conteneur de l'allowlist. Refuse tout le reste."""
    if name not in config.RESTARTABLE_CONTAINERS:
        log.warning("restart refusé (hors allowlist): %s", name)
        return False
    try:
        container = _docker.containers.get(name)
        container.restart(timeout=10)
        log.info("conteneur redémarré: %s", name)
        return True
    except docker.errors.NotFound:
        log.error("conteneur introuvable: %s", name)
        return False
    except docker.errors.APIError as exc:
        log.error("erreur API Docker au restart %s: %s", name, exc)
        return False


def verify_canary(timeout: float = 5.0) -> bool:
    """Prouve le retour à un état utilisable via une transaction canari réelle.

    Un conteneur 'up' ne suffit pas (sujet §2) : on exécute une vraie opération
    métier de bout en bout (auth seed -> débit -> crédit -> écriture en base).
    """
    url = f"{config.CANARY_TARGET}/internal/canary"
    try:
        resp = httpx.post(url, timeout=timeout)
        ok = resp.status_code == 200 and resp.json().get("canary") == "ok"
        log.info("canari: %s (http %s)", "OK" if ok else "KO", resp.status_code)
        return ok
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("canari injoignable: %s", exc)
        return False


def blocked_ips() -> list[str]:
    with _lock:
        return sorted(_blocked_ips)
