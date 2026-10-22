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

HashiCorp Vault est la source de vérité ; le `.env` n'en est qu'un rendu.
```bash
scripts/vault.sh init     # 1re fois : init, descellement, KV, audit, politique, import du .env
scripts/vault.sh unseal   # après tout redémarrage de Vault (il repart scellé)
scripts/vault.sh import   # après modification d'un secret dans .env
scripts/vault.sh render   # Vault -> .env (fait aussi par Ansible deploy.yml)
scripts/vault.sh status
```
`.vault/` (clé de descellement, jetons) et `.env` ne sont **jamais** versionnés.
Interface d'administration : http://127.0.0.1:8201 (locale uniquement). Détails : `docs/vault.md`.

## 4. Vérification de l'état utilisable

```bash
curl -s http://127.0.0.1:8080/api/ready        # 200 = base joignable
# Transaction canari (preuve que le chemin métier complet fonctionne) :
docker exec ra-payment-api python -c "import urllib.request;print(urllib.request.urlopen(urllib.request.Request('http://localhost:8000/internal/canary',method='POST')).read().decode())"
# Raccourci équivalent sous WSL/Linux/macOS : make verify
```
Interfaces :
- Front + dashboard : http://127.0.0.1:8080
- Grafana : http://127.0.0.1:3000/d/resilience-overview (admin / cf. `.env`) —
  état, cycle attaque/détection/remédiation, service métier, journaux corrélés
- Vault : http://127.0.0.1:8201 (local uniquement)

### Mise à niveau d'une base existante (migrations 03 à 08)

Les scripts de `services/payment-api/db/init/` ne sont exécutés par PostgreSQL
**qu'à la création du volume `pgdata`**. Sur une base créée avant leur ajout,
les rejouer à la main (tous idempotents) :
```bash
for f in 03_face_verification 04_auth_self_service 05_biometric_pool 06_canary_accounts          07_honeytokens 08_degraded_mode; do
  docker exec -i ra-postgres psql -U payuser -d paymentdb < services/payment-api/db/init/$f.sql
done
```
| Script | Apport |
|---|---|
| `03_face_verification.sql` | virements `pending` + journal de vérification faciale |
| `04_auth_self_service.sql` | auto-inscription, jeton intermédiaire `face_pending` |
| `05_biometric_pool.sql` | pool de 5 empreintes + consentement. **Détruit les enrôlements à l'ancien format** : réenrôlement nécessaire |
| `06_canary_accounts.sql` | comptes canari dédiés `_canary_src`/`_canary_dst` |
| `07_honeytokens.sql` | comptes leurres (2 utilisateurs, 1 IBAN) et table `honeytoken` |
| `08_degraded_mode.sql` | statut `queued` des virements + table `platform_mode` (mode dégradé) |

Symptôme d'une migration manquante : canari en 503 (`column ... does not
exist` ou `source account not found`) dans `docker logs ra-payment-api`.

Comptes d'exploitation de démonstration (fictifs, mot de passe seul, pas de
virement) : `operator`/`Operator#2026`, `admin`/`Admin#2026`.

Les comptes « clients » ne sont plus semés : chaque client s'inscrit
lui-même (identifiant, mot de passe, **pool de 5 photos** de son visage :
droite, haut, bas, gauche, face) via l'écran « Créer un compte » du front —
précédé d'un pop-up de consentement obligatoire au traitement de la donnée
biométrique — ou directement :
```bash
IMG=$(base64 -w0 moi.jpg)   # démo : la même photo pour les 5 poses
curl -s -X POST http://127.0.0.1:8080/api/auth/register \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"jordan\",\"password\":\"Jordan#2026\",\"consent\":true,
       \"images\":{\"right\":\"$IMG\",\"up\":\"$IMG\",\"down\":\"$IMG\",\"left\":\"$IMG\",\"face\":\"$IMG\"}}"
```
La connexion d'un client exige ensuite le mot de passe **et** le visage (une
seule photo, comparée au pool) :
`POST /auth/login` renvoie un jeton intermédiaire (`pending_token`, ~2 min)
si le mot de passe est correct, puis `POST /api/auth/login/face` (une des
photos enrôlées, ou une photo similaire) renvoie le jeton d'accès complet.

Consentement et suppression : la date de consentement est tracée
(`app_user.biometric_consent_at`). La suppression automatique après 2 ans
d'inactivité annoncée dans le pop-up **n'est pas implémentée** dans ce
démonstrateur (voir `docs/architecture.md` §3.1).

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

Autres scénarios : `attack/sqli.py`, `attack/exfil.py`, `attack/leak_replay.py`
(voir `attack/README.md`).

### Mode dégradé : zéro paiement perdu pendant le DoS

Dès que le playbook DoS démarre, l'API passe en mode dégradé : un virement
validé par le visage est mis en file d'attente (statut `queued`) au lieu
d'être réglé. Quand le détecteur revoit un trafic normal, il clôt l'incident ;
le moteur lève alors le mode dégradé et règle la file, du plus ancien au plus
récent (solde vérifié sous verrou, un virement devenu sans provision est rejeté).
Pour le montrer : pendant l'attaque, valider un virement depuis le front
(message « mis en file d'attente »), puis constater dans l'historique qu'il
passe à réglé après la fin de l'attaque. Désactivable : `DEGRADED_MODE=false`
sur le moteur. Filet : le mode expire seul au bout de 10 min
(`DEGRADED_MAX_MINUTES`) et la file est rejouée au démarrage de l'API.

### Comptes leurres (honeytokens)

```bash
python3 attack/leak_replay.py --target http://192.168.137.1:8080
```
Le script rejoue un extrait « volé » de la table des utilisateurs, qui contient
deux comptes leurres (`m.lefevre.dsi`, `tresorerie.groupe`, IBAN
`FR76-FAKE-7341`). Personne ne les utilise : une connexion, un virement vers
l'IBAN ou une réponse HTTP qui contient l'une de ces valeurs prouve la fuite.
Le détecteur ouvre l'incident `honeytoken_triggered` sans passer par le
modèle, le moteur bloque la source si elle est attribuable et liste les
actions humaines (origine de la fuite, rotation des secrets, notifications).

### Rapport d'incident automatique

Après chaque incident, le moteur produit un rapport au format d'une
notification initiale DORA : chronologie depuis le premier point anormal,
cause, actions, temps de reprise. Supervision, carte de l'incident :
« Rapport d'incident », téléchargeable en `.md`. Le bouton « Résumé pour la
direction » demande à l'assistant RAG (profil `ai`) de rédiger un résumé
depuis ce rapport, en lecture seule (environ 40 s sur CPU). API :
`GET /reports`, `GET /reports/{id}` sur le moteur.

## 6. Chaos engineering (répétition jeudi)

**Scénario catastrophe** : les trois attaques (flood, injection SQL,
exfiltration) frappent en même temps ; le script affiche en direct le score
ML, la décision, la remédiation et le canari, puis le délai de détection et
de reprise prouvée.
```bash
scripts/chaos.sh                                   # répétition locale (cible 127.0.0.1:8080, 45 s)
scripts/chaos.sh http://192.168.137.1:8080 60      # depuis le PC Attaquant, 60 s
```
Les lectures d'état passent par `docker exec` : lancer le script sur le PC
Hôte, ou ne garder que les attaques depuis le PC Attaquant et suivre la reprise
dans Grafana.

Panne franche pour valider le playbook `service_unavailable` :
```bash
docker kill ra-payment-api     # le détecteur voit up==0 -> restart auto -> canari
```

> Sous Docker Desktop, toutes les requêtes arrivent avec l'IP de la passerelle
> Docker : le blocage d'IP ne se constate (`IP bloquées` > 0) qu'avec un vrai
> PC Attaquant sur 192.168.137.0/24.

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

### Validation faciale : enrôlement et réenrôlement

Base existante : voir « Mise à niveau d'une base existante » (§4).

```bash
# Lier un pool de 5 photos (droite, haut, bas, gauche, face) à un client
# depuis des fichiers (opérateur, hors parcours web ; un client normal passe
# par l'auto-inscription, voir §4 ci-dessus). --consent atteste que le
# consentement biométrique a été recueilli (ex. formulaire papier).
# Nouveau client + compte (outil d'exploitation, hors auto-inscription) :
scripts/enroll-face.sh jordan --create --password 'Jordan#2026' --balance 2500 --consent \
  --photo-right droite.jpg --photo-up haut.jpg --photo-down bas.jpg \
  --photo-left gauche.jpg --photo-face face.jpg
# Client existant (--replace pour écraser le pool déjà présent) :
scripts/enroll-face.sh jordan --replace \
  --photo-right droite.jpg --photo-up haut.jpg --photo-down bas.jpg \
  --photo-left gauche.jpg --photo-face face.jpg
# Sans bash (PowerShell) : copier chaque photo dans le conteneur
# (docker cp ... ra-payment-api:/tmp/<pose>.jpg) puis appeler directement
#   docker exec ra-payment-api python -m app.enroll_cli --username jordan --replace
#     --photo-right /tmp/right.jpg --photo-up /tmp/up.jpg --photo-down /tmp/down.jpg
#     --photo-left /tmp/left.jpg --photo-face /tmp/face.jpg
# Les empreintes vivent en base (volume pgdata) : à refaire après `docker compose down -v`.
# Ne jamais les versionner dans un seed : donnée biométrique (RGPD art. 9).

# Réenrôler un client (supprime son pool ; il devra refaire les 5 photos à
# sa prochaine connexion — login mot de passe + visage impossible sans elle)
docker exec ra-postgres psql -U payuser -d paymentdb -c \
  "DELETE FROM face_enrollment WHERE user_id = (SELECT id FROM app_user WHERE username = 'jordan')"
```

## 8. Démo bonus : indicateur LED ESP8266

Hors des 5 domaines notés du sujet. Un ESP8266 (2 LED, voir
`firmware/face-led/README.md`) se connecte en WebSocket à `payment-api` via
le WAF (`/api/ws/face-events`, jeton `ESP_EVENTS_TOKEN`) et affiche en
temps réel le résultat de chaque vérification faciale (connexion, virement) :
verte = reconnu, rouge = refusé.

Flash depuis le PC Hôte (Git Bash côté Windows : WSL ne voit pas les ports
série USB). Le script génère `include/secrets.h` depuis le `.env`
(`ESP_WIFI_SSID`, `ESP_WIFI_PASSWORD`, `ESP_EVENTS_TOKEN`, `EDGE_PORT` ; IP du
PC Hôte et port série CH340 détectés, surchargeables par `ESP_WS_HOST` /
`ESP_SERIAL_PORT`), compile puis flashe :
```bash
scripts/flash-esp.sh               # génère, compile, flashe
scripts/flash-esp.sh --build-only  # compile seulement
pio device monitor -d firmware/face-led -b 115200   # logs (Wi-Fi, WS, événements)
```
Jour de la démo : `ESP_WIFI_SSID=RESILIENCE-G1` et `ESP_WS_HOST=192.168.137.1`.

## 9. Sauvegarde & restauration (PCA/PRA)

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

## 10. Arrêt / remise à zéro

```bash
docker compose --profile ai down      # arrêt
docker compose --profile ai down -v   # arrêt + suppression des volumes (état propre)
# Raccourcis WSL/Linux/macOS : make down / make reset
```
