# Indicateur LED ESP8266 — reconnaissance faciale en temps réel

Démo bonus, hors des 5 domaines notés du sujet. Un ESP8266 (module ESP-12F,
ex. carte AZ-Delivery NodeMCU, détecté via son adaptateur USB CH340) se
connecte en WebSocket à `payment-api` (via le WAF) et pilote la LED à chaque
étape d'une vérification réelle : login client (`POST /api/auth/login/face`
puis `/password`, §10.1) ou confirmation de virement
(`POST /api/transactions/{id}/confirm`).

## Câblage

```
ESP8266 D0 ──[résistance ~220-330 Ω]── LED verte (anode) ── LED verte (cathode) ── GND
ESP8266 D1 ──[résistance ~220-330 Ω]── LED rouge (anode) ── LED rouge (cathode) ── GND
```

Une résistance série est indispensable (non mentionnée dans le câblage
initial) : sans elle, le courant n'est pas limité et la LED et/ou la broche
GPIO (3,3 V) peuvent être endommagées.

### 5 états (§10.1)

Le serveur pousse `{"purpose": "login"|"confirm", "state": ...}` à chaque
étape ; la carte ne renvoie jamais rien (purement passive).

| `state`    | LED                        | Déclenché par |
|------------|----------------------------|---------------|
| `idle`     | Éteinte                    | Repos, ou visage reconnu mais login pas encore complet (mot de passe à venir) |
| `checking` | Verte clignotante          | Une image/un mot de passe vient d'être soumis, en cours de vérification |
| `ok`       | Verte fixe, **30 s**       | Connexion ou virement confirmé avec succès |
| `fail`     | Rouge clignotante, **10 fois** puis éteinte | Visage non reconnu, mot de passe incorrect, spoof détecté |
| `locked`   | Rouge fixe, **30 s**       | Verrou anti-force-brute atteint (2 tentatives au total pour le login, §10.1) ou compte verrouillé |

- Pas de connexion WebSocket (Wi-Fi coupé, backend indisponible) → LED
  éteinte (pas de statut fiable à afficher).
- Au démarrage : les deux LED clignotent deux fois (auto-test de câblage,
  indépendant du Wi-Fi/serveur), puis état `idle`.
- Machine à états non bloquante (`millis()`, pas de `delay()` dans `loop()`)
  pour ne jamais geler `webSocket.loop()`.

## Configuration

```bash
cp include/secrets.example.h include/secrets.h
```
Éditer `include/secrets.h` :
- `WIFI_SSID` / `WIFI_PASSWORD` : réseau Wi-Fi (2,4 GHz — l'ESP8266 ne gère
  pas le 5 GHz).
- `WS_HOST` / `WS_PORT` : IP du PC Hôte et port publié par le WAF
  (`EDGE_PORT` du `.env` du dépôt principal ; 8080 par défaut, 192.168.137.1
  le jour de la démo jury).
- `WS_TOKEN` : doit être identique à `ESP_EVENTS_TOKEN` dans le `.env` du
  dépôt principal.

`include/secrets.h` est ignoré par git (comme `.env`) : ne jamais le
committer.

## Build & flash

Depuis ce dossier (`firmware/face-led/`), en ligne de commande (voie utilisée
et vérifiée — **PlatformIO Core seul**, sans CLion) :
```bash
pio run                              # compile
pio run -t upload --upload-port COM5 # flashe (adapter le port série)
pio device monitor -b 115200         # logs (Wi-Fi, connexion WS, messages reçus)
```
Le sujet mentionne CLion + PlatformIO comme outillage imposé, mais le plugin
**PlatformIO for CLion** n'a pas pu être mis en route ici ; PlatformIO Core
(`pio`) reste la voie qui fonctionne réellement, utilisée pour tous les
builds/flashs de ce projet. Point à signaler tel quel (voir le mode
opératoire de restitution, §10.1/1.6).

## Vérification

1. La plateforme principale doit tourner (`docker compose up -d`) et le WAF
   joignable depuis le réseau Wi-Fi de l'ESP8266 (même réseau que
   `WS_HOST`/`WS_PORT`).
2. `pio device monitor` doit afficher `[ws] connecté à payment-api`.
3. Se connecter dans le front avec un compte enrôlé (mot de passe + visage) :
   LED verte clignotante pendant la vérification du visage, puis à nouveau
   pendant le mot de passe, puis verte fixe 30 s à la connexion réussie.
   Tenter une connexion avec un visage différent → rouge clignotante 10 fois.
   Épuiser les tentatives (2 au total, §10.1) → rouge fixe 30 s.
4. Confirmer un virement par le visage → même logique (`checking`/`ok`/`fail`/
   `locked`), seuils différents (5 échecs / 15 min, inchangés).

## Dépannage

- **Rien sur la carte après upload** : vérifier qu'aucun autre programme
  (CLion, Arduino IDE, un autre `pio device monitor`) ne tient déjà le port
  série — un seul processus peut l'ouvrir à la fois.
- **`pio run -t upload` reste bloqué sans rien afficher** (Windows + projet
  ouvert depuis WSL, chemin `\\wsl.localhost\...`) : le pont réseau
  WSL↔Windows peut faire traîner indéfiniment PlatformIO. Copier le dossier
  vers un chemin Windows natif (ex. `%USERPROFILE%\face-led-build`) et
  lancer `pio run -t upload` depuis là résout le problème.
- **L'ESP se connecte au Wi-Fi mais jamais au WebSocket** (`[ws] déconnecté`
  en boucle) : le pare-feu Windows du PC Hôte bloque souvent les connexions
  entrantes sur les réseaux classés *Public*. Autoriser le port du WAF en
  entrée (PowerShell **administrateur**) :
  ```powershell
  New-NetFirewallRule -DisplayName "Resilience-Alpha WAF" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
  ```
  (adapter `8080` à `EDGE_PORT` si modifié dans le `.env` du dépôt principal).
