# Politique du déploiement : LECTURE SEULE des secrets de la plateforme.
# Utilisée par le jeton de rendu (scripts/vault.sh render, Ansible deploy.yml).
# Ni écriture, ni accès aux autres chemins, ni gestion du coffre.
path "secret/data/resilience-alpha" {
  capabilities = ["read"]
}
