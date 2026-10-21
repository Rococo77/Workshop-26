# Fixtures de test

`sample-face.jpg` : portrait officiel de Barack Obama (Maison-Blanche,
domaine public — œuvre du gouvernement fédéral américain), redimensionné à
480 px / JPEG qualité 85 (même format que les photos envoyées par le front,
voir `services/frontend/src/components/FaceCapture.jsx`).

Utilisé uniquement par `scripts/ci-e2e.sh` pour exercer de bout en bout
l'auto-inscription (`POST /api/auth/register`) puis la connexion à deux
facteurs (`POST /auth/login` + `POST /api/auth/login/face`) avec la même
photo : la distance cosinus attendue est ≈ 0 (même image), donc le test est
déterministe et non sujet à la variabilité de la reconnaissance faciale.
Le compte de test créé est supprimé en fin de script.

Source : https://commons.wikimedia.org/wiki/File:President_Barack_Obama.jpg
