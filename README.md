# PROJECT RESILIENCE-ALPHA

**Cyber-résilience et reprise autonome** — démonstrateur Workshop National Bac+5.

Une plateforme de paiement **fictive** et conteneurisée qui encaisse un incident
de sécurité et **retrouve son fonctionnement sans intervention humaine** :
attaque → détection (ML) → décision → remédiation → vérification (transaction
canari). Aucune donnée bancaire réelle.

---

## Démarrage rapide

```bash
cp .env.example .env            # ou scripts/secrets.sh decrypt (SOPS/age)
make up                         # démarre le cœur de la plateforme
make verify                     # vérifie l'état utilisable (canari)
# Démo de reprise autonome (depuis le PC Attaquant) :
make attack-flood TARGET=http://192.168.137.1:8080
```

- Front + dashboard : http://127.0.0.1:8080
- Grafana : http://127.0.0.1:3000

Assistant IA (optionnel, RAM) : `make up-ai`.

## Architecture (5 domaines, 1 boucle)

```
Attaque (PC Attaquant) ─▶ WAF ─▶ API/Auth ─▶ PostgreSQL
                           │         │
              logs/métriques ▼         ▼ métriques
              Prometheus / Loki ─▶ ml-detector (IsolationForest + SIEM)
                                         │ incident
                                         ▼
                           remediation-engine ─▶ block IP / restart / CANARI
                                         │
                                 dashboard React (reprise prouvée)
```

| Domaine | Composants |
|---|---|
| Développement | `payment-api`, `auth`, `frontend` (React/Tailwind), `supervision-bff` |
| Infrastructure | Docker Compose, Ansible, Prometheus/Grafana/Loki/Promtail |
| IA / Data | `ml-detector` (IsolationForest), `rag-assistant` (Ollama + LangChain) |
| Cybersécurité | WAF ModSecurity + OWASP CRS, SIEM (Loki), secrets SOPS/age |
| Gouvernance | EBIOS RM, PCA/PRA, NIS2/DORA (`docs/`) |

## Arborescence

```
services/            microservices (API, auth, front, détection, remédiation, BFF, RAG)
infra/               WAF, observabilité (Prometheus/Grafana/Loki/Promtail), Ansible
attack/              scripts Red Team (flood, sqli, exfil)
ml/                  entraînement & évaluation du modèle de détection
docs/                architecture, EBIOS RM, PCA/PRA, NIS2/DORA, runbook
tests/               tests (détection, garde-fous remédiation, parsing SIEM)
scripts/             secrets (SOPS/age), orchestration de démo
docker-compose.yml   orchestration (réseaux segmentés)
Makefile             commandes d'exploitation
```

## Principes de conception

- **Détection ML primaire** (pas de règles en dur) avec explicabilité.
- **Reprise prouvée, pas supposée** : validée par une transaction canari réelle.
- **Disponibilité ≠ compromission** : playbooks distincts (DoS vs injection).
- **Moindre privilège** : automate isolé (`control`), allowlists, pas d'UI admin
  exposée ; assistant IA en lecture seule, sans privilège.
- **Aucun secret en clair** : SOPS/age, `.env` ignoré par git.

## Documentation

- [Architecture & chaîne de résilience](docs/architecture.md)
- [Runbook (déploiement, vérification, démo)](docs/runbook.md)
- [Analyse de risques EBIOS RM](docs/ebios-rm.md)
- [PCA / PRA](docs/pca-pra.md)
- [Conformité NIS2 / DORA](docs/nis2-dora.md)
- [Scripts d'attaque](attack/README.md)

## Tests

```bash
pip install -r tests/requirements-dev.txt
make test          # détection, garde-fous de remédiation, parsing SIEM
make train         # (ré)entraîne et évalue le modèle
```

## Livrables (packaging)

Dossier de remise : `Workshop2026-M2-G<n>/` (remplacer `<n>` par le numéro
d'équipe). Ce dépôt constitue l'archive des sources `-Code.zip`. Le dossier
d'ingénierie, le support et le Clip Chrono sont produits à partir de `docs/`.
