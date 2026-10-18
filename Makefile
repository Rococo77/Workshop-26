# ============================================================================
#  PROJECT RESILIENCE-ALPHA — commandes d'exploitation
# ============================================================================
.PHONY: help env up up-ai down logs ps reset demo attack-flood attack-sqli attack-exfil \
        train test verify

TARGET ?= http://127.0.0.1:8080

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

env: ## Crée .env depuis le modèle (démo) si absent
	@test -f .env || cp .env.example .env && echo ".env prêt"

up: env ## Démarre le cœur de la plateforme (build)
	docker compose up -d --build

up-ai: env ## Démarre cœur + assistant IA (Ollama + RAG)
	docker compose --profile ai up -d --build

down: ## Arrête la plateforme
	docker compose down

reset: ## Arrête et supprime les volumes (état propre)
	docker compose down -v

logs: ## Suit les journaux
	docker compose logs -f --tail=100

ps: ## État des conteneurs
	docker compose ps

verify: ## Vérifie l'état utilisable (transaction canari)
	@curl -s -X POST http://127.0.0.1:8080/api/health >/dev/null && echo "WAF/API joignables"
	@docker exec ra-payment-api python -c "import urllib.request,json;\
print(urllib.request.urlopen(urllib.request.Request('http://localhost:8000/internal/canary',method='POST')).read().decode())"

demo: ## Joue la démonstration complète
	bash scripts/demo.sh $(TARGET)

attack-flood: ## Flood HTTP (déni de service)
	python3 attack/flood.py --target $(TARGET) --duration 40 --workers 50

attack-sqli: ## Injection SQL
	python3 attack/sqli.py --target $(TARGET) --rounds 60

attack-exfil: ## Tentative d'exfiltration
	python3 attack/exfil.py --target $(TARGET)

train: ## (Ré)entraîne et évalue le modèle de détection
	python3 ml/train.py

test: ## Lance les tests
	python3 -m pytest -q tests/
