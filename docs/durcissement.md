# Durcissement & moindre privilège des conteneurs

> PROJECT RESILIENCE-ALPHA — volet Cybersécurité (sujet §3.4).
> Ce document décrit la posture de sécurité **réellement appliquée** dans
> [`docker-compose.yml`](../docker-compose.yml) : réduction des privilèges de
> chaque conteneur et confinement de la surface la plus sensible (le moteur de
> remédiation). Il alimente le `Workshop2026-M2-G<n>-Dossier.pdf`.

---

## 1. Principe

Le sujet insiste sur deux points (§3.4) :

- les privilèges accordés aux services doivent être **maîtrisés** ;
- le **moteur de remédiation**, qui agit sur les conteneurs, dispose de droits
  élevés : c'est une **surface d'attaque critique** et il ne faut pas introduire,
  par facilité, une interface d'administration accessible à n'importe quel
  composant.

Notre réponse applique le **moindre privilège** à trois niveaux, sur **tous** les
conteneurs, puis isole spécifiquement le moteur de remédiation.

---

## 2. Socle appliqué à tous les conteneurs

Défini une seule fois via l'ancre YAML `x-sec` et fusionné dans chaque service :

| Mesure | Effet | Portée |
|---|---|---|
| `security_opt: no-new-privileges` | Empêche l'escalade de privilèges via un binaire *setuid* | **15/15 conteneurs** |
| `cap_drop: ALL` | Aucune *capability* Linux par défaut | **15/15 conteneurs** |
| `pids_limit` | Plafond de processus → anti *fork-bomb*, limite l'effet d'un flood/DoS | tous les services applicatifs |
| Utilisateur **non-root** | Le processus ne tourne pas en `root` | 12/15 (voir §5) |

Seuls les services qui en ont un besoin **démontré** récupèrent des droits, et
uniquement ceux-là :

- **postgres** : son point d'entrée démarre en `root` puis bascule vers
  l'utilisateur `postgres` (gosu) et ajuste les droits de `PGDATA`. Il reçoit les
  **5 capabilities strictement nécessaires** : `CHOWN`, `DAC_OVERRIDE`, `FOWNER`,
  `SETGID`, `SETUID`. Rien de plus.

---

## 3. Rootfs en lecture seule

Les services Python exposés au trafic (surface d'attaque) tournent avec un
**système de fichiers racine en lecture seule** (`read_only: true`), un `tmpfs`
sur `/tmp` étant le **seul** chemin inscriptible :

`auth`, `payment-api`, `ml-detector`, `supervision-bff`, `waf-metrics`,
`remediation-engine`.

Aucun de ces services n'écrit sur son disque au fonctionnement normal
(`PYTHONDONTWRITEBYTECODE` est positionné à la construction ; les écritures
légitimes vont dans un **volume** monté `rw`, p. ex. la blocklist pour la
remédiation ou le journal WAF pour `waf-metrics`). Une écriture sur `/` est donc
**refusée** (*Read-only file system*).

---

## 4. Confinement du moteur de remédiation (surface critique)

Le moteur de remédiation doit pouvoir **redémarrer** des conteneurs et
**recharger** le WAF. Historiquement, il montait le **socket Docker brut**
(`/var/run/docker.sock`) en `root` — soit, en pratique, un **accès root au PC
Hôte** (création de conteneur privilégié, montage de volume hôte, etc.).

### 4.1 Proxy Docker filtrant

On intercale un **`docker-socket-proxy`** (image `tecnativa/docker-socket-proxy`)
entre le moteur et le socket :

```
remediation-engine ──TCP──▶ docker-socket-proxy ──(socket ro)──▶ Docker Engine
   (uid 101, non-root)         filtre les appels API
```

- Le moteur **ne monte plus** le socket Docker. Il parle au proxy en TCP
  (`DOCKER_HOST=tcp://docker-socket-proxy:2375`), sur le réseau **`control`**
  interne (jamais publié).
- Le proxy n'autorise **que** les sections d'API nécessaires :
  - `CONTAINERS` → inspecter / lister / lire les logs / **redémarrer** ;
  - `EXEC` → exécuter `nginx -s reload` dans le WAF ;
  - `POST` → autoriser ces écritures.
- **Tout le reste est refusé** : `IMAGES`, `VOLUMES`, `NETWORKS`, `BUILD`,
  `COMMIT`, `INFO`, `SWARM`, `SECRETS`… → même compromis, l'attaquant **ne peut
  pas** créer un conteneur privilégié, monter un volume hôte ni tirer une image.
- Le socket est monté **en lecture seule** dans le proxy.

**Preuve reproductible** (depuis le conteneur de remédiation) :

| Appel | Attendu | Observé |
|---|---|---|
| `containers.get("ra-waf")` | autorisé | OK (`running`) |
| `waf.logs()` | autorisé | OK |
| `waf.exec_run(["nginx","-t"])` | autorisé | `exit=0` |
| `images.list()` | **refusé** | **HTTP 403** |
| `containers.create("alpine")` | **refusé** | **HTTP 404** |

### 4.2 Moteur non-root, sans capability

Le moteur de remédiation tourne désormais sous l'**uid 101** — le propriétaire du
volume `waf-dynamic` (c'est aussi l'uid `nginx` du WAF). Conséquences :

- il écrit la blocklist **en tant que propriétaire**, sans aucune *capability*
  (pas besoin de `DAC_OVERRIDE`), et le fichier produit est directement lisible
  par nginx (même uid) ;
- il n'est **plus root**, n'a **plus** le socket Docker, a un **rootfs en lecture
  seule** et **zéro capability**.

> **Piège évité (à souligner).** `cap_drop: ALL` retire `DAC_OVERRIDE` même à
> `root`. Tant que le moteur tournait en `root`, il ne pouvait alors **plus
> écrire** la blocklist (volume possédé par l'uid 101) — le blocage d'IP aurait
> échoué **silencieusement**. Le faire tourner sous l'uid propriétaire du volume
> corrige le problème **et** rend le service non-root d'un même geste, sans
> réintroduire de capability.

---

## 5. Matrice de la posture (état réel vérifié)

| Conteneur | UID | read-only | no-new-priv | Capabilities |
|---|---|:--:|:--:|---|
| auth | 10001 | ✔ | ✔ | — |
| payment-api | 10001 | ✔ | ✔ | — |
| ml-detector | 10002 | ✔ | ✔ | — |
| supervision-bff | 10003 | ✔ | ✔ | — |
| waf-metrics | 10005 | ✔ | ✔ | — |
| **remediation-engine** | **101** | ✔ | ✔ | — |
| waf | 101 | — | ✔ | — |
| frontend | 101 | — | ✔ | — |
| face-api | 10001 | — | ✔ | — |
| grafana | 472 | — | ✔ | — |
| loki | 10001 | — | ✔ | — |
| prometheus | 65534 | — | ✔ | — |
| promtail | 0 | — | ✔ | — |
| docker-socket-proxy | 0 | — | ✔ | — |
| postgres | 0 → postgres | — | ✔ | CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID |

*(Promtail et docker-socket-proxy tournent en `root` car leurs images l'imposent,
mais sans aucune capability ni possibilité d'escalade. Promtail n'accède au
socket Docker qu'en **lecture seule**, pour la seule découverte des conteneurs.)*

---

## 6. Limites connues & pistes

- `read_only` n'est pas encore appliqué à **waf**, **frontend** et **promtail** :
  ces images écrivent dans plusieurs chemins (caches nginx, *templating* CRS,
  positions Promtail) qui exigeraient autant de `tmpfs`. Gain moindre, réglage
  plus lourd — candidat à une itération ultérieure.
- **promtail** et **docker-socket-proxy** restent `root` (contrainte d'image) ;
  le risque est borné (aucune capability, socket en lecture seule pour l'un,
  surface réduite au strict minimum pour l'autre).

---

## 7. Vérification rapide

```bash
# Posture de tous les conteneurs (uid / read-only / no-new-priv / caps)
for c in $(docker compose ps --format '{{.Name}}'); do
  echo "$c:" \
    "uid=$(docker exec "$c" id -u 2>/dev/null)" \
    "ro=$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$c")" \
    "drop=$(docker inspect -f '{{.HostConfig.CapDrop}}' "$c")"
done
```
