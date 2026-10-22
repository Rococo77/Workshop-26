# Scripts Red Team — PROJECT RESILIENCE-ALPHA

Scénarios offensifs à exécuter **depuis le PC Attaquant** (poste distinct du PC
Hôte, sujet §4). Cible = l'IP publiée du WAF sur le point d'accès du groupe,
p. ex. `http://192.168.137.1:8080`.

> **Périmètre strict (sujet §3.4 / §9).** Ces actions ne visent QUE le SI fictif
> de l'équipe. Aucune action contre les réseaux du campus, un autre consortium,
> un équipement tiers ou un service Internet. Aucune donnée réelle.

Prérequis : Python 3 (bibliothèque standard uniquement, aucune dépendance).

## Scénarios

| Script | Attaque | Effet attendu | Réponse automatique |
|--------|---------|---------------|---------------------|
| `flood.py --scenario business` (défaut) | DoS sur le **chemin métier** (`/auth/login` + `/api/transactions`) | ↑ req/s, ↑ p95, ↑ `auth_login_failures_total`, 429 | Détection `dos_flood` → blocage IP + **mode dégradé** (virements en file puis rejoués) |
| `flood.py --scenario face` | Force brute sur la **biométrie** (`/api/auth/login/face`) | **Surtout des 429** (zone WAF stricte 2 r/s) | Limite WAF tient, auto-inscription/biométrie résiste |
| `flood.py --scenario health` | Flood léger (`/api/health`) | ↑ req/s (ne touche pas le métier) | Comparaison / sanity-check |
| `sqli.py` | Injection SQL sur l'auth | 403 (CRS), aucune injection réussie | Détection `injection_attempt` → confinement IP |
| `exfil.py` | Accès interne / exfiltration | 404 / 401 / limit borné | Exposition maîtrisée, trace pour investigation |
| `leak_replay.py` | Réutilisation d'identifiants fuités (contient des comptes leurres) | 401 | Détection `honeytoken_triggered` sans ML → blocage IP, rapport d'incident |

## Exemples

```bash
# DoS sur le chemin métier = scénario principal de la démo (défaut)
python3 flood.py --target http://192.168.137.1:8080 --duration 40 --workers 50

# Force brute biométrie : prouve la limite WAF (2 r/s) et la résistance de l'auth faciale
python3 flood.py --target http://192.168.137.1:8080 --scenario face --duration 20

# Injection SQL (résistance applicative + WAF)
python3 sqli.py  --target http://192.168.137.1:8080 --rounds 60

# Tentative d'exfiltration / accès non autorisé
python3 exfil.py --target http://192.168.137.1:8080

# Identifiants issus d'une fuite simulée (déclenche les honeytokens)
python3 leak_replay.py --target http://192.168.137.1:8080
```

## Déroulé de démonstration recommandé (Clip Chrono / live)

1. **Avant** : une transaction réussit depuis le front (service nominal).
2. **Attaque** : lancer `flood.py` (défaut = chemin métier) depuis le PC Attaquant.
3. **Détection** : le score d'anomalie ML grimpe, un incident `dos_flood` est émis.
4. **Remédiation** : l'IP attaquante est bloquée au WAF + passage en **mode dégradé**
   (les virements légitimes sont mis en file pendant la perturbation).
5. **Vérification** : transaction canari OK → la file est rejouée → une nouvelle
   transaction réussit.

Aucune intervention corrective humaine entre les étapes 2 et 5.
