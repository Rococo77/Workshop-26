#!/usr/bin/env bash
# ============================================================================
#  Démarre le cœur + l'assistant IA. Ollama tourne sur GPU NVIDIA si Docker
#  peut l'utiliser, sinon sur CPU (bascule automatique, rien à configurer).
#  Compose ne sait pas faire "GPU si disponible" : réserver un GPU absent fait
#  échouer `up`, d'où ce test préalable avec l'image Ollama elle-même.
#  Usage : scripts/up-ai.sh   (Git Bash sous Windows, Linux, make up-ai)
# ============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

files=(-f docker-compose.yml)
img=$(grep -oE 'ollama/ollama:[^[:space:]]+' docker-compose.yml)
if docker run --rm --gpus all --entrypoint true "$img" >/dev/null 2>&1; then
  echo "GPU NVIDIA utilisable par Docker : Ollama sur GPU"
  files+=(-f docker-compose.gpu.yml)
else
  echo "Aucun GPU utilisable par Docker : Ollama sur CPU"
fi
exec docker compose "${files[@]}" --profile ai up -d --build "$@"
