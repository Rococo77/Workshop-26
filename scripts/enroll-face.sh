#!/usr/bin/env bash
# ============================================================================
#  Enrôle le pool de 5 photos (droite, haut, bas, gauche, face) sur un client
#  (existant, ou créé avec --create). Les photos transitent par le conteneur
#  payment-api (accès face-api + base) et y sont supprimées ensuite : seules
#  les empreintes (vecteurs) sont conservées en base.
#
#  Usage : scripts/enroll-face.sh <username> \
#            --photo-right r.jpg --photo-up u.jpg --photo-down d.jpg \
#            --photo-left l.jpg --photo-face f.jpg [options enroll_cli]
#
#    scripts/enroll-face.sh jordan --photo-right r.jpg --photo-up u.jpg \
#      --photo-down d.jpg --photo-left l.jpg --photo-face f.jpg \
#      --create --password 'Jordan#2026' --consent
#    scripts/enroll-face.sh jordan --photo-right r.jpg --photo-up u.jpg \
#      --photo-down d.jpg --photo-left l.jpg --photo-face f.jpg --replace
#
#  Options (transmises à enroll_cli) :
#    --create --password P --consent [--iban FR76-FAKE-0003] [--balance 2500]
#    --replace (écrase le pool d'empreintes existant)
# ============================================================================
set -euo pipefail

[ $# -ge 1 ] || { sed -n '3,19p' "$0"; exit 1; }
USERNAME="$1"; shift

CONTAINER=ra-payment-api
POSES=(right up down left face)
declare -A LOCAL_PHOTO
FORWARD_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --photo-right|--photo-up|--photo-down|--photo-left|--photo-face)
      LOCAL_PHOTO["${1#--photo-}"]="$2"
      shift 2
      ;;
    *)
      FORWARD_ARGS+=("$1")
      shift
      ;;
  esac
done

for pose in "${POSES[@]}"; do
  [ -n "${LOCAL_PHOTO[$pose]:-}" ] || { echo "--photo-$pose manquant" >&2; exit 1; }
  [ -f "${LOCAL_PHOTO[$pose]}" ] || { echo "photo introuvable : ${LOCAL_PHOTO[$pose]}" >&2; exit 1; }
done

cleanup() {
  for pose in "${POSES[@]}"; do
    docker exec -u root "$CONTAINER" rm -f "/tmp/enroll-$$-$pose.img" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

TMP_ARGS=()
for pose in "${POSES[@]}"; do
  tmp="/tmp/enroll-$$-$pose.img"
  docker cp "${LOCAL_PHOTO[$pose]}" "$CONTAINER:$tmp"
  TMP_ARGS+=("--photo-$pose" "$tmp")
done

docker exec "$CONTAINER" python -m app.enroll_cli --username "$USERNAME" "${TMP_ARGS[@]}" "${FORWARD_ARGS[@]}"
