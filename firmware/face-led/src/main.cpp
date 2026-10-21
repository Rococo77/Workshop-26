// Indicateur LED ESP8266 — reconnaissance faciale en temps réel.
//
// Câblage (voir README.md) :
//   D0 -> résistance -> LED verte  -> GND  (vérification réussie)
//   D1 -> résistance -> LED rouge  -> GND  (vérification échouée)
//
// Se connecte en client WebSocket à payment-api (via le WAF) et reçoit un
// message JSON {"ok": bool, "purpose": "login"|"confirm"} à chaque
// vérification faciale réelle (second facteur de connexion, confirmation
// de virement). Aucune action à envoyer : le firmware est purement passif.

#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <WebSocketsClient.h>

#include "secrets.h"

const int LED_GREEN = D0;
const int LED_RED = D1;

// Durée d'affichage d'un résultat avant extinction automatique : évite que
// la LED reste allumée indéfiniment entre deux vérifications. Un nouvel
// événement avant l'échéance la repousse (pas de clignotement parasite).
const unsigned long LED_ON_DURATION_MS = 10000;

WebSocketsClient webSocket;
unsigned long ledOnSince = 0;
bool ledTimerActive = false;

void setLeds(bool ok) {
  digitalWrite(LED_GREEN, ok ? HIGH : LOW);
  digitalWrite(LED_RED, ok ? LOW : HIGH);
  ledOnSince = millis();
  ledTimerActive = true;
}

void ledsOff() {
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_RED, LOW);
  ledTimerActive = false;
}

// Clignotement bref des deux LED : confirme le câblage au démarrage, sans
// dépendre du Wi-Fi ni du serveur.
void startupSelfTest() {
  for (int i = 0; i < 2; i++) {
    digitalWrite(LED_GREEN, HIGH);
    digitalWrite(LED_RED, HIGH);
    delay(200);
    ledsOff();
    delay(200);
  }
}

void onWebSocketEvent(WStype_t type, uint8_t *payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("[ws] connecté à payment-api");
      break;
    case WStype_DISCONNECTED:
      Serial.println("[ws] déconnecté");
      ledsOff(); // pas de statut fiable tant que la connexion n'est pas rétablie
      break;
    case WStype_TEXT: {
      JsonDocument doc;
      if (deserializeJson(doc, payload, length)) {
        Serial.println("[ws] message JSON illisible, ignoré");
        break;
      }
      bool ok = doc["ok"] | false;
      const char *purpose = doc["purpose"] | "?";
      Serial.printf("[ws] purpose=%s ok=%s\n", purpose, ok ? "true" : "false");
      setLeds(ok);
      break;
    }
    default:
      break;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  startupSelfTest();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Connexion Wi-Fi a %s", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.printf("\nWi-Fi connecte, IP=%s\n", WiFi.localIP().toString().c_str());

  // Chemin WAF exact (voir infra/waf/default.conf.template) : /api/ws/face-events.
  webSocket.begin(WS_HOST, WS_PORT, "/api/ws/face-events");
  webSocket.setExtraHeaders("Authorization: Bearer " WS_TOKEN);
  webSocket.onEvent(onWebSocketEvent);
  webSocket.setReconnectInterval(5000);
}

void loop() {
  webSocket.loop();
  // Soustraction non signée : correcte même au rebouclage de millis() (~49 jours).
  if (ledTimerActive && (unsigned long)(millis() - ledOnSince) >= LED_ON_DURATION_MS) {
    ledsOff();
  }
}
