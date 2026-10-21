"""Télécharge et charge les poids des modèles au BUILD de l'image.

À l'exécution, le conteneur vit sur un réseau interne sans accès Internet :
tout ce que DeepFace téléchargerait au premier appel doit déjà être là.
Échoue le build si un modèle ne se charge pas (plutôt qu'au premier virement).
"""

from __future__ import annotations

import os

from deepface import DeepFace

DeepFace.build_model(os.environ["FACE_MODEL"], task="facial_recognition")
DeepFace.build_model(os.environ["FACE_DETECTOR"], task="face_detector")
DeepFace.build_model("Fasnet", task="spoofing")
print("modeles prets")
