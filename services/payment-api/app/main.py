"""API métier de paiement (fictif).

Endpoints publics (via WAF) : /health, /auth/register, /auth/login/face,
/accounts/me, /transactions, /face/enrollment et
/transactions/{id}/confirm|cancel (validation faciale), /ws/face-events
(relais temps réel vers l'indicateur LED ESP8266, voir firmware/face-led/).
Endpoint interne (non exposé au réseau pédagogique) : /internal/canary,
utilisé par le moteur de remédiation pour prouver le retour à un état
utilisable (transaction canari réelle en base).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from . import accounts, biometrics, db, events, face, honeytokens, service
from .auth import Principal, create_access_token, current_customer, current_pending_face
from .config import settings
from .metrics import FACE_LATENCY, FACE_VERIFICATIONS, PAYMENT_TX, MetricsMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("payment-api")


def _replay_leftovers() -> None:
    """Au démarrage, hors mode dégradé : règle les virements restés en file
    (moteur ou API redémarrés avant la clôture de l'incident)."""
    try:
        if not service.degraded(settings.degraded_max_minutes):
            done = service.replay_queue()
            if done["settled"] or done["rejected"]:
                log.info("file d'attente rejouée au démarrage: %s", done)
    except Exception as exc:
        log.warning("rejeu au démarrage impossible: %s", exc)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await asyncio.to_thread(_replay_leftovers)
    task = asyncio.create_task(events.broadcast_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Resilience-Alpha Payment API", version="1.0.0", lifespan=_lifespan)
app.add_middleware(MetricsMiddleware)
# Ajouté en dernier = exécuté en premier : voit toutes les réponses, même les 500.
app.add_middleware(honeytokens.ExfiltrationGuard)

# Comptes canari : utilisateurs verrouillés _canary_src / _canary_dst (seed ou
# migration 06), jamais connectés ; voir service.canary_route().

REQUIRED_POSES = face.REQUIRED_POSES


class TransferRequest(BaseModel):
    src_account: int = Field(gt=0)
    # Bénéficiaire : par id (canari, scripts) ou par IBAN (front client).
    dst_account: int | None = Field(default=None, gt=0)
    dst_iban: str | None = Field(default=None, min_length=4, max_length=34)
    amount: str = Field(description="Montant décimal, ex. '12.50'")


class FaceImage(BaseModel):
    # Photo JPEG/PNG en base64 brut (data URL acceptée). Taille fine contrôlée par face.py.
    image: str = Field(min_length=16, max_length=face.MAX_IMAGE_B64_CHARS * 2)


class PoseImages(BaseModel):
    # Une photo par pose (clés = REQUIRED_POSES, vérifié par _validate_pool).
    images: dict[str, str]


class RegisterRequest(PoseImages):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=256)
    # Consentement explicite au traitement de la donnée biométrique (RGPD
    # art. 9) : obligatoire, affiché par le front avant toute capture photo.
    consent: bool = False


def _face_error(status_code: int, code: str, **extra) -> HTTPException:
    # `detail` structuré : le front affiche un message selon `code`.
    return HTTPException(status_code, {"code": code, **extra})


def _validate_pool(images: dict[str, str]) -> None:
    if set(images.keys()) != set(REQUIRED_POSES):
        raise _face_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "incomplete_pool")


def _embed_pool(images: dict[str, str], purpose: str) -> dict[str, list[float]]:
    """Empreinte de chaque pose, dans un ordre déterministe. Fail-fast : la
    première photo inexploitable arrête tout (aucune écriture partielle),
    l'erreur indique la pose en cause pour que le front ne fasse reprendre
    que celle-là."""
    embeddings: dict[str, list[float]] = {}
    for pose in REQUIRED_POSES:
        try:
            embeddings[pose] = _embed(images[pose], purpose)
        except face.FaceRejected as exc:
            raise _face_error(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, pose=pose) from exc
    return embeddings


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


@app.websocket("/ws/face-events")
async def face_events(websocket: WebSocket) -> None:
    """Relais temps réel des vérifications faciales (login, confirmation de
    virement) vers un client WebSocket (indicateur LED ESP8266). Jeton
    partagé requis (même principe que FACE_API_TOKEN), l'ESP n'envoie rien :
    la boucle de réception ne sert qu'à détecter sa déconnexion."""
    if websocket.headers.get("authorization") != f"Bearer {settings.esp_events_token}":
        await websocket.close(code=4401)
        return
    await websocket.accept()
    events.register(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        events.unregister(websocket)


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest) -> dict:
    """Auto-inscription : mot de passe + pool de 5 photos (une par pose) en
    un seul appel. Reprend l'ordre de l'outil opérateur (`enroll_cli`) : les
    empreintes sont calculées AVANT de créer le compte, pour ne rien
    persister si une seule photo est inexploitable."""
    if not req.consent:
        raise _face_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "consent_required")
    try:
        accounts.validate_username(req.username)
        accounts.validate_password(req.password)
    except accounts.AccountError as exc:
        raise _face_error(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code) from exc
    _validate_pool(req.images)

    # Pas d'audit `log_attempt` ici : le compte n'existe pas encore (rien à
    # rattacher), et une photo inexploitable ne doit créer ni client ni trace.
    embeddings = _embed_pool(req.images, "enroll")

    try:
        accounts.create_customer(
            req.username,
            req.password,
            accounts.next_iban(),
            settings.registration_starting_balance,
            consent_at=datetime.now(UTC),
        )
    except accounts.AccountError as exc:
        raise _face_error(status.HTTP_409_CONFLICT, exc.code) from exc

    biometrics.save_enrollment(req.username, settings.face_model, embeddings)
    biometrics.log_attempt(req.username, purpose="enroll", result="enrolled", distance=None)
    FACE_VERIFICATIONS.labels(purpose="enroll", result="enrolled").inc()
    log.info("customer registered username=%s", req.username)

    token = create_access_token(subject=req.username, role="customer")
    return {"access_token": token, "token_type": "bearer", "role": "customer"}


@app.post("/auth/login/face")
def login_face(req: FaceImage, principal: Principal = Depends(current_pending_face)) -> dict:
    """Second facteur de connexion : le mot de passe a déjà été vérifié par
    le service auth, qui a émis un jeton `face_pending` de courte durée.
    Même logique anti-force-brute / anti-spoof que la confirmation de
    virement, compteur d'échecs indépendant (purpose='login')."""
    user = principal.username
    if biometrics.recent_failures(user, settings.face_lockout_minutes, purpose="login") >= (
        settings.face_lockout_failures
    ):
        log.warning("face login lockout user=%s", user)
        raise _face_error(status.HTTP_429_TOO_MANY_REQUESTS, "face_locked")

    enrollment = biometrics.get_enrollment(user)
    if enrollment is None:
        raise _face_error(status.HTTP_403_FORBIDDEN, "face_not_enrolled")
    if enrollment["model_name"] != settings.face_model:
        raise _face_error(status.HTTP_409_CONFLICT, "face_reenrollment_required")

    distance: float | None = None
    try:
        probe = _embed(req.image, "login")
        distance = face.best_distance(probe, list(enrollment["poses"].values()))
        result = "match" if face.is_match(distance) else "mismatch"
    except face.FaceRejected as exc:
        if exc.code != "spoof":
            raise _face_error(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code) from exc
        result = "spoof"

    biometrics.log_attempt(user, purpose="login", result=result, distance=distance)
    log.info(
        "face login user=%s result=%s distance=%s",
        user,
        result,
        f"{distance:.4f}" if distance is not None else "-",
    )
    events.publish({"ok": result == "match", "purpose": "login"})

    if result != "match":
        FACE_VERIFICATIONS.labels(purpose="login", result=result).inc()
        left = settings.face_lockout_failures - biometrics.recent_failures(
            user, settings.face_lockout_minutes, purpose="login"
        )
        code = "spoof" if result == "spoof" else "face_mismatch"
        raise _face_error(status.HTTP_403_FORBIDDEN, code, attempts_left=max(0, left))

    FACE_VERIFICATIONS.labels(purpose="login", result="match").inc()
    token = create_access_token(subject=user, role=principal.role)
    return {"access_token": token, "token_type": "bearer", "role": principal.role}


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
    req: TransferRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(current_customer),
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

    try:
        dst_account = req.dst_account or service.account_id_by_iban(req.dst_iban)
        if honeytokens.is_honey_account(dst_account):
            # Bénéficiaire = compte leurre : son IBAN ne se trouve que dans la base.
            honeytokens.trigger(
                "transfer", request.headers.get("x-real-ip"), f"user={principal.username}"
            )
            raise service.BusinessError("destination account not found")
    except service.BusinessError as exc:
        PAYMENT_TX.labels(result="rejected").inc()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception as exc:
        PAYMENT_TX.labels(result="error").inc()
        log.error("destination lookup failed: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "transfer backend unavailable"
        ) from exc

    if settings.face_confirmation_required:
        return _create_pending(req, dst_account, amount, principal, response)

    try:
        if service.degraded(settings.degraded_max_minutes):
            pending = service.create_pending(
                username=principal.username,
                src_account=req.src_account,
                dst_account=dst_account,
                amount=amount,
                ttl_seconds=60,
            )
            tx = service.queue_pending(pending["id"], principal.username)
            PAYMENT_TX.labels(result="queued").inc()
            response.status_code = status.HTTP_202_ACCEPTED
            return {**tx, "amount": str(tx["amount"])}
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
    req: TransferRequest,
    dst_account: int,
    amount: Decimal,
    principal: Principal,
    response: Response,
) -> dict:
    try:
        if biometrics.get_enrollment(principal.username) is None:
            raise _face_error(status.HTTP_403_FORBIDDEN, "face_not_enrolled")
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
        distance = face.best_distance(probe, list(enrollment["poses"].values()))
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
    events.publish({"ok": result == "match", "purpose": "confirm"})

    if result != "match":
        FACE_VERIFICATIONS.labels(purpose="confirm", result=result).inc()
        left = service.record_failed_attempt(tx_id, settings.face_max_attempts_per_tx)
        if left == 0:
            PAYMENT_TX.labels(result="rejected").inc()
        code = "spoof" if result == "spoof" else "face_mismatch"
        raise _face_error(status.HTTP_403_FORBIDDEN, code, attempts_left=left)

    FACE_VERIFICATIONS.labels(purpose="confirm", result="match").inc()
    try:
        if service.degraded(settings.degraded_max_minutes):
            # Remédiation en cours : identité validée, règlement différé au rejeu.
            queued = service.queue_pending(tx_id, user)
            PAYMENT_TX.labels(result="queued").inc()
            log.info("virement mis en file (mode dégradé) user=%s tx=%s", user, tx_id)
            return {**queued, "amount": str(queued["amount"])}
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
        "poses": sorted(enrollment["poses"].keys()) if enrollment else [],
    }


@app.post("/face/enrollment", status_code=status.HTTP_201_CREATED)
def face_enroll(req: PoseImages, principal: Principal = Depends(current_customer)) -> dict:
    """Enrôlement unique du pool de référence (une photo par pose). Seuls les
    vecteurs sont stockés. Parcours de rattrapage pour un compte créé sans
    pool complet (le consentement a déjà été donné à l'inscription)."""
    user = principal.username
    try:
        if biometrics.get_enrollment(user) is not None:
            raise _face_error(status.HTTP_409_CONFLICT, "already_enrolled")
    except HTTPException:
        raise
    except Exception as exc:
        log.error("enrollment lookup failed: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "backend unavailable") from exc

    _validate_pool(req.images)
    embeddings = _embed_pool(req.images, "enroll")

    if not biometrics.save_enrollment(user, settings.face_model, embeddings):
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


class DegradedRequest(BaseModel):
    enabled: bool


def _require_remediation(token: str | None) -> None:
    """Endpoints internes de pilotage : jeton du moteur de remédiation exigé
    (en plus du 404 du WAF sur /api/internal/)."""
    expected = settings.remediation_api_token
    if not expected or not secrets.compare_digest(token or "", expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid remediation token")


@app.post("/internal/degraded")
def internal_degraded(
    req: DegradedRequest, x_remediation_token: str | None = Header(default=None)
) -> dict:
    _require_remediation(x_remediation_token)
    service.set_degraded(req.enabled)
    log.warning("mode dégradé %s", "ACTIVÉ" if req.enabled else "levé")
    return {"degraded": req.enabled}


@app.post("/internal/replay")
def internal_replay(x_remediation_token: str | None = Header(default=None)) -> dict:
    _require_remediation(x_remediation_token)
    done = service.replay_queue()
    PAYMENT_TX.labels(result="settled").inc(done["settled"])
    PAYMENT_TX.labels(result="rejected").inc(done["rejected"])
    log.info("file d'attente rejouée: %s", done)
    return done


@app.post("/internal/canary")
def canary() -> dict:
    """Transaction canari : prouve que le chemin métier complet fonctionne
    (auth implicite seed -> débit -> crédit -> écriture). Non exposé via WAF."""
    try:
        owner, src_account, dst_account = service.canary_route()
        tx = service.transfer(
            username=owner,
            src_account=src_account,
            dst_account=dst_account,
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
