"""Client de l'API DeepFace (service interne `face-api`) et décision de
correspondance.

DeepFace ne fait que calculer l'empreinte (vecteur) d'un visage via
`/represent`, avec anti-spoofing. La comparaison à l'empreinte de référence est
faite ICI : seuil maîtrisé, distance journalisée (explicabilité) et jamais
renvoyée au client (pas d'oracle pour optimiser une image d'attaque).
"""

from __future__ import annotations

import base64
import binascii
import math

import httpx

from .config import settings

# Une photo 480 px en JPEG pèse ~30-60 Ko en base64 ; au-delà, refus avant
# tout calcul. Sous la limite ModSecurity des corps JSON (128 Ko) du WAF.
MAX_IMAGE_B64_CHARS = 120_000
_MAGIC = {b"\xff\xd8\xff": "jpeg", b"\x89PNG\r\n\x1a\n": "png"}

# Pool d'empreintes par client : une pose par orientation. Une seule photo
# prise au login/virement est ensuite comparée aux 5 (distance minimale) ->
# reconnaissance plus tolérante à l'angle/l'éclairage. Partagé par
# l'auto-inscription (main.py) et l'outil opérateur (enroll_cli.py).
REQUIRED_POSES = ("right", "up", "down", "left", "face")


class FaceRejected(Exception):
    """Image refusée : pas de visage, plusieurs visages, spoof...
    `code` est remonté tel quel au front."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class FaceUnavailable(Exception):
    """API DeepFace injoignable ou en erreur -> 503, le virement reste en attente."""


def normalize_image(image: str, max_chars: int = MAX_IMAGE_B64_CHARS) -> str:
    """Valide une image base64 (data URL ou brute) et la renvoie en data URL."""
    if len(image) > max_chars:
        raise FaceRejected("image_too_large")
    payload = image.split(",", 1)[1] if image.startswith("data:") else image
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise FaceRejected("invalid_image") from None
    kind = next((k for magic, k in _MAGIC.items() if raw.startswith(magic)), None)
    if kind is None:
        raise FaceRejected("invalid_image")
    return f"data:image/{kind};base64,{payload}"


def embed(image: str, max_chars: int = MAX_IMAGE_B64_CHARS) -> list[float]:
    """Empreinte du visage unique de l'image (anti-spoofing actif).
    `max_chars` : relevé seulement par l'outil d'admin (photo pleine taille,
    sans passer par le WAF)."""
    try:
        res = httpx.post(
            f"{settings.face_api_url}/represent",
            json={
                "img": normalize_image(image, max_chars),
                "model_name": settings.face_model,
                "detector_backend": settings.face_detector,
                "anti_spoofing": settings.face_anti_spoofing,
            },
            headers={"Authorization": f"Bearer {settings.face_api_token}"},
            timeout=settings.face_api_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise FaceUnavailable(str(exc)) from exc

    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    if res.status_code == 400:
        # DeepFace renvoie 400 + message libre pour les refus liés à l'image.
        error = str(body.get("error", ""))
        if "Spoof detected" in error:
            raise FaceRejected("spoof")
        if "Face could not be detected" in error:
            raise FaceRejected("no_face")
        raise FaceRejected("invalid_image")
    if res.status_code != 200:
        raise FaceUnavailable(f"face-api HTTP {res.status_code}")

    faces = body.get("results") or []
    if len(faces) != 1:
        raise FaceRejected("no_face" if not faces else "multiple_faces")
    return [float(x) for x in faces[0]["embedding"]]


def cosine_distance(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("embedding size mismatch")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0:
        return 1.0
    return 1.0 - dot / norm


def is_match(distance: float) -> bool:
    return distance <= settings.face_match_threshold


def best_distance(probe: list[float], candidates: list[list[float]]) -> float:
    """Distance minimale entre une photo prise au login/virement et le pool
    d'empreintes enrôlées (une par pose) : il suffit qu'une seule corresponde."""
    return min(cosine_distance(probe, c) for c in candidates)
