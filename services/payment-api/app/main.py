"""API métier de paiement (fictif).

Endpoints publics (via WAF) : /health, /accounts/me, /transactions.
Endpoint interne (non exposé au réseau pédagogique) : /internal/canary,
utilisé par le moteur de remédiation pour prouver le retour à un état
utilisable (transaction canari réelle en base).
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from . import db, service
from .auth import Principal, current_principal
from .metrics import PAYMENT_TX, MetricsMiddleware

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
def my_accounts(principal: Principal = Depends(current_principal)) -> list[dict]:
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
    req: TransferRequest, principal: Principal = Depends(current_principal)
) -> dict:
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


@app.get("/transactions")
def list_transactions(
    limit: int = 20, principal: Principal = Depends(current_principal)
) -> list[dict]:
    """Historique du client : uniquement les opérations touchant SES comptes
    (avant : toutes les transactions de la plateforme, quel que soit l'appelant)."""
    limit = max(1, min(limit, 100))  # pagination bornée (anti-dump)
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT t.id, t.reference, t.amount, t.status, t.is_canary, t.created_at, "
                "s.iban_fake AS src_iban, d.iban_fake AS dst_iban, "
                "(su.username = %(u)s) AS outgoing "
                "FROM payment_tx t "
                "JOIN account s ON s.id = t.src_account "
                "JOIN account d ON d.id = t.dst_account "
                "JOIN app_user su ON su.id = s.owner_id "
                "JOIN app_user du ON du.id = d.owner_id "
                "WHERE su.username = %(u)s OR du.username = %(u)s "
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
