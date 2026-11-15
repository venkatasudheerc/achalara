"""Admin endpoints: system status, market data status, ticker changes and the rebuild"""
from fastapi import APIRouter, Depends, HTTPException, Query


from datetime import date
from typing import List

from pydantic import BaseModel
from sqlalchemy.orm import Session
import logging

from app.api.schemas.market_data import MarketDataStatusResponse
from app.api.schemas.status import AlertTestResponse, SystemStatusResponse
from app.db.database import get_db
from app.md import read as md_read
from app.services import alerts
from app.services.status_service import StatusService
from app.services.performance_build_service import PerformanceBuildService

router = APIRouter()


@router.get("/status", response_model=SystemStatusResponse)
def system_status(db: Session = Depends(get_db)):
    """Whether everything is running as it should: the daily jobs, brokerage
    accounts, data freshness, the last backup and recent warnings."""
    return StatusService(db).status()


@router.get("/market-data/status", response_model=MarketDataStatusResponse)
def market_data_status(db: Session = Depends(get_db)):
    """The state of the security master: its jobs, indices, coverage and tables,
    and what is not built yet."""
    return md_read.market_data_status(db)


class TickerChangeProposal(BaseModel):
    old: str
    new: str
    on: date
    company: str
    accounts: int


class TickerChangeIn(BaseModel):
    old: str
    new: str
    on: date


@router.get("/ticker-changes", response_model=List[TickerChangeProposal])
def ticker_change_proposals(db: Session = Depends(get_db)):
    """Likely ticker changes seen in the accounts' own records, waiting for a person."""
    from app.services.ticker_changes import proposals

    return proposals(db)


@router.post("/ticker-changes")
def confirm_ticker_change(body: TickerChangeIn, db: Session = Depends(get_db)):
    """Record a ticker change (read old trades under the new ticker) and rebuild
    the accounts that traded or held either."""
    from app.services.ticker_changes import record

    try:
        rebuilt = record(db, body.old, body.new, body.on, "confirmed")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"old": body.old.upper(), "new": body.new.upper(), "on": body.on, "accounts_rebuilt": rebuilt}


@router.post("/status/test-alert", response_model=AlertTestResponse)
def send_test_alert():
    """Send a test message through the configured alert channel."""
    if not alerts.configured():
        raise HTTPException(
            status_code=503, detail="No alert channel is configured on the server."
        )
    return {"sent": alerts.send("Achalara: this is a test alert. Alerts are working.")}


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Weekly snapshot rebuild
# ---------------------------------------------------------------------------


@router.post("/rebuild-performance")
def rebuild_performance(
    account_id: str = Query(None, description="Rebuild one account; omit for all"),
    db: Session = Depends(get_db),
):
    """Rebuild the daily valuation rows (``perf.daily_valuation``).

    Replaces every reconstructed row from the trades and price history on
    file. Days captured from the brokerage are kept as captured; only their
    flows and returns are refreshed. Idempotent — safe to run after correcting
    historical trades or loading more price history.
    """
    service = PerformanceBuildService(db)
    try:
        if account_id:
            written = {account_id: service.rebuild_account(account_id)}
        else:
            written = service.rebuild_all()
        return {
            "status": "success",
            "accounts_rebuilt": len(written),
            "rows_written": sum(written.values()),
        }
    except Exception as e:
        logger.error(f"Performance rebuild failed: {e}")
        raise HTTPException(status_code=500, detail=f"Rebuild failed: {str(e)}")
