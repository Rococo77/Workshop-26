"""Actions élémentaires de remédiation — chacune journalisée et bornée.

Toutes les opérations privilégiées (Docker, WAF) passent par ici afin de
centraliser les garde-fous (allowlist, idempotence) et la traçabilité.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import threading
import time
from collections import Counter
from pathlib import Path

import docker
import httpx

from . import config

log = logging.getLogger("remediation.actions")

_docker: docker.DockerClient | None = None
_blocked_ips: set[str] = set()
_lock = threading.Lock()

# Ligne access nginx : "<ip> - - [date] \"METHOD path\" <status> ..."
_ACCESS_RE = re.compile(r'^(\d{1,3}(?:\.\d{1,3}){3})\s.*"\s*\S+ [^"]*"\s+(\d{3})')


def _client() -> docker.DockerClient:
    """Client Docker créé au premier usage : un socket indisponible au démarrage
    ne doit pas empêcher le moteur de démarrer (erreur levée à l'action, gérée)."""
    global _docker
    if _docker is None:
        _docker = docker.from_env()
    return _docker


def _valid_ip(ip: str) -> bool:
    """IP bien formée ET hors des plages protégées (infra, passerelle Docker)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not any(addr in net for net in config.PROTECTED_NETWORKS)


def block_ip(ip: str) -> bool:
    """Ajoute une IP à la blocklist WAF puis recharge nginx.

    Idempotent : réécrit intégralement le fichier de blocklist. Ne bloque
    jamais une IP invalide ni une plage protégée (config.PROTECTED_NETWORKS).
    Une IP bloquée reçoit 444 (connexion fermée) et non 403 : le trafic d'une
    source déjà confinée ne doit pas être requalifié en injection (403 = CRS).
    """
    if not _valid_ip(ip):
        log.warning("block_ip refusé: IP invalide ou protégée %r", ip)
        return False
    ip = str(ipaddress.ip_address(ip))  # forme canonique, comme $remote_addr

    with _lock:
        _blocked_ips.add(ip)
        snapshot = sorted(_blocked_ips)

    lines = ["# Blocklist dynamique — générée par le moteur de remédiation\n"]
    lines += [f'if ($remote_addr = "{b}") {{ return 444; }}\n' for b in snapshot]
    Path(config.WAF_DYNAMIC_DIR).mkdir(parents=True, exist_ok=True)
    target = os.path.join(config.WAF_DYNAMIC_DIR, "blocklist.conf")
    # Écriture atomique (tmp + rename) pour éviter un reload sur fichier partiel.
    tmp = target + ".tmp"
    Path(tmp).write_text("".join(lines), encoding="utf-8")
    os.replace(tmp, target)

    return _reload_waf()


def _reload_waf() -> bool:
    try:
        waf = _client().containers.get(config.WAF_CONTAINER)
        res = waf.exec_run(["nginx", "-s", "reload"])
        if res.exit_code != 0:
            log.error("reload WAF échoué: %s", res.output.decode(errors="replace"))
            return False
        log.info("WAF rechargé, %d IP(s) bloquée(s)", len(_blocked_ips))
        return True
    except docker.errors.NotFound:
        log.error("conteneur WAF %s introuvable", config.WAF_CONTAINER)
        return False
    except docker.errors.DockerException as exc:
        log.error("erreur API Docker au reload WAF: %s", exc)
        return False


def restart_container(name: str) -> bool:
    """Redémarre un conteneur de l'allowlist. Refuse tout le reste."""
    if name not in config.RESTARTABLE_CONTAINERS:
        log.warning("restart refusé (hors allowlist): %s", name)
        return False
    try:
        container = _client().containers.get(name)
        container.restart(timeout=10)
        log.info("conteneur redémarré: %s", name)
        return True
    except docker.errors.NotFound:
        log.error("conteneur introuvable: %s", name)
        return False
    except docker.errors.DockerException as exc:
        log.error("erreur API Docker au restart %s: %s", name, exc)
        return False


def top_attacker_ip(window_s: int = 120) -> str | None:
    """Résout l'IP attaquante en lisant directement les journaux du WAF
    (docker logs), indépendamment de la latence d'ingestion de Loki.

    On ne retient que les IP générant des rejets (403/429) : ce sont des clients
    externes malveillants, jamais les services internes. Les IP déjà bloquées
    sont ignorées, pour qu'un 2e attaquant soit résolu. Retourne la plus active.
    """
    try:
        waf = _client().containers.get(config.WAF_CONTAINER)
        raw = waf.logs(since=int(time.time()) - window_s).decode("utf-8", errors="replace")
    except docker.errors.NotFound:
        log.error("conteneur WAF introuvable pour la résolution d'IP")
        return None
    except docker.errors.DockerException as exc:
        log.error("lecture des logs WAF impossible: %s", exc)
        return None

    already = set(blocked_ips())
    counts: Counter[str] = Counter()
    for line in raw.splitlines():
        m = _ACCESS_RE.match(line)
        if m and m.group(2) in ("403", "429"):
            src = m.group(1)
            if src not in already and _valid_ip(src):
                counts[src] += 1
    if not counts:
        return None
    ip, n = counts.most_common(1)[0]
    log.info("IP attaquante résolue depuis les logs WAF: %s (%d rejets)", ip, n)
    return ip


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
