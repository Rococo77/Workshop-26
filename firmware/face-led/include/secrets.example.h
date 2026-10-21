// Copier en `secrets.h` (ignoré par git, voir .gitignore) et renseigner.
#pragma once

#define WIFI_SSID "mon-reseau-wifi"
#define WIFI_PASSWORD "mon-mot-de-passe-wifi"

// IP/hôte du WAF (PC Hôte) et port publié (EDGE_PORT, .env — 8080 par défaut).
// Démo jury : IP du PC Hôte sur le réseau du groupe (ex. 192.168.137.1).
#define WS_HOST "192.168.137.1"
#define WS_PORT 8080

// Doit correspondre à ESP_EVENTS_TOKEN (.env du dépôt principal).
#define WS_TOKEN "change_me_esp_events_token"
