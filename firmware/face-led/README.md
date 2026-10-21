# Indicateur LED ESP8266 — reconnaissance faciale en temps réel

Démo bonus, hors des 5 domaines notés du sujet. Un ESP8266 (module ESP-12F,
ex. carte AZ-Delivery NodeMCU, détecté via son adaptateur USB CH340) se
connecte en WebSocket à `payment-api` (via le WAF) et allume la LED verte ou
rouge à chaque vérification faciale réelle (second facteur de connexion
`POST /api/auth/login/face`, confirmation de virement
`POST /api/transactions/{id}/confirm`).

## Câblage

```
ESP8266 D0 ──[résistance ~220-330 Ω]── LED verte (anode) ── LED verte (cathode) ── GND
ESP8266 D1 ──[résistance ~220-330 Ω]── LED rouge (anode) ── LED rouge (cathode) ── GND
```

Une résistance série est indispensable (non mentionnée dans le câblage
initial) : sans elle, le courant n'est pas limité et la LED et/ou la broche
GPIO (3,3 V) peuvent être endommagées.

- Succès (`ok: true`) → verte allumée, rouge éteinte.
- Échec (`ok: false`, visage différent ou spoof détecté) → rouge allumée, verte éteinte.
- Pas de connexion WebSocket (Wi-Fi coupé, backend indisponible) → les deux
  LED s'éteignent (pas de statut fiable à afficher).
- Au démarrage : les deux LED clignotent deux fois (auto-test de câblage,
  indépendant du Wi-Fi/serveur).

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

Depuis ce dossier (`firmware/face-led/`) :
```bash
pio run                              # compile
pio run -t upload --upload-port COM5 # flashe (adapter le port série)
pio device monitor -b 115200         # logs (Wi-Fi, connexion WS, messages reçus)
```
Ou depuis CLion, une fois le plugin **PlatformIO for CLion** installé et
lié à l'exécutable `pio` (voir configuration locale) : ouvrir ce dossier
comme projet PlatformIO.

## Vérification

1. La plateforme principale doit tourner (`docker compose up -d`) et le WAF
   joignable depuis le réseau Wi-Fi de l'ESP8266 (même réseau que
   `WS_HOST`/`WS_PORT`).
2. `pio device monitor` doit afficher `[ws] connecté à payment-api`.
3. Se connecter dans le front avec un compte enrôlé (mot de passe + visage)
   → la LED verte s'allume. Tenter une connexion avec un visage différent
   → la LED rouge s'allume.
4. Confirmer un virement par le visage → même comportement.
