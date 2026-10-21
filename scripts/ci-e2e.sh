#!/usr/bin/env bash
# ============================================================================
#  Test end-to-end de la chaîne de cyber-résilience.
#  Démarre le cœur de la plateforme, rejoue une attaque, et VÉRIFIE que la
#  reprise est autonome : détection -> remédiation -> transaction canari.
#  Exit != 0 si la chaîne ne boucle pas -> fait échouer la CI.
#
#  Utilisable en local comme en CI (GitHub Actions). N'utilise PAS le profil IA.
#  Usage : scripts/ci-e2e.sh
# ============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
EDGE_PORT="${EDGE_PORT:-$(grep -m1 '^EDGE_PORT=' "${ROOT}/.env" 2>/dev/null | cut -d= -f2)}"
BASE="http://127.0.0.1:${EDGE_PORT:-8080}"
FAIL=0

log()  { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
ok()   { printf '  \033[32mOK\033[0m  %s\n' "$*"; }
ko()   { printf '  \033[31mKO\033[0m  %s\n' "$*"; FAIL=1; }

cleanup() {
  if [ "$FAIL" != "0" ]; then
    log "Échec — journaux des composants clés"
    docker compose ps || true
    for c in ra-waf ra-payment-api ra-ml-detector ra-remediation ra-waf-metrics; do
      echo "---- logs $c ----"; docker logs "$c" --tail 40 2>&1 || true
    done
  fi
  # Compte de test créé par l'auto-inscription (voir plus bas) : jamais de
  # données résiduelles, même en local où la stack/les volumes sont préservés.
  docker exec ra-postgres psql -U payuser -d paymentdb -c \
    "DELETE FROM app_user WHERE username = 'alice'" >/dev/null 2>&1 || true
  rm -f "${TMP_REGISTER_JSON:-}" "${TMP_FACE_JSON:-}"
  # Volumes supprimés en CI uniquement : en local, on préserve les données
  # (Postgres, Grafana, modèle Ollama) et la stack reste démarrée.
  if [ -n "${CI:-}" ]; then
    docker compose --profile ai down -v >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

[ -f .env ] || cp .env.example .env

log "Démarrage du cœur de la plateforme"
docker compose up -d --build || { ko "docker compose up"; exit 1; }

log "Attente de la disponibilité (/api/ready)"
ready=0
for _ in $(seq 1 60); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/ready")" = "200" ]; then
    ready=1; ok "API prête"; break
  fi
  sleep 5
done
[ "$ready" = "1" ] || { ko "API jamais prête"; exit 1; }

log "Auto-inscription — mot de passe + visage (photo de test)"
TMP_REGISTER_JSON="$(mktemp)"
python3 - "$TMP_REGISTER_JSON" <<'PY'
import base64, json, sys
img = base64.b64encode(open("tests/fixtures/sample-face.jpg", "rb").read()).decode()
json.dump({"username": "alice", "password": "Alice#2026", "image": img}, open(sys.argv[1], "w"))
PY
REG_BODY=$(curl -s -X POST "$BASE/api/auth/register" -H 'Content-Type: application/json' \
  --data-binary @"$TMP_REGISTER_JSON")
REG_TOKEN=$(echo "$REG_BODY" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)
[ -n "$REG_TOKEN" ] && ok "auto-inscription (mot de passe + visage)" || ko "auto-inscription : $REG_BODY"

log "Connexion — mot de passe puis second facteur (même photo, déterministe)"
LOGIN_BODY=$(curl -s -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"Alice#2026"}')
PENDING=$(echo "$LOGIN_BODY" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("pending_token") or "")' 2>/dev/null)
[ -n "$PENDING" ] && ok "login (mot de passe) -> second facteur requis" || ko "login : $LOGIN_BODY"

TMP_FACE_JSON="$(mktemp)"
python3 - "$TMP_FACE_JSON" <<'PY'
import base64, json, sys
img = base64.b64encode(open("tests/fixtures/sample-face.jpg", "rb").read()).decode()
json.dump({"image": img}, open(sys.argv[1], "w"))
PY
FACE_BODY=$(curl -s -X POST "$BASE/api/auth/login/face" -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $PENDING" --data-binary @"$TMP_FACE_JSON")
TOKEN=$(echo "$FACE_BODY" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)
[ -n "$TOKEN" ] && ok "login (second facteur visage)" || ko "login/face : $FACE_BODY"

log "État nominal — transaction canari"
canary() {
  docker exec ra-payment-api python -c \
    "import urllib.request,json;r=urllib.request.urlopen(urllib.request.Request('http://localhost:8000/internal/canary',method='POST'),timeout=5);print(json.load(r).get('canary'))" 2>/dev/null
}
[ "$(canary)" = "ok" ] && ok "canari avant incident" || ko "canari avant incident"

log "Attaque — déni de service applicatif (25s)"
python3 attack/flood.py --target "$BASE" --duration 25 --workers 40 >/dev/null 2>&1 &
FLOOD=$!

log "Attente de la détection + remédiation autonome"
recovered=0
for _ in $(seq 1 18); do
  sleep 5
  out=$(docker exec ra-remediation python -c \
    "import httpx,json;d=httpx.get('http://localhost:9000/status',timeout=5).json();\
print(json.dumps({'rec':any(e.get('recovered') for e in d['events']),\
'types':[e['type'] for e in d['events'][:3]],'ips':d['blocked_ips']}))" 2>/dev/null)
  echo "    remédiation: ${out:-<indisponible>}"
  if echo "$out" | grep -q '"rec": true'; then recovered=1; break; fi
done
wait "$FLOOD" 2>/dev/null || true

[ "$recovered" = "1" ] && ok "reprise autonome prouvée (canari côté moteur)" \
  || ko "aucune reprise autonome détectée"

log "Après remédiation — le service est de nouveau utilisable"
[ "$(canary)" = "ok" ] && ok "canari après remédiation" || ko "canari après remédiation"

log "Résultat"
if [ "$FAIL" = "0" ]; then
  echo "  Chaîne de résilience validée de bout en bout."
else
  echo "  Chaîne de résilience NON validée."
fi
exit "$FAIL"
