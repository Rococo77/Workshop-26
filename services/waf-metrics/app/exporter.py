"""Micro-exporter : journaux d'accès du WAF -> métriques Prometheus.

Transforme les lignes du log nginx (format combined) en compteurs par code de
statut, exposés sur :4040/metrics. Donne au détecteur un signal temps réel et
fiable (taux de requêtes entrantes, taux de blocage 403/429), indépendant de la
latence d'ingestion de Loki, et NON dampé par le rate-limiting (le WAF journalise
aussi ce qu'il rejette).

Volontairement maison (une quarantaine de lignes, prometheus_client déjà utilisé)
plutôt qu'une image tierce : contrôle total, testable, aucune dépendance externe.
"""

from __future__ import annotations

import logging
import os
import re
import time

from prometheus_client import Counter, start_http_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("waf-metrics")

LOG_FILE = os.getenv("WAF_ACCESS_LOG", "/var/log/nginx/ra_access.log")
PORT = int(os.getenv("EXPORTER_PORT", "4040"))
# Plafond du journal fichier (pas de logrotate dans le WAF) : au-delà, l'exporter
# le tronque. Sûr : nginx écrit en O_APPEND et repart à 0 après troncature.
MAX_LOG_BYTES = int(os.getenv("WAF_LOG_MAX_BYTES", str(50 * 1024 * 1024)))

# Le verbe vient du client : sans liste fermée, un attaquant crée une série
# Prometheus par méthode inventée (cardinalité non bornée = DoS du pipeline).
_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})

# Nom de métrique aligné sur les requêtes du détecteur.
RESPONSES = Counter(
    "nginx_http_response_count_total", "Réponses WAF par statut", ["status", "method"]
)

# "<ip> - <user> [date] \"METHOD path proto\" <status> ..."
_LINE = re.compile(r'^\S+ \S+ \S+ \[[^\]]*\] "([A-Z]+) [^"]*" (\d{3})')


def _parse(line: str) -> None:
    m = _LINE.match(line)
    if m:
        method = m.group(1) if m.group(1) in _METHODS else "OTHER"
        RESPONSES.labels(status=m.group(2), method=method).inc()


def _follow(path: str):
    """Suit le fichier (comme tail -F) en tolérant son absence et sa rotation."""
    cap = MAX_LOG_BYTES
    while True:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                f.seek(0, os.SEEK_END)  # on ne compte que le trafic live
                inode = os.fstat(f.fileno()).st_ino
                log.info("suivi du journal %s", path)
                while True:
                    line = f.readline()
                    if line:
                        yield line
                        continue
                    time.sleep(0.2)
                    if f.tell() > cap:
                        try:
                            os.truncate(path, 0)  # rattrapé par la détection ci-dessous
                        except OSError as exc:
                            # Volume créé avant le journal en 0666 : on continue sans plafond.
                            log.warning("troncature du journal impossible: %s", exc)
                            cap = float("inf")
                    # Détection de rotation / troncature -> réouverture.
                    try:
                        if os.stat(path).st_ino != inode or os.stat(path).st_size < f.tell():
                            break
                    except FileNotFoundError:
                        break
        except FileNotFoundError:
            time.sleep(1)  # le WAF n'a pas encore créé le fichier


def main() -> None:
    start_http_server(PORT)
    log.info("exporter WAF démarré sur :%d", PORT)
    for line in _follow(LOG_FILE):
        _parse(line)


if __name__ == "__main__":
    main()
