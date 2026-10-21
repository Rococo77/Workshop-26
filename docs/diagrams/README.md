# Schémas d'architecture (draw.io)

Sources éditables avec [draw.io / diagrams.net](https://app.diagrams.net).
Le lien « draw.io » ouvre le fichier de la branche `dev` directement dans
l'éditeur (dépôt privé : autoriser l'accès GitHub de draw.io à la première
ouverture).

| Schéma | Pages | Ouvrir |
|---|---|---|
| [Architecture technique](architecture.drawio) | conteneurs, 7 réseaux, flux métier, boucle détection → remédiation, biométrie, Vault, ESP8266 | [draw.io](https://app.diagrams.net/#HRococo77%2FWorkshop-26%2Fdev%2Fdocs%2Fdiagrams%2Farchitecture.drawio) |
| [Vue client](architecture-client.drawio) | version non technique pour le client et le jury | [draw.io](https://app.diagrams.net/#HRococo77%2FWorkshop-26%2Fdev%2Fdocs%2Fdiagrams%2Farchitecture-client.drawio) |
| [Réseaux](reseaux.drawio) | topologie physique (PC Hôte, point d'accès RESILIENCE-G1, PC Attaquant, ESP8266) · matrice conteneurs × réseaux | [draw.io](https://app.diagrams.net/#HRococo77%2FWorkshop-26%2Fdev%2Fdocs%2Fdiagrams%2Freseaux.drawio) |
| [Incident](incident.drawio) | séquence attaque → détection → remédiation → preuve canari · arbre des 3 playbooks | [draw.io](https://app.diagrams.net/#HRococo77%2FWorkshop-26%2Fdev%2Fdocs%2Fdiagrams%2Fincident.drawio) |
| [Authentification](authentification.drawio) | inscription (pool de 5 empreintes) · connexion mot de passe + visage · virement validé par le visage | [draw.io](https://app.diagrams.net/#HRococo77%2FWorkshop-26%2Fdev%2Fdocs%2Fdiagrams%2Fauthentification.drawio) |
| [Secrets et déploiement](secrets-deploiement.drawio) | Vault · chaîne Ansible (site.yml, sauvegarde, restauration) · pipeline CI/CD | [draw.io](https://app.diagrams.net/#HRococo77%2FWorkshop-26%2Fdev%2Fdocs%2Fdiagrams%2Fsecrets-deploiement.drawio) |

Documents qui s'appuient sur ces schémas : [architecture](../architecture.md),
[Vault](../vault.md), [Ansible](../ansible.md), [CI/CD](../CICD.md),
[runbook](../runbook.md).
