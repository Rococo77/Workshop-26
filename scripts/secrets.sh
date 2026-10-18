#!/usr/bin/env bash
# ============================================================================
#  Gestion des secrets avec SOPS + age (aucun secret en clair dans le dépôt).
#  Le fichier chiffré `secrets.enc.env` PEUT être versionné ; la clé privée age
#  (age.key) NE l'est JAMAIS (voir .gitignore).
#
#  Prérequis : sops, age  (https://github.com/getsops/sops , https://github.com/FiloSottile/age)
#
#  Usage :
#    scripts/secrets.sh init      # génère la clé age (une fois)
#    scripts/secrets.sh encrypt   # .env           -> secrets.enc.env (chiffré)
#    scripts/secrets.sh decrypt   # secrets.enc.env -> .env (local, ignoré par git)
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY_FILE="${ROOT}/age.key"
ENC_FILE="${ROOT}/secrets.enc.env"
PLAIN_FILE="${ROOT}/.env"

require() { command -v "$1" >/dev/null 2>&1 || { echo "Erreur : '$1' introuvable." >&2; exit 1; }; }

cmd="${1:-}"
case "$cmd" in
  init)
    require age-keygen
    if [[ -f "$KEY_FILE" ]]; then echo "age.key existe déjà."; exit 0; fi
    age-keygen -o "$KEY_FILE"
    pub="$(grep 'public key:' "$KEY_FILE" | awk '{print $NF}')"
    echo "Clé générée. Clé publique : $pub"
    echo "Ajoutez-la dans .sops.yaml (creation_rules.age)."
    ;;
  encrypt)
    require sops
    [[ -f "$PLAIN_FILE" ]] || { echo "Erreur : .env absent." >&2; exit 1; }
    SOPS_AGE_KEY_FILE="$KEY_FILE" sops --encrypt --input-type dotenv --output-type dotenv \
      "$PLAIN_FILE" > "$ENC_FILE"
    echo "Chiffré -> $ENC_FILE (versionnable)."
    ;;
  decrypt)
    require sops
    if [[ ! -f "$ENC_FILE" ]]; then
      echo "secrets.enc.env absent : repli sur .env.example (DÉMO UNIQUEMENT)." >&2
      [[ -f "$PLAIN_FILE" ]] || cp "${ROOT}/.env.example" "$PLAIN_FILE"
      exit 0
    fi
    SOPS_AGE_KEY_FILE="$KEY_FILE" sops --decrypt --input-type dotenv --output-type dotenv \
      "$ENC_FILE" > "$PLAIN_FILE"
    echo "Déchiffré -> $PLAIN_FILE (ignoré par git)."
    ;;
  *)
    echo "Usage : $0 {init|encrypt|decrypt}" >&2
    exit 1
    ;;
esac
