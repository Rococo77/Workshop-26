# Runbook — déploiement, vérification, démonstration

> Procédure opérationnelle. Sert aussi de corpus à l'assistant RAG.

## 1. Prérequis (PC Hôte)

- Windows 10/11 + Docker Desktop (WSL2), ou Linux + Docker Engine.
- Docker Compose v2, 16 Go RAM (32 Go recommandé si profil IA sur le même poste).
- Python 3 (pour les scripts d'attaque et d'entraînement ML).
- Ports publiés : `8080` (WAF = front + API), `3000` (Grafana).
- **Exposition réseau (démo)** : pour n'exposer QUE le réseau du groupe, régler
  dans `.env` `EDGE_BIND=192.168.137.1` (interface du hotspot `RESILIENCE-G<n>`)
  — le WAF et Grafana ne répondront alors que sur cette interface, pas sur le
  WiFi du campus (sujet §4). `EDGE_PORT` (défaut 8080) permet de changer le port
  hôte si 8080 est déjà pris (ex. Oracle TNS/APEX). En dev/CI : `EDGE_BIND=0.0.0.0`.
- **WSL2 (Ubuntu)** nécessaire uniquement pour **Ansible** (option C) et les
  scripts `.sh`. Les options A/B (`docker compose`) tournent dans PowerShell.

## 2. Déploiement

### Option A — Docker Compose (voie de référence, PowerShell ou bash)
```bash
copy .env.example .env                       # PowerShell : copy ; bash : cp
docker compose up -d --build                 # cœur (sans IA)
scripts/up-ai.sh    # cœur + assistant IA (Ollama sur GPU si dispo, sinon CPU)
docker compose ps                            # état des conteneurs
```

### Option B — Make (raccourcis, WSL/Linux/macOS)
```bash
make up          # cœur (sans IA)
make up-ai       # cœur + assistant IA
make ps          # état des conteneurs
```
Make n'est pas installé par défaut sous Windows : utiliser l'option A dans ce cas.

### Option C — Ansible (reproductible, nécessite WSL sous Windows)

**Installation de WSL Ubuntu + Ansible (une fois, sur le PC Hôte)** — la distro
`docker-desktop` ne suffit pas (pas d'Ansible). Méthode fiable par import de
rootfs (évite l'écran interactif) :
```powershell
# 1) Importer une Ubuntu 24.04 propre (rootfs officiel Canonical)
#    https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz
wsl --import UbuntuRA C:\Users\<user>\WSL\UbuntuRA <chemin>\ubuntu-noble-...rootfs.tar.gz
# 2) Installer Ansible dans la distro
wsl -d UbuntuRA -u root -- bash -lc "apt-get update && apt-get install -y ansible git"
```
Activer l'**intégration WSL de Docker Desktop** pour `UbuntuRA` (Settings →
Resources → WSL Integration, ou `integratedWslDistros: ["UbuntuRA"]` dans
`%APPDATA%\Docker\settings.json` puis redémarrer Docker Desktop).

> Si `docker` reste injoignable dans la distro (socket `/var/run/docker.sock`
> absent), pointer le client sur le socket partagé de Docker Desktop :
> ```bash
> echo 'export DOCKER_HOST=unix:///mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.sock' \
>   | sudo tee /etc/profile.d/docker-host.sh
> ```

> ⚠️ **Le `deploy` (docker compose) ne tourne PAS depuis WSL avec Docker
> Desktop.** Le démon Docker vit dans la distro `docker-desktop` : un
> `docker compose` lancé depuis une autre distro lui demande de monter des
> fichiers (`prometheus.yml`, etc.) à des chemins (`/mnt/c/...` **ou** `/root/...`)
> que le démon ne voit pas dans son propre espace → `error mounting ... to
> rootfs`. Seul le client docker **Windows** résout correctement ces bind-mounts
> (chemins `C:\`). Donc, sous **Windows + Docker Desktop** :
> - **`deploy`** → via `docker compose` côté **PowerShell** (Option A, prouvé) ;
> - **`preflight` / `harden` / `backup` / `restore` / `ops`** → depuis WSL, OK.
>
> Sur un **hôte Linux + Docker Engine** (client et démon partagent le FS), toute
> la chaîne Ansible, `deploy` compris, fonctionne de bout en bout.

**Lancement des playbooks** (le dépôt est vu sous `/mnt/c/...` ; `ansible.cfg`
étant sur un montage *world-writable*, passer l'inventaire avec `-i`) :
```bash
wsl -d UbuntuRA
git config --global --add safe.directory /mnt/c/Users/<user>/Desktop/Workshop-26
cd /mnt/c/Users/<user>/Desktop/Workshop-26/infra/ansible
# --- Windows + Docker Desktop (RECOMMANDÉ) : Compose déploie, Ansible vérifie ---
#   1) déployer côté PowerShell :  docker compose up -d --build
#   2) vérifier + durcir (WSL)   :  site.yml en sautant le deploy Ansible :
ansible-playbook -i inventory.ini site.yml -e deploy_via_ansible=false

# --- Hôte Linux + Docker Engine : chaîne complète (deploy Ansible inclus) ---
# Point d'entrée unique : prérequis -> déploiement -> vérifs de posture
ansible-playbook -i inventory.ini site.yml                   # cœur + vérifications
ansible-playbook -i inventory.ini site.yml -e with_ai=true   # + IA (modèles Ollama)
ansible-playbook -i inventory.ini site.yml -e configure_firewall=true  # + pare-feu

# Playbooks autonomes (hors chaîne nominale) :
ansible-playbook -i inventory.ini preflight.yml   # prérequis seuls
ansible-playbook -i inventory.ini deploy.yml      # déploiement seul
ansible-playbook -i inventory.ini harden.yml      # vérifie durcissement + secrets + exposition
ansible-playbook -i inventory.ini ops.yml -e action=status    # opérations (status/restart_api/backup_db)
```
`site.yml` est le plan d'orchestration **Day-0/1** (déploiement/exploitation),
**distinct** de la reprise autonome **Day-2** (moteur de remédiation). Ansible
n'est jamais dans la boucle de reprise live.

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
# Transaction canari (preuve que le chemin métier complet fonctionne) :
docker exec ra-payment-api python -c "import urllib.request;print(urllib.request.urlopen(urllib.request.Request('http://localhost:8000/internal/canary',method='POST')).read().decode())"
# Raccourci équivalent sous WSL/Linux/macOS : make verify
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
| RAG en 503 | Ollama absent / modèle non pull | `scripts/up-ai.sh`, puis (réseau `app` sans Internet) `docker network connect bridge ra-ollama`, `docker exec ra-ollama ollama pull hf.co/unsloth/Qwen3-4B-GGUF:Q4_K_M` et `nomic-embed-text`, `docker network disconnect bridge ra-ollama` |
| Front inaccessible | Vite pas démarré | `docker compose logs frontend` |
| Pas de caméra dans le navigateur | `getUserMedia` exige HTTPS ou `localhost` | depuis un autre PC en HTTP, le front propose « Prendre ou importer une photo » (caméra directe sur mobile) ; ou Chrome `--unsafely-treat-insecure-origin-as-secure=http://192.168.137.1:8080` |
| Virement : « visage non reconnu » systématique | éclairage / enrôlement de mauvaise qualité | réenrôler (voir ci-dessous) ; seuil `FACE_MATCH_THRESHOLD` |
| `face_unavailable` (503) | `face-api` arrêtée | `docker compose logs face-api` ; le virement reste en attente 5 min |

### Validation faciale : migration et réenrôlement

```bash
# Base existante (créée avant la validation faciale) : script idempotent
docker exec -i ra-postgres psql -U payuser -d paymentdb < services/payment-api/db/init/03_face_verification.sql

# Lier un visage à un client depuis une photo (opérateur, hors parcours web).
# Nouveau client + compte :
scripts/enroll-face.sh moi.jpg jordan --create --password 'Jordan#2026' --balance 2500
# Client existant (--replace pour écraser une empreinte déjà présente) :
scripts/enroll-face.sh moi.jpg alice
# Sans bash (PowerShell) :
#   docker cp moi.jpg ra-payment-api:/tmp/face.jpg
#   docker exec ra-payment-api python -m app.enroll_cli --username alice --photo /tmp/face.jpg
#   docker exec -u root ra-payment-api rm -f /tmp/face.jpg
# L'empreinte vit en base (volume pgdata) : à refaire après `docker compose down -v`.
# Ne jamais la versionner dans un seed : donnée biométrique (RGPD art. 9).

# Réenrôler un client (supprime son empreinte, il refera la photo à la connexion)
docker exec ra-postgres psql -U payuser -d paymentdb -c \
  "DELETE FROM face_enrollment WHERE user_id = (SELECT id FROM app_user WHERE username = 'alice')"
```

## 8. Sauvegarde & restauration (PCA/PRA)

```bash
cd infra/ansible
ansible-playbook backup.yml                     # dump horodaté -> backups/ (rétention 7)
ansible-playbook backup.yml -e retention=10

# Restauration PRA : restaure PUIS vérifie le service par le canari (/api/ready).
ansible-playbook restore.yml -e confirm=yes     # dernière sauvegarde par défaut
ansible-playbook restore.yml -e confirm=yes -e backup_file=backups/paymentdb_AAAAMMJJ_HHMMSS.sql
```
Une sauvegarde n'a de valeur que si la restauration est **prouvée** : `restore.yml`
échoue si `/api/ready` ne repasse pas à 200 après restauration. Les fichiers
`backups/*.sql` ne sont pas versionnés (cf. `.gitignore`).

## 9. Arrêt / remise à zéro

```bash
docker compose --profile ai down      # arrêt
docker compose --profile ai down -v   # arrêt + suppression des volumes (état propre)
# Raccourcis WSL/Linux/macOS : make down / make reset
```
