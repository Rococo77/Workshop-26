#!/usr/bin/env bash
# ============================================================================
#  Flash de l'indicateur LED ESP8266 (firmware/face-led) depuis le PC Hôte.
#  Source unique de configuration : le .env du dépôt. Le script génère
#  include/secrets.h (ignoré par git), compile et flashe la carte branchée.
#
#  Variables lues dans .env :
#    ESP_WIFI_SSID / ESP_WIFI_PASSWORD  réseau 2,4 GHz que rejoint l'ESP8266
#    ESP_EVENTS_TOKEN                   jeton du WebSocket /api/ws/face-events
#    EDGE_PORT                          port publié du WAF (8080 par défaut)
#    ESP_WS_HOST     (optionnel)        IP du PC Hôte ; défaut : détectée
#    ESP_SERIAL_PORT (optionnel)        ex. COM8 ; défaut : carte CH340 détectée
#
#  Usage : scripts/flash-esp.sh            # génère, compile, flashe
#          scripts/flash-esp.sh --build-only
#  À lancer côté Windows (Git Bash) : WSL n'a pas accès aux ports série USB.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FW="${ROOT}/firmware/face-led"
BUILD_ONLY=false
[ "${1:-}" = "--build-only" ] && BUILD_ONLY=true

# Variable d'environnement d'abord (surcharge ponctuelle), sinon .env.
env_get() {
  if [ -n "${!1:-}" ]; then printf '%s' "${!1}"; return; fi
  grep -m1 -E "^$1=" "${ROOT}/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true
}

PIO="$(command -v pio || true)"
[ -z "$PIO" ] && [ -x "$HOME/.platformio/penv/Scripts/pio.exe" ] && PIO="$HOME/.platformio/penv/Scripts/pio.exe"
[ -z "$PIO" ] && { echo "PlatformIO (pio) introuvable." >&2; exit 1; }

SSID="$(env_get ESP_WIFI_SSID)"
PASS="$(env_get ESP_WIFI_PASSWORD)"
TOKEN="$(env_get ESP_EVENTS_TOKEN)"
PORT="$(env_get EDGE_PORT)"; PORT="${PORT:-8080}"
HOST="$(env_get ESP_WS_HOST)"

# IP du PC Hôte : celle de l'interface qui porte la route par défaut.
if [ -z "$HOST" ]; then
  HOST="$(powershell -NoProfile -Command \
    "(Get-NetIPConfiguration | Where-Object { \$_.IPv4DefaultGateway } | Select-Object -First 1).IPv4Address.IPAddress" \
    2>/dev/null | tr -d '\r')"
fi

missing=()
[ -z "$SSID" ] && missing+=(ESP_WIFI_SSID)
[ -z "$PASS" ] && missing+=(ESP_WIFI_PASSWORD)
[ -z "$TOKEN" ] && missing+=(ESP_EVENTS_TOKEN)
[ -z "$HOST" ] && missing+=(ESP_WS_HOST)
if [ ${#missing[@]} -gt 0 ]; then
  echo "À renseigner dans .env : ${missing[*]}" >&2
  exit 1
fi

# secrets.h généré en Python : échappement C correct des guillemets/antislash.
SSID="$SSID" PASS="$PASS" TOKEN="$TOKEN" HOST="$HOST" PORT="$PORT" python - "${FW}/include/secrets.h" <<'PY'
import json, os, sys
q = json.dumps  # chaîne C valide pour de l'ASCII imprimable
e = os.environ
body = f"""// GÉNÉRÉ par scripts/flash-esp.sh depuis le .env — ne pas éditer, ne pas committer.
#pragma once

#define WIFI_SSID {q(e['SSID'])}
#define WIFI_PASSWORD {q(e['PASS'])}

#define WS_HOST {q(e['HOST'])}
#define WS_PORT {int(e['PORT'])}

#define WS_TOKEN {q(e['TOKEN'])}
"""
open(sys.argv[1], "w", encoding="utf-8").write(body)
PY
echo "secrets.h généré (Wi-Fi « ${SSID} », serveur ${HOST}:${PORT})."

cd "$FW"
"$PIO" run

$BUILD_ONLY && { echo "Compilation OK (--build-only : pas de flash)."; exit 0; }

SERIAL="$(env_get ESP_SERIAL_PORT)"
if [ -z "$SERIAL" ]; then
  SERIAL="$(powershell -NoProfile -Command \
    "Get-CimInstance Win32_PnPEntity | Where-Object { \$_.Name -match 'CH340|CP210|USB-SERIAL' -and \$_.Name -match '\((COM\d+)\)' } | ForEach-Object { \$Matches[1] } | Select-Object -First 1" \
    2>/dev/null | tr -d '\r')"
fi
[ -z "$SERIAL" ] && { echo "Aucune carte ESP8266 (CH340/CP210x) détectée. Brancher la carte ou définir ESP_SERIAL_PORT." >&2; exit 1; }

echo "Flash sur ${SERIAL}..."
"$PIO" run -t upload --upload-port "$SERIAL"
echo "Flash terminé. Logs : \"$PIO\" device monitor -p ${SERIAL} -b 115200"
