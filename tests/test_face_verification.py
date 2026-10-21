"""Validation faciale des virements : décision de correspondance, contrôle des
images et interprétation des réponses de l'API DeepFace (sans conteneur)."""

from __future__ import annotations

import base64

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("pydantic_settings")

from conftest import load_service_module  # noqa: E402

config = load_service_module("payment_api", "services/payment-api", "config")
face = load_service_module("payment_api", "services/payment-api", "face")

JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 64).decode()


# ------------------------------------------------------------ distance / seuil
def test_identical_embeddings_have_zero_distance():
    v = [0.1, -0.4, 0.7, 0.2]
    assert face.cosine_distance(v, v) == pytest.approx(0.0, abs=1e-9)


def test_opposite_embeddings_have_max_distance():
    assert face.cosine_distance([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(2.0)


def test_zero_vector_never_matches():
    assert face.is_match(face.cosine_distance([0.0, 0.0], [1.0, 0.0])) is False


def test_embedding_size_mismatch_is_rejected():
    with pytest.raises(ValueError):
        face.cosine_distance([1.0, 0.0], [1.0, 0.0, 0.0])


def test_threshold_is_inclusive(monkeypatch):
    monkeypatch.setattr(config.settings, "face_match_threshold", 0.30)
    assert face.is_match(0.30) is True
    assert face.is_match(0.3001) is False


# ------------------------------------------------------------ images
def test_jpeg_data_url_is_accepted():
    assert face.normalize_image(JPEG).startswith("data:image/jpeg;base64,")


def test_raw_base64_png_gets_a_data_url():
    raw = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()
    assert face.normalize_image(raw).startswith("data:image/png;base64,")


@pytest.mark.parametrize(
    "image",
    [
        "data:image/gif;base64," + base64.b64encode(b"GIF89a" + b"\x00" * 16).decode(),
        "data:image/jpeg;base64,pas-du-base64!!",
        # Chemin ou URL : DeepFace les chargerait (lecture de fichier / SSRF).
        "/etc/passwd",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_non_image_payloads_are_rejected(image):
    with pytest.raises(face.FaceRejected) as exc:
        face.normalize_image(image)
    assert exc.value.code == "invalid_image"


def test_oversized_image_is_rejected_before_decoding():
    with pytest.raises(face.FaceRejected) as exc:
        face.normalize_image("A" * (face.MAX_IMAGE_B64_CHARS + 1))
    assert exc.value.code == "image_too_large"


# ------------------------------------------------------------ réponses DeepFace
def _fake_api(monkeypatch, status_code: int, body: dict | None = None, raise_exc=None):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        if raise_exc:
            raise raise_exc
        return httpx.Response(status_code, json=body or {})

    monkeypatch.setattr(face.httpx, "post", fake_post)
    return seen


def test_single_face_returns_embedding_and_sends_token(monkeypatch):
    monkeypatch.setattr(config.settings, "face_api_token", "s3cret")
    seen = _fake_api(monkeypatch, 200, {"results": [{"embedding": [0.1, 0.2]}]})
    assert face.embed(JPEG) == [0.1, 0.2]
    assert seen["headers"]["Authorization"] == "Bearer s3cret"
    assert seen["json"]["anti_spoofing"] is config.settings.face_anti_spoofing


@pytest.mark.parametrize(
    ("status_code", "body", "code"),
    [
        (400, {"error": "Exception while representing: Spoof detected in the image."}, "spoof"),
        (400, {"error": "Exception while representing: Face could not be detected."}, "no_face"),
        (400, {"error": "Exception while representing: something else"}, "invalid_image"),
        (200, {"results": []}, "no_face"),
        (200, {"results": [{"embedding": [1.0]}, {"embedding": [0.5]}]}, "multiple_faces"),
    ],
)
def test_image_level_refusals_map_to_codes(monkeypatch, status_code, body, code):
    _fake_api(monkeypatch, status_code, body)
    with pytest.raises(face.FaceRejected) as exc:
        face.embed(JPEG)
    assert exc.value.code == code


@pytest.mark.parametrize("status_code", [401, 500, 502])
def test_api_errors_are_unavailability_not_refusal(monkeypatch, status_code):
    _fake_api(monkeypatch, status_code, {"message": "x"})
    with pytest.raises(face.FaceUnavailable):
        face.embed(JPEG)


def test_network_error_is_unavailability(monkeypatch):
    _fake_api(monkeypatch, 0, raise_exc=httpx.ConnectError("refused"))
    with pytest.raises(face.FaceUnavailable):
        face.embed(JPEG)
