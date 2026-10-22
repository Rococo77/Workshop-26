# Mode opératoire — mise en conformité §10.1 et rendus Workshop2026-M2-G<n>

> Document de pilotage, pas une spec figée : les cases à cocher valent preuve d'avancement.
> Hypothèse non vérifiée par moi : le libellé exact du §10.1 vient de ton relevé (Sujet.md
> est gitignored, je ne l'ai pas lu). Si un point ci-dessous ne correspond pas au texte réel
> du sujet, corrige la case concernée avant de coder dessus.

## Vérification après merge de `main` (22/10/2026)

Le merge a touché 5 fichiers en commun avec ce travail (conflits résolus manuellement) :
`services/auth/app/{main,db}.py`, `services/frontend/src/{Supervision.jsx,api.js}`,
`services/payment-api/app/main.py`. Audit complet (diff contre le dernier commit d'avant
merge, pas juste relecture visuelle) :

- **Régression trouvée et corrigée** : la résolution de conflit sur `services/auth/app/main.py`
  avait fait disparaître le filtre `role == "customer"` dans `/login` — un compte client aurait
  pu obtenir un jeton complet par ce seul endpoint (mot de passe), en contournant tout le
  parcours identifiant→visage→mot de passe du §10.1 (1.1). Remis en place.
- **Dette corrigée** : `has_face_enrollment` (dead code, déjà supprimé en 1.1) était revenu dans
  `services/auth/app/db.py` via le merge — resupprimé. Import dupliqué dans
  `services/payment-api/app/main.py` (artefact de résolution de conflit, pas un bug fonctionnel
  mais trompeur) — nettoyé.
- **Angle mort comblé** : aucun test ne couvrait `POST /login` du service `auth` lui-même (seul
  `payment-api`'s `auth.py` — un module différent du même nom — était testé) ; c'est pour ça que
  rien n'a signalé la régression. Ajout de 3 tests dans `tests/test_honeytokens.py` (déjà le
  fichier qui charge ce module, pour éviter une double exécution des compteurs Prometheus qui
  fait planter la collecte pytest si on le recharge depuis un second fichier).
- **Tout le reste** (1.2 à 1.5 : reset identifiant/caméra, seuils de blocage, back-office complet,
  LED 5 états) relu intégralement et confirmé intact, correctement recombiné avec les nouveautés
  de `main` (honeytokens, mode dégradé, rapport DORA) sans collision fonctionnelle.
- Suite de tests complète relancée avec toutes les dépendances optionnelles installées
  (plus aucun skip) : **103 passed**. Revérifié en direct via le WAF après rebuild
  `auth`+`payment-api` : login admin/operator OK, bascule customer→401 confirmée, back-office
  (liste, PATCH verrouillage/rôle, garde anti-auto-modification) OK, cycle LED
  `checking`→`fail` reconfirmé sur la vraie carte (toujours connectée après tous ces redémarrages).
- **Non vérifié, hors périmètre de cet audit** : `ml-detector` et `remediation-engine` tournent
  encore sur des images non reconstruites depuis le merge (3h d'uptime vs peu de minutes pour
  `auth`/`payment-api`/`waf`), alors que `main` y a changé du code (détection honeytoken, mode
  dégradé). Pas touché par mon travail, mais à reconstruire avant de considérer la stack
  entièrement à jour.

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

### 1.1 — Ordre des facteurs : identifiant → caméra → visage → mot de passe ✅ FAIT

- **Écart initial** : `services/auth/app/main.py:55-96` validait le mot de passe en premier
  (`verify_password`) et ne renvoyait `pending_face` qu'après — donc *mot de passe avant visage*,
  l'inverse de la consigne.
- **Conception retenue** (légèrement différente de la piste initiale ci-dessous, cf. bullet 2) :
  tout le parcours client (identifiant → visage → mot de passe) vit désormais dans
  `payment-api`, avec deux jetons intermédiaires à usage unique (`face_pending` puis
  `password_pending`). `auth` ne garde que le login operator/admin (mot de passe seul,
  `/supervision`). Pas de nouvel appel réseau entre services : secret JWT et base Postgres déjà
  partagés.
- **Actions** :
  - [x] Nouveau contrat défini : `POST /auth/login/identify` (identifiant seul, `payment-api`,
        jamais d'échec — pas d'oracle d'existence) → `POST /auth/login/face` (vérif visage,
        émet maintenant `password_pending` au lieu du jeton final) → `POST /auth/login/password`
        (mot de passe, émet le jeton final).
  - [x] `services/auth/app/main.py` + `security.py` + `db.py` : la branche `customer` et
        `create_pending_face_token`/`has_face_enrollment` ont été **supprimées** (pas scindées —
        ce service ne gère plus du tout le visage). `/login` ne reste que pour operator/admin.
  - [x] `services/payment-api` : `app/auth.py` (2 jetons + 2 dépendances `current_pending_*`),
        `app/db.py` (`verify_login_password`, comparaison pgcrypto), `app/main.py` (3 endpoints).
        Clarifié : c'est bien `payment-api` seul qui porte tout le parcours (DB + face-api déjà
        accessibles depuis ce service), aucune orchestration croisée avec `auth` nécessaire.
  - [x] `services/frontend/src/App.jsx` : 3 écrans (`identify`/`face`/`password`), `api.js` mis à
        jour (`identify`, `loginFace`, `loginPassword`). `infra/waf/default.conf.template` :
        `auth/login/identify` et `auth/login/password` ajoutés à la zone stricte anti-brute-force.
  - [x] Tests : `tests/test_auth_self_service.py` — 9 tests ajoutés (2 jetons, symétrie des 4
        dépendances `current_*`, `verify_login_password`). Suite complète relancée dans le
        conteneur `payment-api` (deps déjà présentes) : **60 passed, 4 skipped** (skips sans
        rapport : numpy/sklearn/docker absents du conteneur). Stack redémarrée et testée en
        direct via le WAF (`/api/auth/login/identify` → 200, ancien `/auth/login` rejette
        correctement un `customer`).
  - [x] `README.md` (section Authentification) synchronisé avec le nouveau parcours.

**Reste ouvert, pas fait ici** : `docs/architecture.md` §3.1 décrit encore l'ancien flux
(diagramme `auth {user,pwd}` → jeton pending → visage) — à mettre à jour séparément.

### 1.2 — Visage non reconnu : identifiant vidé + caméra coupée ✅ FAIT

- **Écart initial** : absent du code (aucune route ni logique ne réinitialise l'identifiant ou
  ne coupe le flux caméra après un échec de reconnaissance).
- **Actions** :
  - [x] Côté API : pas de nouveau code — le jeton `face_pending` est déjà à usage unique et de
        courte durée, et surtout le verrou anti-brute-force existant
        (`biometrics.recent_failures(...)`, `services/payment-api/app/main.py`) compte les
        échecs **par identifiant**, pas par jeton : ré-identifier pour obtenir un nouveau jeton
        ne contourne pas le compteur de blocage (1.3, non modifié ici). Pas de session à
        invalider explicitement au-delà de ça.
  - [x] Côté frontend (`services/frontend/src/App.jsx`, `submitFace`) : distinction par code
        d'erreur. Souci de prise de vue (`no_face`, `multiple_faces`, `invalid_image`,
        `image_too_large` — aucune tentative de reconnaissance comptée côté API) → reprise de
        la photo sur place. Toute autre erreur (`face_mismatch`, `spoof`, `face_locked`...) →
        `setUsername("")` + retour à l'étape `identify`, qui démonte `FaceCapture` (la caméra
        est de toute façon déjà coupée dès la photo prise, `FaceCapture.jsx:30-49` ; le
        démontage la coupe aussi si elle avait été rallumée).
  - [x] Firmware ESP8266 : déjà vérifié (reçoit l'événement `{"ok": false}` sur tout échec,
        `onWebSocketEvent`, `firmware/face-led/src/main.cpp:55-79`) — cohérent avec 1.5.
  - [x] Lint + build Vite local OK, image `frontend` reconstruite et redéployée sur la stack.

### 1.3 — Seuils de blocage : 2 tentatives puis 5 min (au lieu de 5 puis 15 min) ✅ FAIT

- **Écart initial** : `services/payment-api/app/config.py:46-47` (avant correction)
  `face_lockout_failures: int = 5`, `face_lockout_minutes: int = 15`.
- **Découverte en creusant** : ce même réglage était aussi utilisé par `confirm_transaction`
  (confirmation de virement, `purpose='confirm'`) — un compteur indépendant de celui du login,
  mais avec les MÊMES valeurs seuils. Changer la valeur globalement aurait aussi resserré le
  virement à 2/5 min, ce que le sujet ne demande pas (§10.1 ne parle que du login).
- **Décision prise sur la question ouverte** ("au total" = visage + mot de passe confondus) :
  **oui, compteur unique partagé**, lecture la plus naturelle de "2 tentatives au total" compte
  tenu du nouvel ordre des facteurs (1.1). À corriger si le texte réel du sujet dit autre chose.
- **Actions** :
  - [x] Nouveau réglage dédié au login, séparé de celui du virement :
        `login_lockout_failures: int = 2`, `login_lockout_minutes: int = 5`
        (`services/payment-api/app/config.py`). `face_lockout_failures`/`face_lockout_minutes`
        (5/15) restent inchangés, utilisés uniquement par `confirm_transaction`.
  - [x] `biometrics.recent_failures()` compte désormais aussi `result='password_mismatch'`
        (en plus de `mismatch`/`spoof`) pour `purpose='login'` : un échec de mot de passe
        consomme le même budget qu'un visage non reconnu.
  - [x] `login_face` et le nouveau `login_password` (`services/payment-api/app/main.py`)
        vérifient tous les deux `login_lockout_failures`/`login_lockout_minutes` avant de
        traiter la tentative, et journalisent l'échec (`log_attempt(..., purpose="login")`)
        sinon. Code d'erreur dédié `login_locked` (429) distinct de `face_locked` (confirmation
        de virement, toujours 15 min) pour que le message affiché reste exact dans les deux cas.
  - [x] Frontend (`services/frontend/src/api.js`) : codes `login_locked` et `invalid_credentials`
        ajoutés à `FACE_CODES` ; suppression du `.catch` ad-hoc de `loginPassword` qui aurait
        sinon écrasé `err.code`/`attemptsLeft`.
  - [x] Vérifié : pas de duplication de ces seuils dans `.env.example`/`docker-compose.yml`
        (jamais exposés en variable d'environnement, avant comme après) ni dans les dashboards
        Grafana.
  - [x] Tests : 2 ajoutés (`recent_failures` compte bien `password_mismatch`, valeurs par défaut
        2/5 vs 5/15 figées en dur). Suite complète : **62 passed, 4 skipped** (skips sans
        rapport). Images `payment-api`/`frontend` reconstruites et redéployées.

### 1.4 — Écran back-office : administration reconnaissance faciale + habilitations ✅ FAIT (périmètre réduit)

- **Écart initial** : aucun composant trouvé. Les rôles `operator`/`admin` n'avaient qu'une vue
  supervision.
- **Périmètre retenu** (précisé par toi, plus étroit que les 3 options envisagées initialement) :
  - [x] Lister les comptes clients avec l'état de leur visage enrôlé. « Connectés » lu comme
        « comptes clients enregistrés », pas des sessions actives en temps réel — les JWT sont
        sans état ici, il n'existe aucun suivi de session à interroger. À dire si ce n'est pas
        ce qui était voulu.
  - [x] Réinitialiser (supprimer) le visage enrôlé d'un client.
  - [x] Conséquence au login : si le visage a été réinitialisé, l'étape `identify` saute
        directement au mot de passe avec le message demandé, puis le ré-enrôlement (5 photos)
        est imposé avant tout accès bancaire.
  - [x] **Ajouté ensuite** (demande de suivi) : activer/désactiver un compte (tous rôles) et
        changer un rôle (customer/operator/admin) — `PATCH /admin/users/{username}`, body
        `{locked?, role?}`. Garde-fou : un admin ne peut pas s'auto-modifier (verrou ou rôle),
        pour éviter de se verrouiller hors du seul compte admin par erreur. Pas de protection
        équivalente sur le « dernier admin » (si plusieurs admins, rien n'empêche de tous se
        rétrograder mutuellement) — limite connue, pas traitée.
  - **Séparation des rôles** : vérifiée côté API à chaque requête (`current_admin`,
    `current_customer`, `current_principal` relisent le claim `role` du JWT), pas dans le front
    — celui-ci n'utilise le rôle que pour masquer/afficher des écrans, sans valeur de sécurité.
- **Bug trouvé et corrigé en testant en direct (pas lié à 1.3/au changement de rôle en soi)** :
  le WAF (OWASP CRS, règle 911100) n'autorise par défaut que `GET/HEAD/POST/OPTIONS` — **toutes**
  les routes back-office utilisant `DELETE` ou `PATCH` étaient bloquées en 403 *avant* d'atteindre
  payment-api, y compris le reset de visage déjà livré plus tôt (jamais testé via le WAF jusqu'ici,
  seulement vérifié en unitaire). Corrigé par une exclusion CRS dédiée (voir Actions).
- **Actions** :
  - [x] `infra/waf/modsecurity-exclusions.conf` (nouveau) + `infra/waf/Dockerfile` : exclusion
        CRS officielle (`REQUEST-900-EXCLUSION-RULES-BEFORE-CRS.conf`) autorisant `PATCH`/`DELETE`
        en plus des méthodes par défaut. Sans ça, `DELETE /api/admin/users/{username}/face`
        (livré avec la première partie du back-office) ne fonctionnait pas non plus via le WAF.
  - [x] `services/payment-api/app/auth.py` : nouveau garde `current_admin` (rôle admin
        uniquement — `operator` garde la supervision lecture seule, pas d'action ici).
  - [x] `services/payment-api/app/db.py` : `list_users()` (tous rôles, remplace
        `list_customers()`), `customer_needs_reenrollment()` (lu par `login_identify`),
        `set_account_locked()`, `set_account_role()`.
  - [x] `services/payment-api/app/biometrics.py` : `delete_enrollment()`.
  - [x] Routes (`services/payment-api/app/main.py`), toutes réservées au rôle admin :
        `GET /admin/users`, `PATCH /admin/users/{username}` (`{locked?, role?}`, rejette un
        rôle invalide en 422 et l'auto-modification en 409), `DELETE /admin/users/{username}/face`.
  - [x] `login_identify` : si le client existe, n'est pas verrouillé et n'a plus de visage
        enrôlé → jeton `password_pending` direct (saute le visage), statut
        `password_required_reenroll`. **Compromis assumé** : ça révèle qu'un compte existe et
        a besoin d'un ré-enrôlement (petite régression par rapport à l'absence d'oracle voulue
        en 1.1) — en pratique, un compte client n'arrive dans cet état que suite à une action
        admin explicite (pas via l'inscription normale, qui enrôle toujours le visage d'un
        coup), donc la fenêtre d'exposition reste étroite.
  - [x] Frontend : écran `/supervision` étend la session stockée pour inclure le rôle **et
        l'identifiant** (pas seulement le jeton) ; `AdminPanel` (visible seulement si
        `role==="admin"`) affiche désormais aussi une colonne rôle (`<select>`, désactivé sur
        soi-même) et un bouton verrouiller/déverrouiller, en plus du reset de visage. Écran de
        connexion client (`App.jsx`) : message demandé affiché sur l'étape mot de passe quand
        elle est atteinte directement depuis l'identifiant (`step.reenroll`). Le parcours de
        ré-enrôlement après connexion (5 photos) **existait déjà** (`FaceEnrollment.jsx`,
        déclenché par `GET /api/face/enrollment` dans `Banking`) — rien à ajouter là.
  - [x] Tests : 13 ajoutés au total (garde `current_admin`, `customer_needs_reenrollment`,
        `delete_enrollment`, `set_account_locked`, `set_account_role`, garde-fou
        anti-auto-modification, rejet de rôle invalide). Suite complète : **75 passed, 4 skipped**.
  - [x] Vérifié en direct via le WAF (après correction de l'exclusion CRS ci-dessus) :
        `/api/admin/users` sans jeton → 401 ; auto-modification → 409 ; rôle invalide → 422 ;
        verrouillage/déverrouillage et changement de rôle sur le compte `operator` de seed →
        200, remis dans son état d'origine après coup ; reset de visage sur un identifiant
        inexistant → 200 `reset:false` ; `identify` sur un client déjà enrôlé (`caro`) renvoie
        bien le statut normal (pas de faux positif de ré-enrôlement).
  - [ ] **Pas vérifié en direct** : le cycle complet reset → identify → mot de passe →
        ré-enrôlement avec un vrai compte (je n'ai pas voulu toucher aux données d'un compte de
        démo existant sans te le demander) — seulement couvert par les tests unitaires. À faire
        pendant la recette (Phase 2) avec un compte jetable.

### 1.5 — LED ESP8266 en 5 états ✅ FAIT

- **Écart initial** : `firmware/face-led/src/main.cpp` n'avait que deux états fixes (vert/rouge,
  10 s) sans clignotement, et rien n'était émis pour l'étape mot de passe.
- **États implémentés** : `idle` (éteinte), `checking` (vert clignotant, 300 ms), `ok` (vert
  fixe 30 s), `fail` (rouge clignotant ×10 puis éteinte), `locked` (rouge fixe 30 s). Détail des
  déclencheurs : `firmware/face-led/README.md`.
- **Actions** :
  - [x] Protocole WebSocket étendu : `{"purpose": "login"|"confirm", "state": "idle"|"checking"|
        "ok"|"fail"|"locked"}` (remplace l'ancien `{"ok": bool, "purpose": ...}`), publié aux
        points clés de `login_face`, `login_password` (nouveau : `checking` avant vérification)
        et `confirm_transaction` (`services/payment-api/app/main.py`).
  - [x] `main.cpp` réécrit : état-machine non bloquante (`enterState`/`updateLeds`, `millis()`,
        pas de `delay()` dans `loop()`) gérant les 5 états, y compris les 10 clignotements
        comptés et les 2 affichages fixes de 30 s.
  - [x] Étape mot de passe propagée : `checking` à l'entrée de `login_password`, `ok` si la
        connexion aboutit, `fail`/`locked` sinon — cohérent avec l'ordre des facteurs (1.1).
  - [x] `firmware/face-led/README.md` mis à jour (tableau des 5 états, build/flash, vérification).
  - [x] Build + upload réels sur la carte (COM5, PlatformIO Core) : succès. Cycle complet testé
        en conditions réelles (requête HTTP → WebSocket → LED) via le moniteur série : capture
        confirmée de `[ws] purpose=login state=checking` puis `state=fail` suite à un login
        échoué déclenché en direct. **Bug trouvé en testant** : j'avais oublié de reconstruire
        et redéployer le conteneur `payment-api` après avoir changé le protocole — corrigé.
  - [x] Tests Python : suite complète inchangée et toujours verte (**75 passed, 4 skipped**,
        `events.publish` reste agnostique du contenu, aucune régression).

### 1.6 — Points à vérifier sur place (pas du code à écrire, de la vérification physique)

- [ ] **Wi-Fi ESP8266** : confirmer sur le terrain que `firmware/face-led/include/secrets.h`
      pointe vers le SSID `RESILIENCE-G<n>` attendu (fichier volontairement gitignored —
      `firmware/*/include/secrets.h` dans `.gitignore` — donc à vérifier en lecture directe sur
      la carte/le poste de flash, pas dans le dépôt). **Vérifié pour le poste actuel** :
      `secrets.h` est bien configuré, mais pour le réseau Wi-Fi courant (`myDiL`), pas encore
      pour le hotspot `RESILIENCE-G1` du jour J — à reconfigurer avant/pendant la recette.
- [x] ~~**Outils imposés (CLion + PlatformIO)**~~ → **CLion abandonné** : le plugin PlatformIO
      for CLion n'a pas pu être mis en route côté utilisateur. Seul **PlatformIO Core en ligne
      de commande** (`pio run`, `pio run -t upload`, `pio device monitor`) est utilisé et
      vérifié — c'est d'ailleurs ce que j'ai utilisé pour flasher/tester 1.5. **Écart à assumer
      et signaler tel quel** vis-à-vis du §10.1 si le sujet exige explicitement l'IDE CLion (pas
      seulement l'outil PlatformIO) ; documenté dans `firmware/face-led/README.md`.

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
- Le point 1.1 (inversion de l'ordre des facteurs) est fait et testé unitairement (60 tests
  passent), mais **pas encore vérifié avec une vraie photo de visage / face-api** (le smoke
  test WAF n'a exercé que `/auth/login/identify`, sans aller jusqu'au bout avec un client
  enrôlé réel) — à couvrir dans la recette hotspot (Phase 2), pas avant.
- Le point 1.4 (écran back-office) n'a pas de brique existante à adapter — c'est le plus gros
  effort de développement neuf du lot.
- Le WAF n'autorisait par défaut que GET/HEAD/POST/OPTIONS (OWASP CRS) : toute future route qui
  utiliserait PUT (pas seulement PATCH/DELETE, déjà couverts) la verrait aussi bloquée en 403
  avant payment-api, sans erreur applicative pour orienter le diagnostic (juste une page nginx
  générique). Pense à `infra/waf/modsecurity-exclusions.conf` si ça arrive.
- `graphify-out` non localisé : si ce dossier doit vraiment être exclu de l'archive, il faut
  d'abord le faire apparaître (générer, ou retrouver où il doit se créer) avant de pouvoir
  vérifier son exclusion.
