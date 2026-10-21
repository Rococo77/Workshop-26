# Gestion des secrets — HashiCorp Vault

> Sujet §3.4 : « gestion des secrets avec HashiCorp Vault ou SOPS ».
> Ce document décrit l'implémentation retenue, ses choix et ses limites.

## 1. Principe

**Vault est la source de vérité des secrets.** Le fichier `.env` lu par Docker
Compose n'en est qu'un **rendu local**, régénéré à chaque déploiement avec un
jeton en **lecture seule**.

```
.env (saisie initiale) --import (jeton racine)--> Vault KV v2 secret/resilience-alpha
                                                         |
Ansible deploy.yml --unseal--> Vault --render (jeton `deploy`, lecture seule)--> .env
                                                         |
                                       journal d'audit -> stdout -> Promtail -> Loki
```

## 2. Choix d'architecture

| Choix | Raison |
|---|---|
| Rendu du `.env` au déploiement, pas de lecture de Vault par les services au démarrage | Le moteur de remédiation **relance** auth et API pendant un incident. Si les services dépendaient de Vault à chaque démarrage, un Vault scellé ferait échouer la reprise autonome (Axe 1 éliminatoire). Le coffre n'est donc jamais sur le chemin critique de la reprise. |
| Réseau `secrets` dédié, aucun autre service rattaché | Vault n'est joignable que par l'administration locale du PC Hôte. |
| Port publié sur `127.0.0.1:8201` uniquement | Interface d'administration jamais exposée au réseau du groupe (§4). Vérifié par `harden.yml`. |
| Politique `deploy` : lecture seule de `secret/data/resilience-alpha` | Moindre privilège : le jeton du déploiement ne peut ni écrire, ni lire un autre chemin, ni gérer le coffre (vérifié : 403). |
| Journal d'audit sur la sortie standard | Chaque accès au coffre arrive dans Loki avec les autres journaux (SIEM). |
| Socle `x-sec` (no-new-privileges, cap_drop ALL), utilisateur non-root | Même durcissement que les autres services. `disable_mlock` faute de capability `IPC_LOCK`. |

## 3. Commandes

```bash
scripts/vault.sh init     # 1re fois : init, descellement, KV v2, audit, politique, jeton deploy, import
scripts/vault.sh unseal   # après tout redémarrage (Vault repart toujours scellé)
scripts/vault.sh import   # .env -> Vault, après ajout/modification d'un secret
scripts/vault.sh render   # Vault -> .env (fait par Ansible deploy.yml)
scripts/vault.sh status
```

Matériel sensible local, ignoré par git (`.vault/`) : clé de descellement et
jeton racine (`init.json`), jeton de déploiement (`deploy.token`).

## 4. Limites assumées (démonstrateur) et cible de production

| Démonstrateur | Production |
|---|---|
| 1 clé de descellement, seuil 1, stockée sur le PC Hôte | Partage de Shamir 5/3 entre personnes, ou auto-unseal par KMS/HSM |
| Jeton racine conservé dans `.vault/init.json` | Jeton racine révoqué après l'installation, régénéré à la demande |
| Stockage fichier, nœud unique, sans TLS (trafic local) | Cluster Raft multi-nœuds, TLS de bout en bout |
| Secrets statiques rendus dans `.env` | Secrets dynamiques (identifiants PostgreSQL à durée de vie courte) lus par les services via AppRole et Vault Agent |
| Descellement manuel après redémarrage (fait par Ansible) | Auto-unseal, aucune intervention |
