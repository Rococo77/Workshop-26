"""API métier de paiement (fictif).

Endpoints publics (via WAF) : /health, /accounts/me, /transactions,
/face/enrollment et /transactions/{id}/confirm|cancel (validation faciale).
Endpoint interne (non exposé au réseau pédagogique) : /internal/canary,
utilisé par le moteur de remédiation pour prouver le retour à un état
utilisable (transaction canari réelle en base).
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from . import biometrics, db, face, service
from .auth import Principal, current_customer
from .config import settings
from .metrics import FACE_LATENCY, FACE_VERIFICATIONS, PAYMENT_TX, MetricsMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("payment-api")

app = FastAPI(title="Resilience-Alpha Payment API", version="1.0.0")
app.add_middleware(MetricsMiddleware)

# Comptes canari (seed) : alice(1) -> bob(2), montant symbolique.
CANARY_SRC, CANARY_DST, CANARY_USER = 1, 2, "alice"


class TransferRequest(BaseModel):
    src_account: int = Field(gt=0)
    # Bénéficiaire : par id (canari, scripts) ou par IBAN (front client).
    dst_account: int | None = Field(default=None, gt=0)
    dst_iban: str | None = Field(default=None, min_length=4, max_length=34)
    amount: str = Field(description="Montant décimal, ex. '12.50'")


class FaceImage(BaseModel):
    # Photo JPEG/PNG en base64 brut (data URL acceptée). Taille fine contrôlée par face.py.
    image: str = Field(min_length=16, max_length=face.MAX_IMAGE_B64_CHARS * 2)


def _face_error(status_code: int, code: str, **extra) -> HTTPException:
    # `detail` structuré : le front affiche un message selon `code`.
    return HTTPException(status_code, {"code": code, **extra})


def _embed(image: str, purpose: str) -> list[float]:
    """Empreinte via DeepFace, instrumentée. FaceRejected remonte à l'appelant
    (décision métier différente à l'enrôlement et à la confirmation)."""
    start = time.perf_counter()
    try:
        return face.embed(image)
    except face.FaceRejected as exc:
        FACE_VERIFICATIONS.labels(purpose=purpose, result=exc.code).inc()
        raise
    except face.FaceUnavailable as exc:
        FACE_VERIFICATIONS.labels(purpose=purpose, result="unavailable").inc()
        log.error("face-api unavailable: %s", exc)
        raise _face_error(status.HTTP_503_SERVICE_UNAVAILABLE, "face_unavailable") from exc
    finally:
        FACE_LATENCY.observe(time.perf_counter() - start)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    # Prêt = base joignable. Utilisé pour distinguer 'up' de 'utilisable'.
    try:
        with db.get_conn() as conn:
            conn.execute("SELECT 1")
        return {"status": "ready"}
    except Exception as exc:
        log.warning("not ready: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/accounts/me")
def my_accounts(principal: Principal = Depends(current_customer)) -> list[dict]:
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT a.id, a.iban_fake, a.balance, a.currency FROM account a "
                "JOIN app_user u ON u.id = a.owner_id WHERE u.username = %s ORDER BY a.id",
                (principal.username,),
            ).fetchall()
        return rows
    except Exception as exc:
        log.error("accounts query failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "backend unavailable") from exc


@app.post("/transactions", status_code=status.HTTP_201_CREATED)
def create_transaction(
    req: TransferRequest, response: Response, principal: Principal = Depends(current_customer)
) -> dict:
    """Validation faciale active : crée un virement `pending` (202), réglé
    seulement par /transactions/{id}/confirm. Sinon : règlement immédiat (201)."""
    try:
        amount = Decimal(req.amount)
    except (InvalidOperation, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid amount") from None
    if (req.dst_account is None) == (req.dst_iban is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "provide either dst_account or dst_iban"
        )

    if settings.face_confirmation_required:
        return _create_pending(req, amount, principal, response)

    try:
        dst_account = req.dst_account or service.account_id_by_iban(req.dst_iban)
        tx = service.transfer(
            username=principal.username,
            src_account=req.src_account,
            dst_account=dst_account,
            amount=amount,
        )
        PAYMENT_TX.labels(result="settled").inc()
        return {
            "id": tx["id"],
            "reference": tx["reference"],
            "status": tx["status"],
            "amount": str(tx["amount"]),
        }
    except service.BusinessError as exc:
        PAYMENT_TX.labels(result="rejected").inc()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception as exc:
        PAYMENT_TX.labels(result="error").inc()
        log.error("transfer failed: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "transfer backend unavailable"
        ) from exc


def _create_pending(
    req: TransferRequest, amount: Decimal, principal: Principal, response: Response
) -> dict:
    try:
        if biometrics.get_enrollment(principal.username) is None:
            raise _face_error(status.HTTP_403_FORBIDDEN, "face_not_enrolled")
        dst_account = req.dst_account or service.account_id_by_iban(req.dst_iban)
        tx = service.create_pending(
            username=principal.username,
            src_account=req.src_account,
            dst_account=dst_account,
            amount=amount,
            ttl_seconds=settings.face_confirm_ttl_seconds,
        )
    except HTTPException:
        raise
    except service.BusinessError as exc:
        PAYMENT_TX.labels(result="rejected").inc()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception as exc:
        PAYMENT_TX.labels(result="error").inc()
        log.error("pending transfer failed: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "transfer backend unavailable"
        ) from exc

    PAYMENT_TX.labels(result="pending").inc()
    response.status_code = status.HTTP_202_ACCEPTED
    return {
        "id": tx["id"],
        "reference": tx["reference"],
        "status": tx["status"],
        "amount": str(tx["amount"]),
        "expires_at": tx["expires_at"].isoformat(),
        "attempts_left": settings.face_max_attempts_per_tx - tx["confirm_attempts"],
    }


@app.post("/transactions/{tx_id}/confirm")
def confirm_transaction(
    tx_id: int, req: FaceImage, principal: Principal = Depends(current_customer)
) -> dict:
    """Règle un virement en attente si le visage correspond à l'empreinte
    enrôlée. Chaque échec consomme un essai ; un spoof aussi."""
    user = principal.username
    try:
        service.get_pending(tx_id, user)  # BusinessError si introuvable ou clos
        if biometrics.recent_failures(user, settings.face_lockout_minutes) >= (
            settings.face_lockout_failures
        ):
            log.warning("face lockout user=%s tx=%s", user, tx_id)
            raise _face_error(status.HTTP_429_TOO_MANY_REQUESTS, "face_locked")
        enrollment = biometrics.get_enrollment(user)
    except HTTPException:
        raise
    except service.BusinessError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Exception as exc:
        log.error("confirm lookup failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "backend unavailable") from exc

    if enrollment is None:
        raise _face_error(status.HTTP_403_FORBIDDEN, "face_not_enrolled")
    if enrollment["model_name"] != settings.face_model:
        raise _face_error(status.HTTP_409_CONFLICT, "face_reenrollment_required")

    distance: float | None = None
    try:
        probe = _embed(req.image, "confirm")
        distance = face.cosine_distance(enrollment["embedding"], probe)
        result = "match" if face.is_match(distance) else "mismatch"
    except face.FaceRejected as exc:
        if exc.code != "spoof":
            # Photo inexploitable (pas de visage, floue...) : pas d'essai consommé.
            raise _face_error(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code) from exc
        result = "spoof"

    # Journal d'audit + SIEM (Loki) : la distance est tracée, jamais renvoyée.
    biometrics.log_attempt(user, purpose="confirm", result=result, distance=distance, tx_id=tx_id)
    log.info(
        "face confirm user=%s tx=%s result=%s distance=%s",
        user,
        tx_id,
        result,
        f"{distance:.4f}" if distance is not None else "-",
    )

    if result != "match":
        FACE_VERIFICATIONS.labels(purpose="confirm", result=result).inc()
        left = service.record_failed_attempt(tx_id, settings.face_max_attempts_per_tx)
        if left == 0:
            PAYMENT_TX.labels(result="rejected").inc()
        code = "spoof" if result == "spoof" else "face_mismatch"
        raise _face_error(status.HTTP_403_FORBIDDEN, code, attempts_left=left)

    FACE_VERIFICATIONS.labels(purpose="confirm", result="match").inc()
    try:
        settled = service.settle_pending(tx_id, user)
    except service.BusinessError as exc:
        PAYMENT_TX.labels(result="rejected").inc()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception as exc:
        PAYMENT_TX.labels(result="error").inc()
        log.error("settle failed: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "transfer backend unavailable"
        ) from exc

    PAYMENT_TX.labels(result="settled").inc()
    return {
        "id": settled["id"],
        "reference": settled["reference"],
        "status": settled["status"],
        "amount": str(settled["amount"]),
    }


@app.post("/transactions/{tx_id}/cancel")
def cancel_transaction(tx_id: int, principal: Principal = Depends(current_customer)) -> dict:
    try:
        service.get_pending(tx_id, principal.username)
        service.reject_pending(tx_id, "cancelled")
    except service.BusinessError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Exception as exc:
        log.error("cancel failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "backend unavailable") from exc
    return {"id": tx_id, "status": "rejected"}


@app.get("/face/enrollment")
def face_enrollment_status(principal: Principal = Depends(current_customer)) -> dict:
    try:
        enrollment = biometrics.get_enrollment(principal.username)
    except Exception as exc:
        log.error("enrollment lookup failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "backend unavailable") from exc
    return {
        "required": settings.face_confirmation_required,
        "enrolled": enrollment is not None,
        "enrolled_at": enrollment["created_at"].isoformat() if enrollment else None,
    }


@app.post("/face/enrollment", status_code=status.HTTP_201_CREATED)
def face_enroll(req: FaceImage, principal: Principal = Depends(current_customer)) -> dict:
    """Enrôlement unique du visage de référence. Seul le vecteur est stocké."""
    user = principal.username
    try:
        if biometrics.get_enrollment(user) is not None:
            raise _face_error(status.HTTP_409_CONFLICT, "already_enrolled")
    except HTTPException:
        raise
    except Exception as exc:
        log.error("enrollment lookup failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "backend unavailable") from exc

    try:
        embedding = _embed(req.image, "enroll")
    except face.FaceRejected as exc:
        if exc.code == "spoof":
            biometrics.log_attempt(user, purpose="enroll", result="spoof", distance=None)
            log.warning("face enroll spoof user=%s", user)
        raise _face_error(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code) from exc

    if not biometrics.save_enrollment(user, settings.face_model, embedding):
        raise _face_error(status.HTTP_409_CONFLICT, "already_enrolled")
    biometrics.log_attempt(user, purpose="enroll", result="enrolled", distance=None)
    FACE_VERIFICATIONS.labels(purpose="enroll", result="enrolled").inc()
    log.info("face enrolled user=%s model=%s", user, settings.face_model)
    return {"enrolled": True}


@app.get("/transactions")
def list_transactions(
    limit: int = 20, principal: Principal = Depends(current_customer)
) -> list[dict]:
    """Historique du client : uniquement les opérations touchant SES comptes
    (avant : toutes les transactions de la plateforme, quel que soit l'appelant)."""
    limit = max(1, min(limit, 100))  # pagination bornée (anti-dump)
    try:
        service.expire_pending()
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT t.id, t.reference, t.amount, t.status, t.reject_reason, t.is_canary, "
                "t.created_at, "
                "s.iban_fake AS src_iban, d.iban_fake AS dst_iban, "
                "(su.username = %(u)s) AS outgoing "
                "FROM payment_tx t "
                "JOIN account s ON s.id = t.src_account "
                "JOIN account d ON d.id = t.dst_account "
                "JOIN app_user su ON su.id = s.owner_id "
                "JOIN app_user du ON du.id = d.owner_id "
                # Le bénéficiaire ne voit un virement qu'une fois réglé.
                "WHERE su.username = %(u)s OR (du.username = %(u)s AND t.status = 'settled') "
                "ORDER BY t.created_at DESC LIMIT %(n)s",
                {"u": principal.username, "n": limit},
            ).fetchall()
        return rows
    except Exception as exc:
        log.error("tx list failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "backend unavailable") from exc


@app.post("/internal/canary")
def canary() -> dict:
    """Transaction canari : prouve que le chemin métier complet fonctionne
    (auth implicite seed -> débit -> crédit -> écriture). Non exposé via WAF."""
    try:
        tx = service.transfer(
            username=CANARY_USER,
            src_account=CANARY_SRC,
            dst_account=CANARY_DST,
            amount=Decimal("1.00"),
            is_canary=True,
        )
        PAYMENT_TX.labels(result="canary_ok").inc()
        return {"canary": "ok", "reference": tx["reference"]}
    except Exception as exc:
        PAYMENT_TX.labels(result="canary_fail").inc()
        log.error("canary failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"canary failed: {exc}") from exc


@app.exception_handler(Exception)
def unhandled(_, exc: Exception) -> JSONResponse:
    log.exception("unhandled: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "internal error"})
