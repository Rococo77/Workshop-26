# ============================================================================
#  HashiCorp Vault — coffre des secrets de la plateforme (sujet §3.4).
#  Nœud unique, stockage fichier chiffré sur volume (vault-data).
#  Publié UNIQUEMENT sur 127.0.0.1 (jamais sur le réseau du groupe, §4).
#  Démonstrateur : pas de TLS (trafic local au PC Hôte). Production : TLS,
#  stockage Raft multi-nœuds, auto-unseal (KMS/HSM), voir docs/vault.md.
# ============================================================================
storage "file" {
  path = "/vault/file"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

api_addr      = "http://127.0.0.1:8200"
ui            = true
# Pas de capability IPC_LOCK (cap_drop ALL) : mlock désactivé. Production :
# réactiver mlock (ou désactiver le swap de l'hôte).
disable_mlock = true
