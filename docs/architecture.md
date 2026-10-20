# Architecture & chaîne de cyber-résilience

> PROJECT RESILIENCE-ALPHA — démonstrateur de reprise autonome (Zero-Touch Recovery).
> Ce document décrit l'architecture réelle livrée dans le dépôt, les flux, le
> cycle de vie d'un incident et les choix de sécurité. Il alimente le
> `Workshop2026-M2-G<n>-Dossier.pdf`.

## 1. Vue d'ensemble

Le démonstrateur est une plateforme de paiement **fictive**, conteneurisée,
déployée de façon reproductible via Docker Compose sur le PC Hôte. Il réunit les
cinq domaines imposés autour d'une seule boucle : **attaque → détection →
décision → remédiation → vérification**, sans intervention humaine.

```
                         PC ATTAQUANT (réseau du groupe 192.168.137.0/24)
                                   │  flood / sqli / exfil
                                   ▼
┌───────────────────────────── PC HÔTE (Docker) ──────────────────────────────┐
│                                                                              │
│   [edge]        ┌────────── WAF (ModSecurity + OWASP CRS) ──────────┐        │
│   8080  ───────▶│  reverse proxy durci · rate limit · blocklist dyn.│        │
│                 └───┬───────────────┬────────────────┬─────────────┘        │
│   [app]             ▼               ▼                ▼                       │
│              frontend React   payment-api (API)   auth (JWT)   supervision-bff │
│                                     │   │                              │      │
│   [data]                            ▼   ▼                              │      │
│                                 PostgreSQL (interne, non exposé)       │      │
│                                                                        │      │
│   [obs]   Prometheus ── Loki ── Promtail ── Grafana  ◀── métriques/logs│      │
│                 │                                                      │      │
│                 ▼ (features)                                           │      │
│   ml-detector (IsolationForest + corrélation SIEM)                     │      │
│                 │ incident (jeton interne)                             │      │
│   [control]     ▼                                                      │      │
│          remediation-engine (non-root) ─▶ docker-socket-proxy (filtré) ─▶ restart │
│                             └─▶ WAF (block IP) · canari  — voir docs/durcissement.md │
│                                                                              │
│   [ai]    ollama + rag-assistant (LangChain) — assistant opérateur, read-only │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 2. Les cinq domaines et leur interconnexion

| Domaine | Composants livrés | Branché sur la boucle |
|---|---|---|
| **Développement** | `payment-api`, `auth`, `frontend` (React/Tailwind), `supervision-bff` | Produit les signaux (métriques) ; le front rend l'état avant/pendant/après ; la transaction canari prouve la reprise |
| **Infrastructure** | `docker-compose.yml`, playbooks Ansible, Prometheus/Grafana/Loki/Promtail | Déploiement reproductible ; l'observabilité alimente la détection |
| **IA / Data** | `ml-detector` (IsolationForest), `rag-assistant` (Ollama+LangChain) | Le modèle **déclenche** la remédiation ; l'assistant aide l'opérateur (sans privilège) |
| **Cybersécurité** | WAF ModSecurity+CRS, corrélation SIEM (Loki), secrets SOPS/age, durcissement | Le WAF bloque/trace ; le SIEM qualifie l'attaque et fournit l'IP source |
| **Gouvernance** | EBIOS RM, PCA/PRA, analyse NIS2/DORA | Justifie les services critiques, les objectifs de reprise, les arbitrages |

## 3. Flux métier nominal

1. L'utilisateur s'authentifie (`auth` → JWT HS256, `iss`/`exp` vérifiés).
2. Le front appelle `payment-api` avec le jeton.
3. `payment-api` exécute un **virement atomique** (verrou pessimiste ordonné,
   contrôle de solde, écriture transactionnelle) sur PostgreSQL.
4. Chaque requête émet des métriques Prometheus (taux, latence, statut, métier).

### 3.1 Validation faciale des virements (DeepFace)

Un virement client n'est réglé qu'après reconnaissance du visage du titulaire.

```
front ──POST /transactions──▶ payment-api ── virement `pending` (5 min, 3 essais)
front ──photo──▶ POST /transactions/{id}/confirm ▶ payment-api ──/represent──▶ face-api
                                     distance cosinus ≤ 0,30 ? ──▶ règlement atomique
```

- **`face-api`** : API Flask officielle de [DeepFace](https://github.com/serengil/deepface)
  (tag `v0.0.102`, commit vérifié au build), moteur **ONNX** : Facenet512
  (empreinte 512 d), YuNet (détection), FasNet (anti-spoofing : photo d'écran
  ou imprimée). Poids embarqués dans l'image.
- **Isolement** : réseau `biometric` interne (seul `payment-api` y accède,
  ni le WAF ni Internet) + jeton Bearer `FACE_API_TOKEN`.
- **Décision dans `payment-api`** : DeepFace calcule l'empreinte, la
  comparaison et le seuil sont maîtrisés côté métier. La distance est
  journalisée (audit `face_verification_log`, logs Loki) mais **jamais renvoyée
  au client** (pas d'oracle pour optimiser une image d'attaque).
- **Minimisation (RGPD art. 9)** : aucune photo stockée, seulement le vecteur
  d'empreinte (`face_enrollment`). Enrôlement unique, sans écrasement possible
  par la seule connaissance du mot de passe.
- **Anti force brute** : 3 essais par virement, verrou utilisateur après
  5 échecs en 15 min (429), zone de rate-limit WAF dédiée (2 req/s).
- **Disponibilité ≠ compromission** : `face-api` indisponible → 503, le
  virement reste en attente (aucun essai consommé) ; le canari et `/ready` ne
  dépendent pas de la biométrie.
- Les fonds ne bougent qu'au règlement : solde re-contrôlé sous verrou, double
  confirmation impossible (`FOR UPDATE` sur la ligne `pending`).
- `FACE_CONFIRMATION_REQUIRED=false` restaure le règlement immédiat.

La base, les secrets et les interfaces de gestion **ne sont pas publiés** sur le
réseau pédagogique : seul le WAF (et Grafana pour l'observation jury) est exposé.

## 4. Cycle de vie d'un incident (reprise autonome)

```
flood/sqli ──▶ WAF (bloque/trace) ──▶ métriques+logs ──▶ Prometheus/Loki
                                                              │
                                   ml-detector (toutes les 10s) :
                                   1. collecte le vecteur de features
                                   2. score IsolationForest (anomalie ?)
                                   3. si anomalie : qualifie (SIEM/Loki) + IP source
                                   4. POST /incident (jeton interne)
                                                              │
                                   remediation-engine :
                                   5. playbook selon le type d'incident
                                   6. action (block IP WAF / restart conteneur)
                                   7. VÉRIFIE par transaction canari réelle
                                                              │
                                   dashboard : score, IP bloquée, reprise prouvée
```

Points clés de conception :

- **Détection ML primaire, pas de règles en dur.** Le modèle non supervisé
  (IsolationForest) apprend le profil nominal ; les règles Prometheus ne servent
  que de filet et de visualisation. Explicabilité par z-score des features.
- **Reprise prouvée, pas supposée.** Un conteneur « up » ne suffit pas : la
  reprise n'est validée que si une **transaction canari** (débit→crédit→écriture)
  réussit. C'est ce que vérifie le moteur avant de déclarer le service rétabli.
- **Disponibilité ≠ compromission.** Deux familles de playbooks distinctes :
  `dos_flood`/`service_unavailable` (rétablir) vs `injection_attempt` (confiner +
  tracer, sans prétendre « réparer » un service qui répond toujours).

## 5. Détection — modèle et données

- **Modèle** : IsolationForest (scikit-learn), non supervisé — adapté au cas où
  le trafic nominal est abondant mais les attaques étiquetées rares.
- **Features** : `req_rate` et `waf_block_rate` proviennent des métriques du WAF
  (micro-exporter de logs nginx → Prometheus) : signal temps réel non dampé par
  le rate-limiting. `err_ratio`, `p95_latency` (API métier), `auth_fail_rate`
  (auth). L'IP attaquante est résolue par le moteur de remédiation directement
  depuis les journaux du conteneur WAF (fiable, sans latence d'ingestion) ;
  Loki alimente la corrélation SIEM et le dashboard.
- **Préparation** : standardisation (z-score) sur le profil nominal.
- **Résultats** (jeu synthétique, `ml/train.py`) : rappel ~100 %, faux positifs
  ~5 % sur le profil de démonstration.
- **Limites** : modèle calé sur charge légère ; en production, réentraînement sur
  trafic réel, fenêtres multi-échelles, features additionnelles (entropie des
  chemins, géo-IP, saisonnalité). Voir `docs/nis2-dora.md`.

## 6. Sécurité et durcissement

- **Segmentation réseau** : `edge` (WAF) / `app` / `data` (interne) / `obs` /
  `control` (remédiation isolée). La base n'est accessible que depuis `app`.
- **WAF** : ModSecurity + OWASP CRS (blocage réel), rate limiting par IP,
  en-têtes de durcissement, blocklist dynamique pilotée par la remédiation.
- **Moindre privilège de l'automate** : le moteur de remédiation a besoin du
  socket Docker, mais tourne sur un réseau `control` isolé, **sans UI d'admin
  exposée**, avec une **allowlist** de conteneurs (la base n'est jamais
  redémarrée automatiquement) et une allowlist de playbooks.
- **Assistant IA sans privilège** : le RAG lit un corpus documentaire en lecture
  seule ; il ne peut pas agir sur le système et est distinct de l'automate.
- **Secrets** : aucun secret en clair (SOPS + age ; `.env` ignoré par git).
  Requêtes SQL **paramétrées**, validation d'entrées (Pydantic), pas de secret
  dans les logs, messages d'erreur sans oracle.

## 7. Du démonstrateur à l'industriel (arbitrages)

- Front : mode dev Vite pour la démo → build statique servi par nginx en prod.
- Secrets : SOPS/age (léger) → HashiCorp Vault (rotation, baux dynamiques).
- Inférence LLM : Ollama (démo, CPU/GPU) → vLLM/TGI derrière une API
  OpenAI-compatible en production (débit, batching continu).
- Remédiation : socket Docker → orchestrateur avec RBAC (Kubernetes + Operator),
  actions signées et journal d'audit immuable.
- SIEM : corrélation Loki → SIEM dédié (Wazuh/Elastic) avec règles de détection
  versionnées.
