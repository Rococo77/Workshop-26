// Indicateur LED ESP8266 — reconnaissance faciale en temps réel.
//
// Câblage (voir README.md) :
//   D0 -> résistance -> LED verte  -> GND  (vérification réussie)
//   D1 -> résistance -> LED rouge  -> GND  (vérification échouée)
//
// Se connecte en client WebSocket à payment-api (via le WAF) et reçoit un
// message JSON {"purpose": "login"|"confirm", "state": "idle"|"checking"|
// "ok"|"fail"|"locked"} à chaque étape d'une vérification réelle (second
// facteur de connexion, confirmation de virement). Aucune action à
// envoyer : le firmware est purement passif, 5 états (§10.1) :
//   idle     éteinte                      — rien en cours
//   checking vert clignotant              — visage/mot de passe en cours de vérification
//   ok       vert fixe 30 s               — connexion/virement confirmé
//   fail     rouge clignotant x10 puis off — tentative refusée (pas un blocage)
//   locked   rouge fixe 30 s              — verrou anti-force-brute atteint

#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <WebSocketsClient.h>
#include <string.h>

#include "secrets.h"

const int LED_GREEN = D0;
const int LED_RED = D1;

const unsigned long BLINK_PERIOD_MS = 300;    // vert/rouge clignotants
const unsigned long FIXED_DURATION_MS = 30000; // vert fixe (ok), rouge fixe (locked)
const int FAIL_BLINK_COUNT = 10;               // nombre de clignotements rouges (fail)

enum LedState { LED_IDLE, LED_CHECKING, LED_OK, LED_FAIL, LED_LOCKED };

WebSocketsClient webSocket;
LedState ledState = LED_IDLE;
unsigned long stateStartedAt = 0;
unsigned long lastBlinkToggleAt = 0;
bool blinkOn = false;
int failBlinksDone = 0;

void setLeds(bool green, bool red) {
  digitalWrite(LED_GREEN, green ? HIGH : LOW);
  digitalWrite(LED_RED, red ? HIGH : LOW);
}

// Point d'entrée unique de tout changement d'état : (ré)initialise le
// chronométrage pour que `updateLeds()` reparte sur des bases propres,
// quel que soit l'état précédent (évite un clignotement "décalé" si un
// nouvel événement interrompt un cycle en cours).
void enterState(LedState next) {
  ledState = next;
  stateStartedAt = millis();
  lastBlinkToggleAt = stateStartedAt;
  blinkOn = true;
  failBlinksDone = 0;
  switch (next) {
    case LED_IDLE:
      setLeds(false, false);
      break;
    case LED_CHECKING:
      setLeds(true, false);
      break;
    case LED_OK:
      setLeds(true, false);
      break;
    case LED_FAIL:
      setLeds(false, true);
      break;
    case LED_LOCKED:
      setLeds(false, true);
      break;
  }
}

// Appelée à chaque tour de `loop()` : fait progresser clignotements et
// durées d'affichage sans jamais bloquer (pas de `delay()`), pour ne pas
// geler `webSocket.loop()`. Soustractions non signées : correctes même au
// rebouclage de millis() (~49 jours).
void updateLeds() {
  unsigned long now = millis();
  switch (ledState) {
    case LED_IDLE:
      break;
    case LED_OK:
    case LED_LOCKED:
      if ((unsigned long)(now - stateStartedAt) >= FIXED_DURATION_MS) {
        enterState(LED_IDLE);
      }
      break;
    case LED_CHECKING:
      if ((unsigned long)(now - lastBlinkToggleAt) >= BLINK_PERIOD_MS) {
        blinkOn = !blinkOn;
        setLeds(blinkOn, false);
        lastBlinkToggleAt = now;
      }
      break;
    case LED_FAIL:
      if ((unsigned long)(now - lastBlinkToggleAt) >= BLINK_PERIOD_MS) {
        blinkOn = !blinkOn;
        setLeds(false, blinkOn);
        lastBlinkToggleAt = now;
        if (!blinkOn) {  // un clignotement complet (allumé -> éteint) de fait
          failBlinksDone++;
          if (failBlinksDone >= FAIL_BLINK_COUNT) {
            enterState(LED_IDLE);
          }
        }
      }
      break;
  }
}

// Clignotement bref des deux LED : confirme le câblage au démarrage, sans
// dépendre du Wi-Fi ni du serveur.
void startupSelfTest() {
  for (int i = 0; i < 2; i++) {
    setLeds(true, true);
    delay(200);
    setLeds(false, false);
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
      enterState(LED_IDLE); // pas de statut fiable tant que la connexion n'est pas rétablie
      break;
    case WStype_TEXT: {
      JsonDocument doc;
      if (deserializeJson(doc, payload, length)) {
        Serial.println("[ws] message JSON illisible, ignoré");
        break;
      }
      const char *purpose = doc["purpose"] | "?";
      const char *state = doc["state"] | "idle";
      Serial.printf("[ws] purpose=%s state=%s\n", purpose, state);
      if (strcmp(state, "checking") == 0) enterState(LED_CHECKING);
      else if (strcmp(state, "ok") == 0) enterState(LED_OK);
      else if (strcmp(state, "fail") == 0) enterState(LED_FAIL);
      else if (strcmp(state, "locked") == 0) enterState(LED_LOCKED);
      else enterState(LED_IDLE);
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
  enterState(LED_IDLE);

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
  updateLeds();
}
