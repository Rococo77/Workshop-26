# Mode opératoire — mise en conformité §10.1 et rendus Workshop2026-M2-G<n>

> Document de pilotage, pas une spec figée : les cases à cocher valent preuve d'avancement.
> Hypothèse non vérifiée par moi : le libellé exact du §10.1 vient de ton relevé (Sujet.md
> est gitignored, je ne l'ai pas lu). Si un point ci-dessous ne correspond pas au texte réel
> du sujet, corrige la case concernée avant de coder dessus.

## 0. Pré-requis avant de commencer

- [x] Numéro de groupe : **1**. Ajouté comme variable `NUM_GROUPE` dans `.env`/`.env.example`,
      propagé en build-arg `VITE_NUM_GROUPE` (`docker-compose.yml` service `frontend`,
      `services/frontend/Dockerfile`), affiché dans le front (`GroupBadge` dans
      `services/frontend/src/App.jsx` et badge équivalent dans `Supervision.jsx`) — vérifié
      par un build Vite local, la valeur est bien embarquée dans le bundle et proprement
      éliminée si la variable est absente. Les noms de fichiers de rendu (`<n>`) et le SSID
      Wi-Fi restent à remplacer manuellement par `1` au moment de produire les rendus /
      flasher l'ESP8266 (pas automatisé, pas le même mécanisme).
- [ ] Relire le §10.1 du Sujet.md original et confirmer les 5 écarts ci-dessous mot pour mot
      (ordre des facteurs, comportement en cas d'échec, seuils de blocage, écran back-office,
      états LED). **Reporté à plus tard (décision explicite).**
- [x] Gel du code confirmé : **aujourd'hui 22/10/2026 à 17h**. C'est donc une échéance du jour
      même, pas dans une semaine — la Phase 1 (§10.1) est pourtant explicitement reportée
      (« on fait ça après ») : à ce stade le zip/dossier/slides produits avant 17h ne pourront
      pas refléter la mise en conformité §10.1 si elle n'est pas faite d'ici là.

---

## Phase 1 — Mise en conformité §10.1 (front, auth, payment-api, firmware)

Ordre interne recommandé : **auth → payment-api → firmware → frontend**, parce que le
frontend ne fait qu'afficher ce que l'API renvoie ; le modifier avant que le backend soit
conforme produirait un flux qui *a l'air* correct sans l'être.

### 1.1 — Ordre des facteurs : identifiant → caméra → visage → mot de passe

- **Écart actuel** : `services/auth/app/main.py:55-96` valide le mot de passe en premier
  (`verify_password`) et ne renvoie `pending_face` qu'après — donc *mot de passe avant visage*,
  l'inverse de la consigne.
- **Impact** : c'est un changement de contrat d'API (`POST /login` ne doit plus accepter de
  mot de passe au premier appel pour un `customer`), donc ça touche aussi `services/payment-api`
  (qui vérifie le visage via `POST /auth/login/face`, cf. `config.py:33-47`) et le frontend
  (`services/frontend/src/App.jsx`, formulaire `submitPassword` ligne 84).
- **Actions** :
  - [ ] Définir le nouveau contrat : `POST /auth/login/identify` (identifiant seul) → déclenche
        l'ouverture caméra côté client → `POST /auth/login/face` (vérif visage) → si OK,
        `POST /auth/login/password` (mot de passe) → jeton final.
  - [ ] Adapter `services/auth/app/main.py` et `services/auth/app/security.py` pour scinder
        la création du jeton intermédiaire (après visage, plus après mot de passe).
  - [ ] Adapter `services/payment-api` si c'est lui qui orchestre l'appel à `face-api` (vérifier
        qui appelle qui — actuellement c'est payment-api qui parle à face-api, pas auth).
  - [ ] Adapter `services/frontend/src/App.jsx` : écran 1 = identifiant seul, écran 2 = caméra,
        écran 3 = mot de passe (seulement si écran 2 OK).
  - [ ] Test E2E à mettre à jour en conséquence (voir dossier de tests existant).

### 1.2 — Visage non reconnu : identifiant vidé + caméra coupée

- **Écart actuel** : absent du code (aucune route ni logique ne réinitialise l'identifiant ou
  ne coupe le flux caméra après un échec de reconnaissance).
- **Actions** :
  - [ ] Côté API : sur échec de vérification faciale, ne pas renvoyer de jeton réutilisable
        (déjà le cas) — mais surtout, décider si l'API doit explicitement invalider la session
        d'identification en cours (le jeton `face_pending` expire déjà à 120 s,
        `services/payment-api/app/config.py:24` — à vérifier si ça suffit pour "l'identifiant
        est remis à vide" ou s'il faut un signal explicite consommé côté front).
  - [ ] Côté frontend : sur réponse d'échec facial, vider le champ identifiant (`setUsername("")`)
        et arrêter le flux `getUserMedia` (stopper les tracks de la caméra), revenir à l'écran 1.
  - [ ] Vérifier que le firmware ESP8266 reçoit aussi l'événement d'échec (il le reçoit déjà,
        `onWebSocketEvent`, `firmware/face-led/src/main.cpp:55-79`) — cohérent avec 1.5.

### 1.3 — Seuils de blocage : 2 tentatives puis 5 min (au lieu de 5 puis 15 min)

- **Écart actuel** : `services/payment-api/app/config.py:46-47`
  `face_lockout_failures: int = 5`, `face_lockout_minutes: int = 15`.
- **Action** :
  - [ ] Changer en `face_lockout_failures: int = 2`, `face_lockout_minutes: int = 5`.
  - [ ] Vérifier qu'il n'y a pas d'autre endroit qui duplique ces valeurs (tests, `.env.example`,
        Grafana/alerting si un seuil est câblé en dur côté dashboard SIEM).
  - [ ] Mettre à jour les tests qui dépendent de ces constantes (ex. tests de brute force E2E).
  - [ ] Clarifier avec le sujet si "2 tentatives au total" compte le mot de passe + le visage
        ensemble ou seulement le visage — ça change l'implémentation (compteur unique vs
        compteur par facteur).

### 1.4 — Écran back-office : administration reconnaissance faciale + habilitations

- **Écart actuel** : aucun composant trouvé (`grep -ri admin services/frontend/src` ne remonte
  que `api.js`, `App.jsx`, `Supervision.jsx` — tous liés à la supervision incident, pas à
  l'administration des utilisateurs/visages). Les rôles `operator`/`admin` n'ont qu'une vue
  supervision.
- **Actions** (le plus gros morceau — à chiffrer en premier pour la suite du planning) :
  - [ ] Définir le périmètre minimal exigé par le sujet : lister/désenrôler un visage,
        activer/désactiver un compte, changer une habilitation (rôle) ? (à confirmer via §10.1).
  - [ ] Ajouter les routes API nécessaires côté `payment-api` ou `face-api` (lister les visages
        enrôlés, révoquer, changer un rôle) — probablement déjà protégées par JWT role=admin.
  - [ ] Ajouter un écran React (nouvelle route, garde par rôle `admin`/`operator`) dans
        `services/frontend/src`, réutilisant les patterns existants de `Supervision.jsx`.
  - [ ] Écrire au moins un test E2E qui couvre ce nouvel écran.

### 1.5 — LED ESP8266 en 5 états

- **Écart actuel** : `firmware/face-led/src/main.cpp` n'a que deux états fixes (vert/rouge,
  10 s, `LED_ON_DURATION_MS`, ligne 24) sans clignotement, et rien n'est émis pour l'étape
  mot de passe.
- **États cibles** (à confirmer précisément avec le §10.1, formulation du relevé) :
  1. Éteinte (repos)
  2. Vert clignotant (en cours de vérification / attente)
  3. Vert fixe 30 s (succès)
  4. Rouge clignotant ×10 (échec, nombre de clignotements fini)
  5. Rouge fixe 30 s (blocage / échec terminal)
- **Actions** :
  - [ ] Étendre le protocole WebSocket `payment-api` → ESP8266 : le JSON `{"ok": bool,
        "purpose": ...}` actuel ne suffit pas à distinguer 5 états ; ajouter un champ genre
        `"state": "idle"|"checking"|"ok"|"fail"|"locked"`.
  - [ ] Réécrire `setLeds`/`loop()` dans `main.cpp` pour gérer blink (vert clignotant continu,
        rouge clignotant ×10 puis extinction, durées 30 s pour les fixes) sans bloquer
        `webSocket.loop()` (pas de `delay()` long dans `loop()`, utiliser un état-machine
        non bloquante comme déjà fait pour `ledTimerActive`).
  - [ ] Propager l'événement "mot de passe" si le nouvel ordre des facteurs (1.1) en a besoin.
  - [ ] Mettre à jour `firmware/face-led/README.md` (câblage/comportement) en conséquence.

### 1.6 — Points à vérifier sur place (pas du code à écrire, de la vérification physique)

- [ ] **Wi-Fi ESP8266** : confirmer sur le terrain que `firmware/face-led/include/secrets.h`
      pointe vers le SSID `RESILIENCE-G<n>` attendu (fichier volontairement gitignored —
      `firmware/*/include/secrets.h` dans `.gitignore` — donc à vérifier en lecture directe sur
      la carte/le poste de flash, pas dans le dépôt).
  - [ ] Vérifier aussi que `secrets.example.h` documente bien le format attendu pour un
        relecteur qui n'a pas accès au vrai `secrets.h`.
- [ ] **Outils imposés (CLion + PlatformIO)** : `firmware/face-led/platformio.ini` existe déjà.
      Préparer une démo courte (ouvrir le projet dans CLion avec le plugin PlatformIO, build +
      upload depuis l'IDE) à montrer pendant la recette ou le live, pas seulement en ligne de
      commande (`make flash-esp` existe déjà, Makefile:41, mais ne prouve pas l'usage de
      l'IDE imposé).

---

## Phase 2 — Recette sur le hotspot (jeudi) + clip chrono

À faire une fois la Phase 1 posée (au moins 1.1 à 1.3 et 1.5, qui touchent le flux filmé).

- [ ] Monter le hotspot, connecter tous les postes (PC Attaquant, serveur, ESP8266) dessus —
      confirmer que le SSID correspond à `RESILIENCE-G<n>` (lien avec 1.6).
- [ ] Dérouler une recette fonctionnelle complète : inscription/enrôlement visage, login
      conforme au nouvel ordre (1.1), échec volontaire (visage faux → vérifier 1.2 et la LED
      rouge clignotante de 1.5), blocage après 2 échecs / déblocage après 5 min (1.3), virement
      avec confirmation faciale, dashboard Supervision avant/pendant/après incident.
  - [ ] Noter les mesures de recette pour la section 7.2 du dossier (ce que le sujet appelle
        "mesures de la recette hotspot" — latences, taux de succès, captures d'écran).
- [ ] **Pendant la même session**, filmer le clip chrono (une seule prise, pas de coupe,
      ≤ 60 s) : attaque lancée depuis le PC Attaquant (`make attack-flood` /
      `attack-sqli` / `attack-exfil`, Makefile:44-50 — choisir celle qui illustre le mieux la
      remédiation ML) jusqu'à une nouvelle transaction réussie après remédiation.
  - [ ] Répéter le timing à blanc avant la prise définitive (le direct ne pardonne pas une
        coupe).
  - [ ] Exporter en `Workshop2026-M2-G<n>-VidChrono.mp4`.
- [ ] Capturer les éléments nécessaires aux slides 7 et 10 (cf. Phase 3) pendant cette même
      session pour ne pas avoir à refaire une recette seulement pour une capture d'écran.

---

## Phase 3 — Dossier, slides, archive code, répétition live (avant le gel 17h)

### 3.1 — Dossier PDF

- [ ] Compléter §7.2 avec les mesures de recette hotspot collectées en Phase 2.
- [ ] Mettre à jour §13 (biométrie) pour refléter l'implémentation réelle issue de la Phase 1
      — pas la version avant correction.
- [ ] Reprendre la phrase sur l'usage de l'IA (actuellement terminée provisoirement par
      "et de la validation finale") — à valider par la personne concernée avant export.
- [ ] Exporter en `Workshop2026-M2-G<n>-Dossier.pdf` depuis le Google Doc.

### 3.2 — Slides

- [ ] Mettre à jour les slides 7 et 10 avec les résultats réels de la recette (Phase 2), pas
      des placeholders.
- [ ] Exporter en `Workshop2026-M2-G<n>-Pres.pptx`.

### 3.3 — Archive code

- [ ] Vérifier avant export : pas de cible `git archive` existante dans le `Makefile` —
      construire la commande manuellement, ex. :
      `git archive --format=zip -o Workshop2026-M2-G<n>-Code.zip HEAD`
      (ou `--prefix=...` si le rendu doit avoir un dossier racine nommé).
  - Note : `git archive` n'exporte que les fichiers **suivis par git** au commit choisi — il
    exclut `.env`/`.vault/` *parce qu'ils sont gitignorés et jamais committés* (vérifié :
    `git ls-files` ne les liste pas), pas via une règle `export-ignore` (il n'y a pas de
    `.gitattributes` dans le dépôt). Donc l'exclusion marche aujourd'hui, mais elle dépend de
    la discipline de ne jamais `git add -f` un `.env` par erreur.
  - **`graphify-out` n'a été trouvé nulle part dans le dépôt** (ni fichier, ni référence dans
    le code/Makefile/doc). À vérifier avant de compter dessus : soit ce dossier n'existe pas
    encore (généré par un outil externe, auquel cas il faut l'ajouter au `.gitignore` et
    confirmer qu'il reste bien un dossier non suivi), soit c'est une confusion de nom.
- [ ] Une fois le zip produit, scanner son contenu avant diffusion :
      `unzip -l Workshop2026-M2-G<n>-Code.zip | grep -iE '\.env|secret|\.pem|\.key'`
      puis grep du contenu des fichiers extraits pour des chaînes sensibles
      (`trivy fs` / `gitleaks` sur le dossier extrait si l'outil est disponible, cf. `.trivyignore`
      déjà présent à la racine qui laisse penser que Trivy est déjà utilisé dans ce projet).
  - [ ] Vérifier spécifiquement `firmware/face-led/include/secrets.h` : il est gitignored donc
        absent de l'archive — confirmer que c'est bien voulu (sinon `secrets.example.h` doit
        suffire au correcteur pour comprendre la structure).

### 3.4 — Répétition du live (5 min, hotspot, attaque depuis PC Attaquant)

- [ ] Dérouler le script minute par minute avant le jour J : lancement attaque → détection
      (dashboard Supervision) → remédiation ML → preuve de reprise (transaction réussie).
  - [ ] Chronométrer pour tenir large dans les 5 minutes (prévoir une marge, pas pile 5:00).
  - [ ] Désigner qui manipule le PC Attaquant et qui commente/présente, pour ne pas improviser
        le jour du live.

---

## Synthèse de l'ordre (vue calendrier)

| Étape | Bloque / dépend de | Pourquoi dans cet ordre |
|---|---|---|
| 1. Code §10.1 (auth → payment-api → firmware → frontend) | — | Si le code change après la recette, la recette filmée (vidéo, mesures §7.2) devient obsolète. |
| 2. Recette hotspot + clip chrono (jeudi) | Phase 1 (au moins 1.1, 1.2, 1.3, 1.5) | Le clip et les mesures doivent refléter le comportement conforme, pas l'ancien. |
| 3. Dossier + slides + zip + répétition live | Phase 2 | Les rendus écrits/exportés figent ce qui a été mesuré en recette — à faire en dernier, avant 17h. |

## Risques identifiés à surveiller

- Le §10.1 n'a été relu qu'à travers ton relevé — si le texte exact diffère (ex. durées LED,
  définition précise de "2 tentatives au total"), corriger ce document avant de coder.
- Le point 1.1 (inversion de l'ordre des facteurs) est un changement de contrat d'API qui
  touche 3 services + le firmware + les tests E2E : c'est le point le plus risqué en termes de
  régression, à traiter avec le plus de marge avant jeudi.
- Le point 1.4 (écran back-office) n'a pas de brique existante à adapter — c'est le plus gros
  effort de développement neuf du lot.
- `graphify-out` non localisé : si ce dossier doit vraiment être exclu de l'archive, il faut
  d'abord le faire apparaître (générer, ou retrouver où il doit se créer) avant de pouvoir
  vérifier son exclusion.
