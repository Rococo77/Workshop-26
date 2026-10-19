# Pipeline CI/CD — PROJECT RESILIENCE-ALPHA

Workflow GitHub Actions : [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
Il suit la chaîne canonique en 11 étapes, **adaptée au contexte** : le livrable
est un démonstrateur mono-machine (PC Hôte), il n'y a pas d'environnement cloud.
Les étapes de déploiement cloud sont donc des **jobs documentés** (pas supprimés),
et le cœur de la valeur est le job **E2E** qui rejoue la chaîne de cyber-résilience
à chaque push.

## Schéma

```
 push / PR
    │
    ▼
 ┌──────────┐   monorepo : ne lance que ce qui a changé (paths-filter)
 │ changes  │
 └────┬─────┘
      ├───────────────┬──────────────────┐
      ▼               ▼                  ▼
 ┌──────────┐   ┌──────────────┐   (frontend ?)
 │static-py │   │static-frontend│
 │ruff+bandit│  │   eslint     │
 └────┬─────┘   └──────┬───────┘
      ▼                ▼
 ┌──────────┐   ┌──────────────┐
 │test-py   │   │build-frontend│
 │pytest+cov│   │  vite build  │
 └────┬─────┘   └──────────────┘
      ▼
 ┌─────────────────────┐   étapes 4+5 : packaging + scan
 │ build-scan (Trivy)  │   docker compose build (cœur+IA)
 │ vuln deps = bloquant│   misconfig/secret = report-only (SARIF)
 └────┬────────────────┘
      ▼
 ┌──────────────┐  étape 6 : "staging" = PC Hôte (Ansible), documenté
 │deploy-staging│
 └────┬─────────┘
      ▼
 ┌─────────────────────────────────────────────┐  étape 7 : E2E RÉEL
 │ e2e : attaque → détection → remédiation →    │  scripts/ci-e2e.sh
 │       transaction canari (échoue si pas de   │  (fait tourner tout le stack)
 │       reprise autonome)                      │
 └────┬────────────────────────────────────────┘
      ▼
 ┌──────────────┐  étape 8 : gate humain (environment production-approval)
 │manual-approval│  (uniquement sur main)
 └────┬─────────┘
      ▼
 ┌──────────┐  étape 9 : publication images sur GHCR (tag = SHA + latest)
 │ publish  │
 └────┬─────┘
      ▼
 ┌────────────┐  étapes 10+11 : "prod" = PC Hôte, validation = make verify + Clip Chrono
 │deploy-prod │
 └────────────┘
```

## Pourquoi cette adaptation

Le sujet impose un démonstrateur local (PC Hôte, PC Attaquant), **pas** une
infrastructure cloud. Produire des jobs Terraform/SonarQube/Nexus qui échouent
faute de serveur donnerait une CI rouge, sans valeur. Les choix :

- **Déploiement** : pas de Terraform cloud. Le déploiement reproductible existe
  déjà via **Ansible** (`infra/ansible/deploy.yml`) sur le PC Hôte. Les jobs
  `deploy-staging` / `deploy-prod` le documentent et conservent la structure
  canonique + le gate humain (`environment`).
- **Registry** : **GHCR** (gratuit, intégré) au lieu de Nexus. Publication sur
  `main` seulement, tag = SHA court + `latest`.
- **SonarQube** : **optionnel** — ne s'exécute que si `SONAR_TOKEN` est défini.
  Sans lui, `ruff` + `bandit` couvrent lint, format et sécurité.
- **Tests E2E** : au lieu de Selenium sur un site déployé, on rejoue la **vraie
  chaîne de résilience** en démarrant le stack via `docker compose` et en
  vérifiant la reprise autonome. C'est le test qui compte pour ce projet.
- **Scan Trivy** : gate **bloquant** sur les vulnérabilités corrigeables de nos
  dépendances (ce qu'on contrôle, `ignore-unfixed`). Les mauvaises configs
  Dockerfile (certains conteneurs tournent en root **volontairement**, ex. le
  moteur de remédiation qui a besoin du socket Docker) et la détection de secrets
  sont en **report-only** (publiées dans l'onglet Security), pour ne pas rendre
  la CI rouge sur des choix assumés. Pour durcir : passer `scanners: misconfig`
  en `exit-code: "1"` une fois les exceptions tracées dans `.trivyignore`.

## Secrets

| Secret | Rôle | Obligatoire |
|--------|------|-------------|
| `GITHUB_TOKEN` | Push des images sur GHCR | Fourni automatiquement par GitHub |
| `SONAR_TOKEN` | Jeton SonarQube | Non — sans lui, l'étape Sonar est sautée |
| `SONAR_HOST_URL` | URL du serveur SonarQube | Non — idem |

Aucun autre secret n'est requis pour une CI verte. Aucun secret n'est codé en dur.

## Environnements à configurer (GitHub → Settings → Environments)

- **`production-approval`** : ajouter des *Required reviewers* → gate humain
  avant la publication (étape 8). Sans configuration, le job attend une approbation.
- **`production`** : optionnel, pour tracer les déploiements prod.

## Tester localement avant de pousser

```bash
# Lint + format + sécurité (identique à la CI)
pip install ruff==0.6.9 bandit==1.7.10
ruff check . && ruff format --check . && bandit -r services ml -ll -x '**/tests/**'

# Tests
pip install -r tests/requirements-dev.txt pytest-cov docker httpx
pytest --cov

# Front
cd services/frontend && npm ci && npm run lint && npm run build

# Chaîne de résilience de bout en bout (nécessite Docker)
scripts/ci-e2e.sh

# Scan Trivy local
trivy fs --severity HIGH,CRITICAL .
```

Pour exécuter le workflow entier en local : [`act`](https://github.com/nektos/act)
(`act push`), en gardant à l'esprit que les jobs Docker-in-Docker (build-scan,
e2e) demandent un runner avec accès au démon Docker.

## Ajouter une étape

1. Ajouter un `job` dans `ci.yml` avec un `needs:` explicite sur le job précédent.
2. Si l'étape est spécifique à une partie du monorepo, la conditionner avec
   `if: needs.changes.outputs.<filtre> == 'true'`.
3. Fail-fast par défaut ; n'utiliser `continue-on-error` que pour une étape
   réellement non bloquante, et le documenter ici.
