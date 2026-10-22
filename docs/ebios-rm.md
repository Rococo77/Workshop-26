# Analyse de risques — EBIOS Risk Manager

> Périmètre : démonstrateur PROJECT RESILIENCE-ALPHA (plateforme de paiement
> fictive). Méthode EBIOS RM (ANSSI), 5 ateliers. Les valeurs sont calibrées
> pour un **démonstrateur** ; les transpositions industrielles sont signalées.

## Atelier 1 — Cadrage, valeurs métier, biens supports

### Valeurs métier
| ID | Valeur métier | Besoin de sécurité (D/I/C) |
|----|---------------|----------------------------|
| VM1 | Exécution d'une transaction de paiement | **Disponibilité** forte, Intégrité forte |
| VM2 | Authentification des utilisateurs | Intégrité forte, Confidentialité forte |
| VM3 | Traçabilité des opérations (preuve, investigation) | Intégrité forte, Disponibilité moyenne |
| VM4 | Continuité du service (reprise) | Disponibilité forte |

### Biens supports
API métier (`payment-api`), service `auth`, PostgreSQL, WAF, chaîne
d'observabilité, moteur de remédiation, socket Docker, secrets (HashiCorp Vault),
réseau du consortium.

### Événements redoutés
| ID | Événement redouté | Impact | Gravité |
|----|-------------------|--------|---------|
| ER1 | Indisponibilité du service de paiement | Opérations partenaires retardées, perte de confiance | **G4 — Critique** |
| ER2 | Altération/injection sur les données de paiement | Transactions incohérentes, fraude | **G4 — Critique** |
| ER3 | Exfiltration de données (même fictives) | Atteinte confidentialité, image | G3 — Grave |
| ER4 | Élévation de privilèges via l'automate de remédiation | Prise de contrôle de l'hôte | **G4 — Critique** |

## Atelier 2 — Sources de risque / objectifs visés

| SR | Source de risque | Motivation | Objectif visé |
|----|------------------|------------|---------------|
| SR1 | Cybercriminel opportuniste | Gain, nuisance | Interrompre le paiement (rançon/sabotage) |
| SR2 | Attaquant ciblé (concurrent/étatique) | Déstabilisation | Exfiltrer / altérer |
| SR3 | Script-kiddie | Notoriété | Déni de service |
| SR4 | Menace interne / erreur | — | Mauvaise manipulation, abus de privilège |

Couples SR/OV prioritaires retenus : **SR1→ER1** (DoS), **SR2→ER2/ER3**
(injection/exfiltration), **SR1/SR4→ER4** (abus de l'automate).

## Atelier 3 — Scénarios stratégiques

- **SS1 (DoS applicatif)** : saturation de l'API métier depuis le réseau du
  groupe → indisponibilité (ER1). *Chemin* : Internet/LAN → WAF → API.
- **SS2 (Injection)** : injection SQL sur l'authentification / les paramètres
  → altération ou exfiltration (ER2/ER3). *Chemin* : WAF → API → base.
- **SS2ter (Réutilisation de données fuitées)** : un extrait de la base de
  comptes sort (injection réussie, sauvegarde volée, complicité interne) puis
  sert à se connecter ou à viser des IBAN (ER3). *Chemin* : WAF → auth / API.
- **SS3 (Abus de l'automate)** : compromission du moteur de remédiation
  (socket Docker) → élévation de privilèges (ER4). *Chemin* : `app`/`control`.

## Atelier 4 — Scénarios opérationnels (modes opératoires)

| Scénario | Mode opératoire | Vraisemblance |
|----------|-----------------|---------------|
| SS1 | Flood HTTP multi-thread sur `/api/*` jusqu'à saturation CPU/latence | **V3 — Vraisemblable** |
| SS2 | Payloads SQLi (`' OR '1'='1`, UNION, pg_sleep) sur `/auth/login`, `/api/auth/register` | **V3 — Vraisemblable** |
| SS2bis | Credential stuffing / brute force sur `/auth/login` puis `/api/auth/login/face` (second facteur) ; création massive de faux comptes sur `/api/auth/register` | V2 — Possible |
| SS2ter | Rejeu des identifiants et IBAN d'un extrait de `app_user` / `account` (`attack/leak_replay.py`) | V2 — Possible |
| SS3 | Accès au socket Docker, création/execution de conteneur privilégié, pivot | V2 — Possible |

## Atelier 5 — Traitement du risque

| Risque | Mesure(s) mise(s) en œuvre dans le démonstrateur | Risque résiduel |
|--------|--------------------------------------------------|-----------------|
| SS1 (DoS) | Rate limiting WAF, détection ML `dos_flood`, **blocage IP automatique**, canari de reprise | Flood distribué (DDoS) non couvert : nécessiterait anti-DDoS amont |
| SS2 (Injection) | Requêtes **paramétrées**, OWASP CRS (403), détection `injection_attempt`, confinement IP | 0-day CRS ; WAF en contournement si règle manquante |
| SS3 (Abus automate) | Réseau `control` isolé, **allowlist** conteneurs/playbooks, pas d'UI admin exposée, socket non partagé aux services métier | Socket Docker = root-equivalent : en prod, RBAC/Operator + audit |
| SS2bis (Stuffing / faux comptes) | Second facteur visage obligatoire (un mot de passe volé ne suffit pas), zone WAF dédiée 2 req/s (`/api/auth/register`, `/api/auth/login/face`), verrou après 5 échecs/15 min (visage), jeton intermédiaire `face_pending` de ~2 min sans accès métier | Le visage seul n'est pas un secret opposable (deepfake) : anti-spoofing (FasNet) atténue, pas d'authentification « vivante » garantie en démonstrateur |
| ER3 (Exfiltration) | Pagination bornée, auth obligatoire, endpoint interne masqué (404), logs d'investigation ; comptes leurres : une réponse HTTP qui en contient une valeur est bloquée et alerte | Une fuite qui ne touche aucune valeur leurre (extraction ciblée) reste invisible |
| SS2ter (Données fuitées réutilisées) | Comptes leurres : connexion ou virement vers eux = incident `honeytoken_triggered` sans ML, source confinée, actions humaines listées dans le rapport | La fuite n'est vue qu'à sa réutilisation ; l'origine reste à investiguer |

### Mesures transverses
- Moindre privilège (utilisateurs non-root dans les conteneurs, allowlists).
- Secrets centralisés dans HashiCorp Vault (chiffrés au repos, accès par politique, journal d'audit), aucune donnée réelle.
- Traçabilité : logs centralisés (Loki), corrélation SIEM, horodatage des
  remédiations.

### Risques résiduels assumés (démonstrateur, 4 jours)
DDoS volumétrique, 0-day, compromission de la chaîne d'approvisionnement,
sécurité physique du PC Hôte. Ces points relèvent d'un contexte industriel et
sont documentés dans le PCA/PRA et l'analyse NIS2/DORA.
