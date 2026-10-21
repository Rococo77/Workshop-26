# PCA / PRA — Plan de Continuité et de Reprise d'Activité

> Adapté à la solution livrée (sujet §3.5). Explicite les scénarios couverts,
> les responsabilités, les choix de restauration et les risques résiduels.

## 1. Services critiques et objectifs

| Service | Criticité | RTO visé (démo) | RPO visé (démo) | Justification |
|---------|-----------|-----------------|-----------------|---------------|
| `payment-api` + PostgreSQL | **Vitale** | < 60 s (autonome) | ~0 (transaction atomique) | Cœur métier : sans lui, aucun paiement |
| `auth` | **Vitale** | < 60 s | 0 | Pas de paiement sans authentification |
| WAF | Essentielle | < 30 s | n/a | Point d'entrée + défense |
| Observabilité (Prom/Loki/Grafana) | Importante | best-effort | perte de fenêtre tolérée | Nécessaire à la détection, pas au métier |
| `rag-assistant` / Ollama | Confort | n/a | n/a | Aide opérateur, non bloquant |

> RTO/RPO industriels : pour une vraie plateforme de paiement, RTO de quelques
> minutes et RPO quasi nul avec réplication synchrone + bascule multi-site.

## 2. Scénarios couverts par la reprise AUTONOME

| Scénario | Détection | Décision | Action | Preuve de reprise |
|----------|-----------|----------|--------|-------------------|
| Déni de service applicatif | ML `dos_flood` (req/s, latence, 429) | Playbook DoS | Blocage IP WAF (+ restart si saturation) | Transaction canari OK |
| Service injoignable (crash) | `up == 0` | Playbook `service_unavailable` | Restart conteneur (allowlist) | Transaction canari OK |
| Tentative d'injection | ML `injection_attempt` (403 CRS) | Playbook injection | Confinement IP + trace | Intégrité service (canari) |

La preuve de reprise n'est **jamais** le simple redémarrage : elle repose sur
l'exécution réussie d'une **transaction canari** de bout en bout.

## 3. PRA manuel — filet de dernier recours

Si la reprise autonome échoue (hors scope démo), procédure manuelle documentée
et automatisée via Ansible (`infra/ansible/ops.yml`) :

1. `ansible-playbook ops.yml -e action=status` — diagnostic.
2. `ansible-playbook ops.yml -e action=restart_api` — relance ciblée.
3. Restauration base : `ansible-playbook backup.yml` (sauvegarde horodatée) puis
   `ansible-playbook restore.yml -e confirm=yes` — **restauration vérifiée** par
   transaction canari (échoue si `/api/ready` ne repasse pas à 200).
4. Reconstruction complète : `ansible-playbook site.yml` (prérequis + déploiement
   + vérifs de posture, idempotent).

> ⚠️ Toute intervention corrective humaine **pendant la démonstration live**
> entraîne ND (0/5) sur l'axe remédiation (sujet §8). Le PRA manuel est un plan
> de secours documenté, pas le mode de reprise nominal.

## 4. Responsabilités (RACI simplifié)

| Activité | Dev | Infra | IA/Data | Cyber | Gouvernance |
|----------|-----|-------|---------|-------|-------------|
| Signaux applicatifs | **R** | C | C | C | I |
| Déploiement / observabilité | C | **R** | I | C | I |
| Modèle de détection | I | C | **R** | C | I |
| Playbooks de remédiation | C | **R** | C | **R** | I |
| Décisions d'arbitrage / RTO-RPO | C | C | C | C | **R/A** |

## 5. Stratégie de restauration

- **État applicatif** : sans état dans les conteneurs métier (12-factor) →
  restauration = redéploiement. L'état vit dans PostgreSQL (volume persistant).
- **Données** : sauvegarde logique `pg_dump` (`backup.yml`, horodatée + rétention)
  et **restauration prouvée** (`restore.yml`, vérifiée par le canari). Industriel :
  PITR (WAL archiving) + réplication streaming + bascule.
- **Secrets** : régénérés/déchiffrés via SOPS/age au déploiement, jamais stockés
  en clair.
- **Configuration** : tout est code (Compose + Ansible) → reconstruction
  reproductible sur une machine propre.

## 6. Risques résiduels après reprise

- DoS distribué (DDoS) : le blocage mono-IP ne suffit pas → anti-DDoS amont.
- Corruption logique des données (au-delà du dernier backup) : perte jusqu'au RPO.
- Compromission persistante (backdoor) : un redémarrage ne nettoie pas →
  réponse à incident + reconstruction depuis sources de confiance.
- Dépendance au PC Hôte unique (SPOF) : pas de haute disponibilité en démo.
