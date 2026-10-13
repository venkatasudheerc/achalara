"""Brokerage connection endpoints"""
import base64
import hashlib
import hmac
import json
import logging
from contextlib import contextmanager
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.schemas.connection import (
    BrokerageAccountResponse,
    BrokerageAccountUpdate,
    ConnectionResponse,
    LinkRequest,
    LinkResponse,
    Reconciliation,
    SyncResult,
)
from app.config import settings
from app.connectors.models import NotSupported
from app.db.database import get_db
from app.services import alerts
from app.services.connection_service import (
    ConnectionService,
    sync_brokerage_account,
)

logger = logging.getLogger(__name__)

# Mounted at /api/v1; paths below carry their own resource prefix.
router = APIRouter()
# Not behind sign-in: SnapTrade calls it, and it verifies the body's signature.
public_router = APIRouter()


@contextmanager
def _http_errors():
    """Translate service errors into HTTP responses."""
    try:
        yield
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except NotSupported as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Brokerage request failed: %s", exc)
        raise HTTPException(status_code=502, detail="The brokerage source failed")


@router.post(
    "/clients/{client_id}/connections/snaptrade/link", response_model=LinkResponse
)
def start_link(
    client_id: str, body: LinkRequest = LinkRequest(), db: Session = Depends(get_db)
):
    """Get a hosted portal URL for linking a brokerage login."""
    with _http_errors():
        return ConnectionService(db).start_link(
            client_id, body.redirect_uri, body.connection_id
        )


@router.post(
    "/clients/{client_id}/connections/discover",
    response_model=List[ConnectionResponse],
)
def discover_connections(client_id: str, db: Session = Depends(get_db)):
    """Record the logins and accounts the source reports; run after linking."""
    with _http_errors():
        return ConnectionService(db).discover(client_id)


@router.get("/clients/{client_id}/connections", response_model=List[ConnectionResponse])
def list_connections(client_id: str, db: Session = Depends(get_db)):
    """List a client's brokerage connections and their accounts."""
    with _http_errors():
        return ConnectionService(db).list_connections(client_id)


@router.delete("/connections/{connection_id}", status_code=204)
def remove_connection(connection_id: str, db: Session = Depends(get_db)):
    """Revoke a brokerage login. Trades already ingested are kept."""
    with _http_errors():
        ConnectionService(db).remove_connection(connection_id)


@router.patch(
    "/brokerage-accounts/{brokerage_account_id}",
    response_model=BrokerageAccountResponse,
)
def update_brokerage_account(
    brokerage_account_id: str,
    body: BrokerageAccountUpdate,
    db: Session = Depends(get_db),
):
    """Map a discovered account into the hierarchy, or mark it ignored."""
    with _http_errors():
        service = ConnectionService(db)
        if body.status == "ignored":
            return service.ignore_account(brokerage_account_id)
        return service.map_account(
            brokerage_account_id,
            body.account_id,
            body.strategy_id,
            body.client_id,
            body.strategy_routes,
            body.history_start,
        )


@router.post(
    "/brokerage-accounts/{brokerage_account_id}/sync", response_model=SyncResult
)
def sync_account(
    brokerage_account_id: str,
    full_history: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Pull new activity for a mapped account (at most once per 24 hours).

    ``full_history`` reloads from the account's first day rather than from
    where the last sync left off.
    """
    with _http_errors():
        return sync_brokerage_account(
            db, brokerage_account_id, full_history=full_history
        )


@router.get(
    "/brokerage-accounts/{brokerage_account_id}/reconciliation",
    response_model=Reconciliation,
)
def get_reconciliation(brokerage_account_id: str, db: Session = Depends(get_db)):
    """The last comparison of brokerage holdings against derived positions."""
    with _http_errors():
        account = ConnectionService(db).get_brokerage_account(brokerage_account_id)
        return account.reconciliation or {}


async def _raw_body(request: Request) -> bytes:
    """The request body exactly as sent; a signature covers these bytes."""
    return await request.body()


def _signature_valid(body: bytes, signature: str) -> bool:
    """Whether ``signature`` is the HMAC-SHA256 of ``body`` under our consumer key."""
    key = settings.snaptrade_consumer_key
    if not key or not signature:
        return False
    digest = hmac.new(key.encode(), body, hashlib.sha256).digest()
    candidates = (base64.b64encode(digest).decode(), digest.hex())
    return any(hmac.compare_digest(signature.strip(), c) for c in candidates)


@public_router.post("/webhooks/snaptrade")
def snaptrade_webhook(
    body: bytes = Depends(_raw_body),
    signature: str = Header(default="", alias="Signature"),
    db: Session = Depends(get_db),
):
    """Receive a SnapTrade event. Unsigned or mis-signed bodies are rejected."""
    # Nothing in the body is trusted, or even parsed, until the signature holds.
    if not _signature_valid(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Body is not JSON")
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Body is not an event")

    try:
        outcome = ConnectionService(db).handle_webhook(event)
    except Exception as exc:  # noqa: BLE001
        # Acknowledge anyway: the daily job will catch up, and a non-2xx only
        # makes the source redeliver an event we already failed on.
        db.rollback()
        logger.error("SnapTrade webhook %s failed: %s", event.get("eventType"), exc)
        outcome = "failed"
    # A link breaking or mending arrives this way: say so without waiting.
    try:
        alerts.run_status_watch(db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Status watch after a webhook failed: %s", exc)
    return {"status": outcome}
