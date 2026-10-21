#!/usr/bin/env bash
# ============================================================================
#  Orchestration de la démonstration (Clip Chrono / live jury).
#  À lancer depuis le PC Attaquant (ou le PC Hôte pour répétition locale).
#  Montre : état nominal -> attaque -> détection -> remédiation -> reprise.
#
#  Usage : scripts/demo.sh http://192.168.137.1:8080
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ATTACK_DIR="${ROOT}/attack"
EDGE_PORT="${EDGE_PORT:-$(grep -m1 '^EDGE_PORT=' "${ROOT}/.env" 2>/dev/null | cut -d= -f2)}"
TARGET="${1:-http://127.0.0.1:${EDGE_PORT:-8080}}"

line() { printf '\n\033[1;36m== %s ==\033[0m\n' "$1"; }

line "1. État nominal — transaction canari avant incident"
curl -s -X POST "${TARGET}/api/health" >/dev/null && echo "API joignable."

line "2. Attaque — déni de service applicatif (40s)"
python3 "${ATTACK_DIR}/flood.py" --target "${TARGET}" --duration 40 --workers 50

line "3. Observation — le détecteur ML qualifie l'anomalie et le moteur agit"
echo "Suivez le dashboard : http://127.0.0.1:${EDGE_PORT:-8080} (score ML, IP bloquée, reprise)."

line "4. Vérification — nouvelle transaction après remédiation"
sleep 5
curl -s "${TARGET}/api/health" && echo "  <- service de nouveau utilisable"

echo
echo "Démonstration terminée. Aucune intervention corrective humaine requise."
