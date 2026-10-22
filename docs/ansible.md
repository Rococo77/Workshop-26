# Automatisation Ansible — déploiement, exploitation, PRA

> PROJECT RESILIENCE-ALPHA — volet Infrastructure (sujet §3.2).
> Ce document décrit **le rôle d'Ansible**, son fonctionnement, chaque playbook
> livré, et comment déployer/exploiter la plateforme de façon reproductible. Il
> alimente le `Workshop2026-M2-G<n>-Dossier.pdf`.

---

## 1. Rôle d'Ansible dans le projet

Le sujet impose **Docker Compose** pour *définir et orchestrer les conteneurs*,
et des **playbooks Ansible** pour *automatiser les opérations* (déploiement,
reprise, exploitation). Ansible est donc notre couche **Infrastructure as Code** :
installer, vérifier, sauvegarder, restaurer et exploiter la plateforme **par du
code reproductible**, pas à la main.

Point structurant — Ansible agit sur **deux moments du cycle de vie**, mais
**jamais** dans la boucle de reprise automatique :

```
  Day-0 / Day-1 : INSTALLER & EXPLOITER        Day-2 : REPRISE AUTONOME
  ┌───────────────────────────────┐           ┌──────────────────────────┐
  │ Ansible (site/deploy/harden/   │           │ moteur de remédiation    │
  │ backup/restore/ops)            │    ≠      │ (détection ML → action)  │
  │ déclenché par un HUMAIN, rare  │           │ AUCUN humain, en direct  │
  └───────────────────────────────┘           └──────────────────────────┘
```

Ansible **prépare le terrain et vérifie** ; le **moteur de remédiation** répare
tout seul pendant l'incident. Cette séparation est volontaire (sujet §3.4).

---

## 2. Comment Ansible fonctionne

- **Sans agent** (*agentless*) : rien à installer sur les cibles. Un **nœud de
  contrôle** (le PC Hôte) possède les playbooks + l'inventaire et agit sur les
  cibles. Ici la cible est le PC Hôte lui-même (`ansible_connection=local`).
- **Playbooks** = fichiers YAML décrivant des tâches, exécutées **dans l'ordre**,
  de façon **idempotente** (rejouer ne refait que ce qui a changé).
- **Ansible ne lance pas les conteneurs un par un** : il **délègue à Docker
  Compose** via le module `community.docker.docker_compose_v2` (équivaut à
  `docker compose up -d --build`). C'est Compose qui lit `docker-compose.yml`,
  crée les réseaux/volumes et démarre les 15 conteneurs dans l'ordre des
  dépendances (`depends_on` + `healthcheck`). Le `docker-compose.yml` reste la
  **source de vérité** unique de l'architecture ; Ansible l'**invoque**.

```
   ANSIBLE                     DOCKER COMPOSE              DOCKER ENGINE
   prépare, déclenche,   ───▶  lit docker-compose.yml ───▶ crée réseaux/volumes,
   puis vérifie (/ready)       (15 services, réseaux…)      démarre les conteneurs
```

---

## 3. Fichiers livrés (`infra/ansible/`)

| Fichier | Rôle |
|---|---|
| `ansible.cfg` | Config (inventaire par défaut, sortie YAML, pas de retry files). |
| `inventory.ini` | Machines pilotées : `host` (PC Hôte, local) + `ia`/`esp` (optionnels). |
| `site.yml` | **Point d'entrée unique** : `preflight` → `deploy` → `harden`. |
| `preflight.yml` | Vérifie les prérequis avant tout déploiement. |
| `deploy.yml` | Déploie la plateforme (ou délègue à Compose, voir §6). |
| `harden.yml` | Vérifie la posture de sécurité (+ pare-feu hôte optionnel). |
| `backup.yml` | Sauvegarde logique PostgreSQL (dump horodaté + rétention). |
| `restore.yml` | Restauration PRA **vérifiée** par transaction canari. |
| `ops.yml` | Opérations courantes (`status` / `restart_api` / `backup_db` / `migrate`). |

---

## 4. Les playbooks en détail

### `site.yml` — orchestrateur unique
Enchaîne trois plans : prérequis, déploiement, vérification de posture. C'est la
commande à lancer pour (re)mettre la plateforme en route et la contrôler.

### `preflight.yml` — prérequis (fin du « ça marche sur ma machine »)
Vérifie : Docker présent, Docker Compose v2, collection `community.docker`
installée, le conteneur Vault (si le coffre est initialisé), et la présence
d'un `.env` ou d'un coffre Vault. Échoue tôt et clairement si un prérequis manque.

### `deploy.yml` — déploiement
1. Vérifie Docker.
2. **Si** Vault est initialisé (`.vault/init.json`) : le descelle puis rend le
   `.env` avec le jeton `deploy` (lecture seule) ; sinon s'appuie sur le `.env`
   présent (voie démo locale).
3. Lance `docker compose up -d --build` via le module (selon `deploy_via_ansible`,
   voir §6) ; variante `with_ai=true` pour Ollama (détection GPU + pull modèles).
4. **Attend `/api/ready` = 200** (20 essais) : la mise en route est *vérifiée*,
   pas supposée.

Variables : `with_ai` (défaut false), `ollama_model`, `deploy_via_ansible`
(défaut true — voir §6).

### `harden.yml` — vérification de posture (sujet §3.4)
Le durcissement est **déclaratif** dans `docker-compose.yml` (voir
[durcissement.md](durcissement.md)) ; ce playbook le **contrôle** :
- présence de `no-new-privileges`, `cap_drop`, `read_only` et du
  `docker-socket-proxy` (échoue si quelqu'un les a retirés) ;
- hygiène des secrets : `.env` ignoré par git et non suivi ;
- exposition minimale : aucun service interne (DB, remédiation, proxy, détecteur)
  n'est publié ;
- *optionnel* (`-e configure_firewall=true`) : règles pare-feu hôte restreignant
  le point d'entrée au seul réseau du groupe (`192.168.137.0/24`).

### `backup.yml` — sauvegarde (PCA/PRA)
`pg_dump --clean --if-exists` → `backups/paymentdb_<horodatage>.sql`. Le `--clean
--if-exists` rend le dump **rejouable** sur une base déjà peuplée. Rétention
configurable (`-e retention=N`, défaut 7). Les identifiants viennent des variables
d'environnement **du conteneur** (aucun secret en ligne de commande).

### `restore.yml` — restauration PRA **prouvée**
Opération destructive → exige `-e confirm=yes`. Restaure la dernière sauvegarde
(ou `-e backup_file=...`) **puis vérifie** que `/api/ready` repasse à 200. Une
sauvegarde n'a de valeur que si la restauration est démontrée.

### `ops.yml` — exploitation courante
`-e action=status` (état des conteneurs), `restart_api` (relance ciblée),
`backup_db` (dump rapide), `migrate` (rejoue dans l'ordre les scripts
idempotents de `services/payment-api/db/init/` sur une base créée avant leur
ajout, ex. comptes leurres et mode dégradé). Filet d'exploitation hors incident.

---

## 5. Inventaire multi-hôtes

```ini
[host]              # PC Hôte : tout le SI conteneurisé (connexion locale)
pc-hote ansible_connection=local
[ia]                # (optionnel) PC délestage : Ollama déporté
[esp]               # (optionnel) ESP8266 : génération de sa config WiFi/MQTT
[all:vars]
group_subnet=192.168.137.0/24
host_ip=192.168.137.1
```
Le nœud de contrôle (PC Hôte) peut piloter jusqu'à trois cibles. `ia` et `esp`
sont préparés pour les évolutions (délestage IA, consigne B).

---

## 6. Comment déployer (selon l'environnement)

Le déploiement réel (`docker compose up`) exige que **le client docker et le
démon partagent la même vue du système de fichiers**, à cause des *bind-mounts*
de fichiers de conf (`prometheus.yml`, etc.).

### Windows + Docker Desktop (configuration de la démo) — **RECOMMANDÉ**
On déploie **côté Windows** avec Compose, et Ansible (depuis WSL) fait le reste :
```powershell
docker compose up -d --build              # 1) déploie (PowerShell)
```
```bash
# 2) vérifie + durcit (WSL) — saute le `docker compose up` d'Ansible :
ansible-playbook -i inventory.ini site.yml -e deploy_via_ansible=false
```
Le drapeau **`deploy_via_ansible=false`** fait sauter l'étape `docker compose up`
d'Ansible tout en conservant la vérif `/api/ready` et le durcissement.

> **Pourquoi pas le `docker compose up` d'Ansible depuis WSL ?** Les bind-mounts
> de fichiers de conf (`prometheus.yml`, etc.) échouent (`error mounting ... to
> rootfs`). Le démon Docker vit dans la distro `docker-desktop` ; pour qu'un
> `docker compose` lancé depuis une autre distro traduise les chemins vers la vue
> du démon, Docker Desktop doit y lancer son **proxy d'intégration**
> (`/var/run/docker.sock`). Or ce proxy n'est provisionné que pour les distros
> **installées via le Microsoft Store**, pas pour celles créées par
> `wsl --import`. Notre `UbuntuRA` étant importée, le proxy est absent → les
> bind-mounts ne se traduisent pas. Ce n'est **pas** un bug des playbooks : les
> autres (preflight/harden/backup/restore/ops) n'utilisent pas de bind-mount et
> fonctionnent depuis WSL. Pour obtenir le deploy Ansible natif sous Windows+DD,
> installer Ubuntu **via le Store** (DD l'intègre alors automatiquement).

> Prérequis WSL : voir [runbook.md](runbook.md) §2 Option C (import d'une Ubuntu,
> `apt install ansible`, intégration Docker Desktop). Lancer les playbooks avec
> `-i inventory.ini` (le `ansible.cfg` est ignoré sur un montage `/mnt/c`
> *world-writable*).

### Hôte Linux + Docker Engine
Client et démon partagent le FS → **toute la chaîne Ansible fonctionne**, deploy
inclus :
```bash
ansible-playbook -i inventory.ini site.yml            # prérequis + deploy + harden
ansible-playbook -i inventory.ini site.yml -e with_ai=true
```

---

## 7. Validation (ce qui a été testé)

Testés **réellement** depuis une Ubuntu WSL (Ansible core 2.16) pointant sur
Docker Desktop :

| Playbook | Résultat |
|---|---|
| `preflight.yml` | ✅ `failed=0` |
| `harden.yml` | ✅ `failed=0` |
| `backup.yml` | ✅ `failed=0` (dump rejouable) |
| `restore.yml` | ✅ `failed=0` — *« /api/ready = 200, PRA prouvé »* |
| `ops.yml` (status) | ✅ `failed=0` |
| `site.yml -e deploy_via_ansible=false` | ✅ `failed=0` (deploy sauté, vérif + harden OK) |
| `site.yml` (deploy Ansible depuis WSL) | ⚠️ KO sous Docker Desktop (bind-mounts, §6) ; OK sur hôte Linux |

Bugs trouvés et corrigés par ces tests : rendu Vault conditionnel
(`deploy.yml`), et
`pg_dump --clean --if-exists` pour une restauration idempotente (`backup.yml`).

---

## 8. Résumé

**Ansible = installer, vérifier, sauvegarder, restaurer et exploiter la
plateforme par du code reproductible.** Il délègue la création des conteneurs à
Docker Compose, vérifie que le service répond vraiment, contrôle la posture de
sécurité et fournit un PRA prouvé. La reprise *pendant* l'incident reste, elle,
du ressort exclusif du moteur de remédiation.
