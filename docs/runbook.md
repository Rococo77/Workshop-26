# Runbook — déploiement, vérification, démonstration

> Procédure opérationnelle. Sert aussi de corpus à l'assistant RAG.

## 1. Prérequis (PC Hôte)

- Windows 10/11 + Docker Desktop (WSL2), ou Linux + Docker Engine.
- Docker Compose v2, 16 Go RAM (32 Go recommandé si profil IA sur le même poste).
- Python 3 (pour les scripts d'attaque et d'entraînement ML).
- Ports publiés : `8080` (WAF = front + API), `3000` (Grafana).

## 2. Déploiement

### Option A — Make (rapide)
```bash
make up          # cœur (sans IA)
make up-ai       # cœur + assistant IA (Ollama + RAG)
make ps          # état des conteneurs
```

### Option B — Docker Compose
```bash
cp .env.example .env         # ou : scripts/secrets.sh decrypt (SOPS/age)
docker compose up -d --build
docker compose --profile ai up -d --build   # avec IA
```

### Option C — Ansible (reproductible)
```bash
cd infra/ansible
ansible-playbook deploy.yml                  # cœur
ansible-playbook deploy.yml -e with_ai=true  # + IA (pull des modèles Ollama)
```

## 3. Secrets

```bash
scripts/secrets.sh init      # génère la clé age (une fois) ; MAJ .sops.yaml
# éditer .env puis :
scripts/secrets.sh encrypt   # .env -> secrets.enc.env (versionnable)
scripts/secrets.sh decrypt   # secrets.enc.env -> .env (local)
```
`age.key` et `.env` ne sont **jamais** versionnés (cf. `.gitignore`).

## 4. Vérification de l'état utilisable

```bash
curl -s http://127.0.0.1:8080/api/ready        # 200 = base joignable
make verify                                     # transaction canari
```
Interfaces :
- Front + dashboard : http://127.0.0.1:8080
- Grafana : http://127.0.0.1:3000 (admin / cf. `.env`)

Comptes de démonstration (fictifs) : `alice`/`Alice#2026`, `bob`/`Bob#2026`,
`operator`/`Operator#2026`, `admin`/`Admin#2026`.

## 5. Démonstration de reprise autonome

Depuis le **PC Attaquant** (cible = IP du WAF sur le PA du groupe) :

```bash
# Scénario principal : déni de service applicatif
python3 attack/flood.py --target http://192.168.137.1:8080 --duration 40 --workers 50
```

Observer dans le dashboard (http://192.168.137.1:8080) et Grafana :
1. le score d'anomalie ML monte ;
2. un incident `dos_flood` est émis puis traité ;
3. l'IP attaquante apparaît dans « IP bloquées » ;
4. la transaction canari repasse OK → une nouvelle transaction réussit.

Aucune intervention humaine entre l'attaque et la reprise.

Autres scénarios : `attack/sqli.py`, `attack/exfil.py` (voir `attack/README.md`).

## 6. Chaos engineering (répétition jeudi)

Provoquer une panne pour valider le playbook `service_unavailable` :
```bash
docker kill ra-payment-api     # le détecteur voit up==0 -> restart auto -> canari
```

## 7. Dépannage

| Symptôme | Cause probable | Action |
|----------|----------------|--------|
| `api/ready` en 503 | Postgres pas encore prêt | attendre le healthcheck, `docker compose logs postgres` |
| Pas de détection | Loki/Prometheus pas scrapés | `docker compose logs ml-detector`, vérifier `/metrics` |
| WAF ne bloque pas | reload échoué | `docker logs ra-remediation`, vérifier le volume `waf-dynamic` |
| RAG en 503 | Ollama absent / modèle non pull | `make up-ai`, `docker exec ra-ollama ollama pull llama3.2:3b` |
| Front inaccessible | Vite pas démarré | `docker compose logs frontend` |

## 8. Arrêt / remise à zéro

```bash
make down     # arrêt
make reset    # arrêt + suppression des volumes (état propre)
```
