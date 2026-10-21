#!/usr/bin/env bash
# ============================================================================
#  Gestion des secrets avec HashiCorp Vault (sujet §3.4).
#  Vault est la source de vérité ; le .env n'est qu'un RENDU local, régénéré
#  au déploiement avec un jeton en lecture seule (politique `deploy`).
#
#  Usage :
#    scripts/vault.sh init     # 1re fois : init, descellement, KV, audit,
#                              # politique, jeton de déploiement, import du .env
#    scripts/vault.sh unseal   # après un redémarrage de Vault (il redémarre scellé)
#    scripts/vault.sh import   # .env -> Vault (après ajout/modification d'un secret)
#    scripts/vault.sh render   # Vault -> .env (jeton `deploy`, lecture seule)
#    scripts/vault.sh status
#
#  Matériel sensible local, ignoré par git (.vault/) : clé de descellement,
#  jeton racine, jeton de déploiement. Production : partage Shamir 5/3 entre
#  personnes, auto-unseal (KMS/HSM), jeton racine révoqué (docs/vault.md).
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${ROOT}/.vault"
INIT_FILE="${STATE}/init.json"
DEPLOY_TOKEN_FILE="${STATE}/deploy.token"
ENV_FILE="${ROOT}/.env"
CONTAINER="ra-vault"
KV_MOUNT="secret"
KV_PATH="resilience-alpha"

# `python` d'abord : sous Windows, `python3` est souvent l'alias du Microsoft
# Store (WindowsApps), qui ne lit pas l'entrée standard d'un pipe.
PY="$(command -v python 2>/dev/null || command -v python3)"
[ "$(printf ok | "$PY" -c 'import sys;print(sys.stdin.read())')" = ok ] \
  || { echo "Erreur : interpréteur Python incapable de lire un pipe ($PY)." >&2; exit 1; }
die() { echo "Erreur : $*" >&2; exit 1; }
json() { "$PY" -c "import json,sys;d=json.load(sys.stdin);print($1)"; }
# vault CLI dans le conteneur ; VAULT_TOKEN passé seulement si fourni.
vlt() { docker exec -i ${TOKEN:+-e VAULT_TOKEN="$TOKEN"} "$CONTAINER" vault "$@"; }

root_token() { [ -f "$INIT_FILE" ] || die "Vault non initialisé (scripts/vault.sh init)."; json "d['root_token']" < "$INIT_FILE"; }

wait_up() {
  # Conteneur existant : simple démarrage (depuis WSL/Ansible, `compose up`
  # recalculerait les chemins des bind-mounts et casserait vault.hcl sous
  # Docker Desktop). Création seulement s'il n'existe pas encore.
  if docker inspect "$CONTAINER" >/dev/null 2>&1; then
    docker start "$CONTAINER" >/dev/null
  else
    docker compose -f "${ROOT}/docker-compose.yml" up -d vault >/dev/null
  fi
  for _ in $(seq 1 30); do
    # rc 0 = descellé, 2 = scellé (mais joignable), 1 = erreur
    rc=0; docker exec "$CONTAINER" vault status >/dev/null 2>&1 || rc=$?
    [ "$rc" -ne 1 ] && return 0
    sleep 1
  done
  die "Vault ne répond pas."
}

# `vault status` sort en 2 quand Vault est scellé : on tolère ce code (pipefail).
vstatus() { docker exec "$CONTAINER" vault status -format=json 2>/dev/null || true; }
sealed() { vstatus | json "d['sealed']" | grep -q True; }

unseal() {
  wait_up
  if sealed; then
    key="$(json "d['unseal_keys_b64'][0]" < "$INIT_FILE")"
    docker exec "$CONTAINER" vault operator unseal "$key" >/dev/null
    echo "Vault descellé."
  else
    echo "Vault déjà descellé."
  fi
}

import_env() {
  [ -f "$ENV_FILE" ] || die ".env absent."
  TOKEN="$(root_token)"
  # KEY=VALUE (commentaires et lignes vides ignorés) -> JSON -> KV v2
  "$PY" - "$ENV_FILE" <<'PY' | vlt kv put -mount="$KV_MOUNT" "$KV_PATH" - >/dev/null
import json, sys
data = {}
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    data[k.strip()] = v
print(json.dumps(data))
PY
  n="$(TOKEN="$TOKEN" vlt kv get -mount="$KV_MOUNT" -format=json "$KV_PATH" | json "len(d['data']['data'])")"
  echo "${n} secrets importés dans ${KV_MOUNT}/${KV_PATH}."
}

render_env() {
  [ -f "$DEPLOY_TOKEN_FILE" ] || die "jeton de déploiement absent (scripts/vault.sh init)."
  TOKEN="$(tr -d '\r\n' < "$DEPLOY_TOKEN_FILE")"
  [ -f "$ENV_FILE" ] && cp "$ENV_FILE" "${STATE}/env.previous"
  vlt kv get -mount="$KV_MOUNT" -format=json "$KV_PATH" | "$PY" -c "
import json, sys
d = json.load(sys.stdin)['data']
data, ver = d['data'], d['metadata']['version']
with open(sys.argv[1], 'w', encoding='utf-8', newline='\n') as f:
    f.write('# GÉNÉRÉ depuis Vault (secret/%s, version %s) par scripts/vault.sh render.\n' % ('$KV_PATH', ver))
    f.write('# Ne pas éditer : modifier dans Vault (ou .env puis scripts/vault.sh import).\n')
    for k in sorted(data):
        f.write('%s=%s\n' % (k, data[k]))
print('%d secrets rendus dans .env (version %s).' % (len(data), ver))
" "$ENV_FILE"
}

init() {
  mkdir -p "$STATE"
  wait_up
  if vstatus | json "d['initialized']" | grep -q True; then
    [ -f "$INIT_FILE" ] || die "Vault déjà initialisé mais ${INIT_FILE} absent."
    echo "Vault déjà initialisé."
  else
    [ -s "$INIT_FILE" ] && die "${INIT_FILE} existe déjà : refus de l'écraser (clé de descellement)."
    # Démonstrateur : 1 part, seuil 1. Production : -key-shares=5 -key-threshold=3.
    # Écriture via un fichier temporaire : une init en échec ne doit JAMAIS
    # tronquer une clé de descellement existante.
    docker exec "$CONTAINER" vault operator init -key-shares=1 -key-threshold=1 -format=json \
      > "${INIT_FILE}.tmp"
    "$PY" -c "import json,sys;json.load(open(sys.argv[1]))['unseal_keys_b64'][0]" "${INIT_FILE}.tmp" \
      || { rm -f "${INIT_FILE}.tmp"; die "sortie de vault operator init invalide."; }
    mv "${INIT_FILE}.tmp" "$INIT_FILE"
    chmod 600 "$INIT_FILE" 2>/dev/null || true
    echo "Vault initialisé (clé de descellement et jeton racine dans .vault/init.json)."
  fi
  unseal
  TOKEN="$(root_token)"

  vlt secrets list -format=json | json "'${KV_MOUNT}/' in d" | grep -q True \
    || TOKEN="$TOKEN" vlt secrets enable -path="$KV_MOUNT" kv-v2 >/dev/null
  # Journal d'audit sur la sortie standard -> Promtail -> Loki (SIEM).
  vlt audit list -format=json 2>/dev/null | json "'file/' in d" | grep -q True \
    || TOKEN="$TOKEN" vlt audit enable file file_path=stdout >/dev/null
  vlt policy write deploy - < "${ROOT}/infra/vault/policies/deploy.hcl" >/dev/null

  if [ ! -f "$DEPLOY_TOKEN_FILE" ]; then
    vlt token create -policy=deploy -orphan -period=720h -display-name=deploy -format=json \
      | json "d['auth']['client_token']" > "$DEPLOY_TOKEN_FILE"
    chmod 600 "$DEPLOY_TOKEN_FILE" 2>/dev/null || true
  fi
  echo "KV v2, audit, politique 'deploy' et jeton de déploiement en place."
  import_env
}

status() {
  vstatus | PYTHONIOENCODING=utf-8 json "'initialisé: %s / scellé: %s / version: %s' % (d['initialized'], d['sealed'], d['version'])" \
    || echo "Vault ne répond pas."
}

case "${1:-}" in
  init) init ;;
  unseal) unseal ;;
  import) import_env ;;
  render) render_env ;;
  status) status ;;
  *) sed -n '2,18p' "$0"; exit 1 ;;
esac
