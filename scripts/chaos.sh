#!/usr/bin/env bash
# ============================================================================
#  Scénario catastrophe (chaos engineering) — sujet §6 JEUDI.
#  Les TROIS vecteurs d'attaque frappent la plateforme EN MÊME TEMPS :
#    - déni de service applicatif (flood.py)
#    - injection SQL          (sqli.py)
#    - tentative d'exfiltration (exfil.py, rejoué en boucle)
#  On observe en direct que le système se détecte, qualifie, remédie et
#  prouve sa reprise par une transaction canari — sans intervention humaine.
#
#  PC Hôte = PC Red Team (répétition locale) : cible = http://127.0.0.1:8080
#  Démo réelle depuis le PC Attaquant : scripts/chaos.sh http://192.168.137.1:8080
# ============================================================================
set -uo pipefail

TARGET="${1:-http://127.0.0.1:8080}"
DURATION="${2:-45}"
ATTACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../attack" && pwd)"

c()   { printf '\033[%sm%s\033[0m' "$1" "$2"; }
line(){ printf '\n%s\n' "$(c '1;36' "== $1 ==")"; }

# --- Lecteurs d'état (réseaux internes : on passe par docker exec, urllib) ---
canary() {
  docker exec ra-payment-api python -c \
    "import urllib.request,json;r=urllib.request.urlopen(urllib.request.Request('http://localhost:8000/internal/canary',method='POST'),timeout=5);print(json.load(r).get('canary','?'))" 2>/dev/null || echo "KO"
}
detector() {  # -> "score decision"
  docker exec ra-ml-detector python -c \
    "import urllib.request,json;d=json.load(urllib.request.urlopen('http://localhost:9100/state',timeout=4));print(d.get('last_score','?'),d.get('last_decision','?'))" 2>/dev/null || echo "? ?"
}
remediation() {  # -> "<nb_events> <dernier_playbook>:<issue> | ips=<n>"
  docker exec ra-remediation python -c \
    "import urllib.request,json;d=json.load(urllib.request.urlopen('http://localhost:9000/status',timeout=4));e=d.get('events',[]);last=e[0] if e else {};print(len(e), (last.get('type','-')+':'+last.get('outcome','-')), '| ips='+str(len(d.get('blocked_ips',[]))))" 2>/dev/null || echo "0 - | ips=0"
}
pub_status() {  # pastille client publique
  curl -s --max-time 4 "${TARGET}/supervision/status" | grep -o '"ok":[a-z]*' || echo '"ok":?'
}

# ----------------------------------------------------------------------------
line "0. État nominal (avant l'incident)"
printf "   canari          : %s\n"  "$(c '1;32' "$(canary)")"
printf "   statut public   : %s\n"  "$(pub_status)"
printf "   cible           : %s\n"  "$TARGET"

line "1. ATTAQUE SIMULTANÉE — flood + injection + exfiltration (${DURATION}s)"
SQLI_ROUNDS=$(( DURATION * 5 ))          # ~0.2s / round -> couvre la fenêtre
python3 "${ATTACK_DIR}/flood.py" --target "$TARGET" --duration "$DURATION" --workers 50 >/dev/null 2>&1 &
PID_FLOOD=$!
python3 "${ATTACK_DIR}/sqli.py"  --target "$TARGET" --rounds "$SQLI_ROUNDS"      >/dev/null 2>&1 &
PID_SQLI=$!
( end=$(( $(date +%s) + DURATION )); while [ "$(date +%s)" -lt "$end" ]; do \
    python3 "${ATTACK_DIR}/exfil.py" --target "$TARGET" >/dev/null 2>&1; sleep 1; done ) &
PID_EXFIL=$!
printf "   lancés : flood(pid %s) · sqli(pid %s) · exfil(pid %s)\n" "$PID_FLOOD" "$PID_SQLI" "$PID_EXFIL"

line "2. Observation en direct (détection -> décision -> remédiation -> canari)"
printf "   %-8s %-7s %-20s %-28s %-10s %s\n" "t(s)" "score" "décision ML" "remédiation" "canari" "public"
t0=$(date +%s); detected_at=""; proof_at=""
# On observe pendant l'attaque + ~40s de marge pour la reprise.
while :; do
  now=$(date +%s); t=$(( now - t0 ))
  read -r score decision <<<"$(detector)"
  rem="$(remediation)"; can="$(canary)"; pub="$(pub_status)"
  [ -z "$detected_at" ] && [ "$decision" != "normal" ] && [ "$decision" != "?" ] && detected_at=$t
  [ -z "$proof_at" ] && [ -n "$detected_at" ] && echo "$rem" | grep -q "recovered" && proof_at=$t
  printf "   %-8s %-7s %-20s %-28s %-10s %s\n" "$t" "$score" "$decision" "$rem" "$can" "$pub"
  # fin : attaques terminées ET reprise prouvée (canari ok + public ok)
  if ! kill -0 "$PID_FLOOD" 2>/dev/null && ! kill -0 "$PID_EXFIL" 2>/dev/null; then
    [ "$can" = "ok" ] && echo "$pub" | grep -q 'true' && break
  fi
  [ "$t" -gt $(( DURATION + 60 )) ] && break
  sleep 2
done

wait "$PID_FLOOD" "$PID_SQLI" "$PID_EXFIL" 2>/dev/null

line "3. Bilan"
printf "   canari final    : %s\n" "$(c '1;32' "$(canary)")"
printf "   statut public   : %s\n" "$(pub_status)"
printf "   remédiation     : %s\n" "$(remediation)"
[ -n "$detected_at" ] && printf "   détection à     : t+%ss\n" "$detected_at"
[ -n "$proof_at" ]    && printf "   reprise prouvée : t+%ss (canari OK après remédiation)\n" "$proof_at"
echo
echo "$(c '1;32' 'Scénario catastrophe terminé — reprise autonome, aucune intervention humaine.')"
