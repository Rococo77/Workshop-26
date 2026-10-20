#!/usr/bin/env bash
# ============================================================================
#  Enrôle le visage d'une photo sur un client (existant, ou créé avec --create).
#  La photo transite par le conteneur payment-api (accès face-api + base) et y
#  est supprimée ensuite : seule l'empreinte (vecteur) est conservée en base.
#
#  Usage : scripts/enroll-face.sh <photo.jpg> <username> [options enroll_cli]
#    scripts/enroll-face.sh moi.jpg jordan --create --password 'Jordan#2026'
#    scripts/enroll-face.sh moi.jpg alice --replace
#  Options : --create --password P [--iban FR76-FAKE-0003] [--balance 2500]
#            --replace (écrase une empreinte existante)
# ============================================================================
set -euo pipefail

[ $# -ge 2 ] || { sed -n '3,12p' "$0"; exit 1; }
PHOTO="$1"; USERNAME="$2"; shift 2
[ -f "$PHOTO" ] || { echo "photo introuvable : $PHOTO" >&2; exit 1; }

CONTAINER=ra-payment-api
TMP="/tmp/enroll-$$.img"
trap 'docker exec -u root "$CONTAINER" rm -f "$TMP" >/dev/null 2>&1 || true' EXIT

docker cp "$PHOTO" "$CONTAINER:$TMP"
docker exec "$CONTAINER" python -m app.enroll_cli --username "$USERNAME" --photo "$TMP" "$@"
