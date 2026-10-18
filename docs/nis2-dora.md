# Conformité — NIS2 & DORA (lecture appliquée au démonstrateur)

> Objectif (sujet §3.5) : distinguer ce que le prototype **démontre** des
> exigences réglementaires qui **ne peuvent pas** l'être en 4 jours. Pas de
> rapport de conformité générique : chaque point est relié à l'architecture.

## 1. Cadre

- **NIS2** (directive UE 2022/2555) : cybersécurité des entités essentielles /
  importantes. Gestion des risques, notification d'incidents, gouvernance.
- **DORA** (règlement UE 2022/2554) : résilience opérationnelle numérique du
  secteur financier. ICT risk management, tests de résilience, incidents, tiers.

Une plateforme de paiement relèverait des deux (entité financière = DORA en
priorité, NIS2 en complément).

## 2. Exigences DÉMONTRÉES par le prototype

| Exigence | Article (indicatif) | Preuve dans le démonstrateur |
|----------|--------------------|------------------------------|
| Détection et gestion d'incidents ICT | DORA art. 17 ; NIS2 art. 21.2.b | Détection ML + moteur de remédiation + journalisation des incidents |
| Mécanismes de réponse et de reprise | DORA art. 11 ; NIS2 art. 21.2.c | Playbooks + transaction canari (reprise prouvée) |
| Tests de résilience (scénarios d'attaque) | DORA art. 24-25 | Scripts Red Team reproductibles + chaos (injection de pannes) |
| Journalisation / traçabilité | DORA art. 15 | Loki + corrélation SIEM + horodatage des remédiations |
| Mesures techniques (durcissement, accès) | NIS2 art. 21.2 | WAF/CRS, segmentation réseau, moindre privilège, secrets chiffrés |
| Analyse de risques | NIS2 art. 21.2.a | EBIOS RM (`docs/ebios-rm.md`) |

## 3. Exigences NON démontrables en 4 jours (honnêteté)

| Exigence | Pourquoi hors scope | Ce qu'il faudrait en production |
|----------|---------------------|---------------------------------|
| Notification d'incident sous 24 h/72 h | Processus organisationnel, pas technique | Procédure + canal CSIRT/autorité, registre d'incidents |
| Gouvernance et responsabilité de l'organe de direction | Dimension RH/juridique | Comité des risques ICT, formation dirigeants |
| Gestion du risque lié aux tiers ICT | Pas de fournisseur réel | Registre des contrats, clauses de résilience, audit |
| Tests TLPT (red team avancé, menace réelle) | Nécessite agrément et durée | Campagne TLPT pilotée, scénarios menace-informés |
| Continuité multi-site / BIA complète | Un seul PC Hôte | Analyse d'impact métier, sites de repli, exercices |
| Revue et audit indépendants | — | Audit interne/externe périodique |

## 4. Arbitrages recommandés au commanditaire

1. **Prioriser la détection-réponse automatisée** (fort ROI résilience, déjà
   démontré) avant d'investir dans la couverture réglementaire documentaire.
2. **Passer les secrets sur Vault** et l'inférence sur vLLM/TGI avant mise en
   production (cf. `docs/architecture.md §7`).
3. **Mettre en place le registre d'incidents et la chaîne de notification**
   (exigence DORA/NIS2 non technique mais obligatoire) dès l'industrialisation.
4. **Supprimer le SPOF** (PC Hôte unique) : la reprise autonome gère l'incident
   applicatif, pas la panne matérielle de l'hôte.

## 5. Synthèse

Le démonstrateur prouve la **capacité technique** de détection et de reprise
autonome, cœur de la résilience opérationnelle visée par DORA. Il ne prétend pas
à la conformité réglementaire complète, qui est majoritairement
organisationnelle et pluriannuelle. La valeur livrée est la brique technique
vérifiable sur laquelle une démarche de conformité peut s'appuyer.
