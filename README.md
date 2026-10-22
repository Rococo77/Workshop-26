# PROJECT RESILIENCE-ALPHA

**Cyber-résilience et reprise autonome** — démonstrateur Workshop National Bac+5.

Une plateforme de paiement **fictive** et conteneurisée qui encaisse un incident
de sécurité et **retrouve son fonctionnement sans intervention humaine** :
attaque → détection (ML) → décision → remédiation → vérification (transaction
canari). Aucune donnée bancaire réelle.

---

## Prérequis (PC Hôte)

- **Windows 10/11 + Docker Desktop (WSL2)** — ou Linux + Docker Engine.
- **Docker Compose v2** (inclus dans Docker Desktop).
- **Python 3** pour les scripts d'attaque et l'entraînement ML (bibliothèque
  standard uniquement côté attaque).
- **WSL2 (Ubuntu)** requis uniquement pour **Ansible** et les scripts `.sh`
  (`scripts/vault.sh`, `scripts/demo.sh`). La voie `docker compose` ci-dessous
  fonctionne telle quelle dans **PowerShell**, sans WSL.

## Démarrage rapide (`docker compose` — PowerShell ou bash)

```bash
copy .env.example .env          # PowerShell : copy ; bash : cp
docker compose up -d --build    # démarre le cœur de la plateforme
docker compose ps               # état des conteneurs

# Vérifier l'état utilisable (transaction canari)
curl http://127.0.0.1:8080/api/ready

# Démo de reprise autonome, depuis le PC Attaquant :
python attack/flood.py --target http://192.168.137.1:8080 --duration 40 --workers 50
```

- Front + dashboard : http://127.0.0.1:8080
- Grafana : http://127.0.0.1:3000/d/resilience-overview
- Vault (local uniquement) : http://127.0.0.1:8201

Scénario catastrophe (les 3 attaques en même temps, reprise suivie en direct) :
`scripts/chaos.sh` — voir [runbook §6](docs/runbook.md).

Base créée avant les migrations 03 à 06 : les rejouer à la main
([runbook §4](docs/runbook.md#mise-à-niveau-dune-base-existante-migrations-03-à-06)).

Assistant IA (optionnel) : `scripts/up-ai.sh` (Ollama sur GPU NVIDIA si disponible, sinon CPU).

> **Raccourcis `make` (optionnels, sous WSL/Linux/macOS).** Un `Makefile`
> enveloppe ces commandes pour plus de concision : `make up`, `make verify`,
> `make up-ai`, `make attack-flood TARGET=...`, `make test`, `make train`
> (`make help` pour la liste). Make n'est pas installé par défaut sous Windows ;
> les commandes `docker compose` ci-dessus sont la voie de référence.

## Architecture (5 domaines, 1 boucle)

```
Attaque (PC Attaquant) ─▶ WAF ─▶ API/Auth ─▶ PostgreSQL
                           │         │
              logs/métriques ▼         ▼ métriques
              Prometheus / Loki ─▶ ml-detector (IsolationForest + SIEM + comptes leurres)
                                         │ incident / clôture
                                         ▼
                           remediation-engine ─▶ block IP / restart / CANARI
                                         │        mode dégradé (virements en file)
                                         ▼
                 dashboard React (reprise prouvée, rapport d'incident DORA)
```

| Domaine | Composants |
|---|---|
| Développement | `payment-api`, `auth`, `frontend` (React/Tailwind), `supervision-bff`, `face-api` (DeepFace : auto-inscription, connexion et virements validés par visage) |
| Infrastructure | Docker Compose, Ansible, Prometheus/Grafana/Loki/Promtail |
| IA / Data | `ml-detector` (IsolationForest), `rag-assistant` (Ollama + LangChain) |
| Cybersécurité | WAF ModSecurity + OWASP CRS, SIEM (Loki), secrets HashiCorp Vault |
| Gouvernance | EBIOS RM, PCA/PRA, NIS2/DORA (`docs/`) |

### Authentification : auto-inscription et connexion en 3 étapes ordonnées

Aucun compte client n'est pré-créé. Chaque client s'inscrit lui-même
(identifiant, mot de passe, consentement RGPD, **pool de 5 photos** du
visage : droite, haut, bas, gauche, face) puis se connecte ensuite en 3
étapes strictement ordonnées (§10.1) : **identifiant** seul, puis **visage**
(une photo, comparée au pool), puis **mot de passe** — jamais l'inverse.
Chaque étape n'émet qu'un jeton intermédiaire à usage unique, consommé par
la seule étape suivante (`POST /auth/login/identify` → `/face` → `/password`,
tous portés par `payment-api`). Operator/admin (supervision) gardent un
login mot de passe seul, sans visage. Détails et schémas :
[docs/architecture.md §3.1](docs/architecture.md).

Démo bonus (hors périmètre noté) : un indicateur **LED ESP8266** affiche en
temps réel (WebSocket) le résultat de chaque vérification faciale — voir
[firmware/face-led/](firmware/face-led/README.md).

## Arborescence

```
services/            microservices (API, auth, front, détection, remédiation, BFF, RAG, face-api)
infra/               WAF, observabilité (Prometheus/Grafana/Loki/Promtail), Ansible
firmware/            démo bonus : indicateur LED ESP8266 (PlatformIO), hors périmètre noté
attack/              scripts Red Team (flood, sqli, exfil, leak_replay)
ml/                  entraînement & évaluation du modèle de détection
docs/                architecture, EBIOS RM, PCA/PRA, NIS2/DORA, runbook
tests/               tests (auth, pool biométrique, détection, garde-fous remédiation, parsing SIEM,
                     comptes leurres, mode dégradé, rapport d'incident)
scripts/             vault.sh (secrets), chaos.sh (scénario catastrophe), demo.sh,
                     flash-esp.sh (flash ESP8266), enroll-face.sh, up-ai.sh
docker-compose.yml   orchestration (réseaux segmentés)
.github/workflows/   pipeline CI/CD (lint, tests, scan, E2E de résilience)
Makefile             raccourcis d'exploitation (optionnels, WSL/Linux/macOS)
```

## Principes de conception

- **Détection ML primaire** (pas de règles en dur) avec explicabilité.
- **Reprise prouvée, pas supposée** : validée par une transaction canari réelle.
- **Disponibilité ≠ compromission** : playbooks distincts (DoS vs injection ou
  fuite de données détectée par comptes leurres).
- **Aucun paiement accepté perdu** : pendant la remédiation d'un DoS, les
  virements validés attendent en file puis sont réglés à la clôture.
- **Rapport sans humain** : chaque incident produit un rapport au format d'une
  notification initiale DORA ; l'assistant RAG peut en rédiger le résumé direction.
- **Moindre privilège** : automate isolé (`control`), allowlists, pas d'UI admin
  exposée ; assistant IA en lecture seule, sans privilège.
- **Aucun secret en clair** : HashiCorp Vault (source de vérité), `.env` rendu au déploiement et ignoré par git.

## Documentation

- [Architecture & chaîne de résilience](docs/architecture.md)
- [Automatisation Ansible (déploiement, exploitation, PRA)](docs/ansible.md)
- [Durcissement & moindre privilège des conteneurs](docs/durcissement.md)
- [Gestion des secrets (HashiCorp Vault)](docs/vault.md)
- [Pipeline CI/CD](docs/CICD.md)
- [Schémas d'architecture (draw.io)](docs/diagrams/README.md)
- [Runbook (déploiement, vérification, démo)](docs/runbook.md)
- [Analyse de risques EBIOS RM](docs/ebios-rm.md)
- [PCA / PRA](docs/pca-pra.md)
- [Conformité NIS2 / DORA](docs/nis2-dora.md)
- [Scripts d'attaque](attack/README.md)
- [Indicateur LED ESP8266 (démo bonus)](firmware/face-led/README.md)

## Tests

```bash
pip install -r tests/requirements-dev.txt
python -m pytest -q      # détection, garde-fous de remédiation, parsing SIEM
python ml/train.py       # (ré)entraîne et évalue le modèle
```

## Livrables (packaging)

Dossier de remise : `Workshop2026-M2-G<n>/` (remplacer `<n>` par le numéro
d'équipe). Ce dépôt constitue l'archive des sources `-Code.zip`. Le dossier
d'ingénierie, le support et le Clip Chrono sont produits à partir de `docs/`.
