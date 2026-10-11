"""Period performance, statistics and the account report.

All read from ``perf.daily_valuation``; nothing here is computed from trades.
"""
import re
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.schemas.performance import PeriodsResponse, StatisticsResponse
from app.db.database import get_db
from app.models.account import Account
from app.models.client import Client
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.services.performance_stats_service import GRAINS, PerformanceStatsService

# Mounted at /api/v1; paths below carry their own resource prefix.
router = APIRouter()

_GRAIN = Query("month", description="day | week | month | quarter | year")
_BENCHMARK = Query(None, description="Benchmark ticker, e.g. SPY")


def _periods(
    db,
    level,
    entity_id,
    name,
    grain,
    start_date,
    end_date,
    benchmark,
    sleeve_ids=(),
    account_ids=(),
):
    if grain not in GRAINS:
        raise HTTPException(
            status_code=422, detail=f"grain must be one of {', '.join(GRAINS)}"
        )
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be before end_date"
        )
    stats = PerformanceStatsService(db)
    series = stats.daily(sleeve_ids=sleeve_ids, account_ids=account_ids)
    return {
        "level": level,
        "id": entity_id,
        "name": name,
        "grain": grain,
        "benchmark": benchmark.upper() if benchmark else None,
        "periods": stats.periods(series, grain, start_date, end_date, benchmark),
    }


def _client_or_404(db: Session, client_id: str) -> Client:
    client = db.query(Client).filter(Client.id == client_id).first()
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _account_or_404(db: Session, client_id: str, account_id: str) -> Account:
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.client_id == client_id)
        .first()
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get("/clients/{client_id}/performance/periods", response_model=PeriodsResponse)
def client_periods(
    client_id: str,
    grain: str = _GRAIN,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    benchmark: Optional[str] = _BENCHMARK,
    db: Session = Depends(get_db),
):
    """A client's performance by period: all their accounts added together."""
    client = _client_or_404(db, client_id)
    account_ids: List[str] = [
        row[0] for row in db.query(Account.id).filter(Account.client_id == client_id)
    ]
    return _periods(
        db,
        "client",
        client_id,
        client.name,
        grain,
        start_date,
        end_date,
        benchmark,
        account_ids=account_ids,
    )


@router.get(
    "/clients/{client_id}/accounts/{account_id}/performance/periods",
    response_model=PeriodsResponse,
)
def account_periods(
    client_id: str,
    account_id: str,
    grain: str = _GRAIN,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    benchmark: Optional[str] = _BENCHMARK,
    db: Session = Depends(get_db),
):
    """An account's performance by period, cash included where it is known."""
    account = _account_or_404(db, client_id, account_id)
    return _periods(
        db,
        "account",
        account_id,
        account.name,
        grain,
        start_date,
        end_date,
        benchmark,
        account_ids=[account_id],
    )


@router.get(
    "/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/performance/periods",
    response_model=PeriodsResponse,
)
def sleeve_periods(
    client_id: str,
    account_id: str,
    sleeve_id: str,
    grain: str = _GRAIN,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    benchmark: Optional[str] = _BENCHMARK,
    db: Session = Depends(get_db),
):
    """A sleeve's performance by period (securities only)."""
    _account_or_404(db, client_id, account_id)
    found = (
        db.query(Sleeve, Strategy)
        .join(Strategy, Sleeve.strategy_id == Strategy.id)
        .filter(Sleeve.id == sleeve_id, Sleeve.account_id == account_id)
        .first()
    )
    if found is None:
        raise HTTPException(status_code=404, detail="Sleeve not found")
    return _periods(
        db,
        "sleeve",
        sleeve_id,
        found[1].name,
        grain,
        start_date,
        end_date,
        benchmark,
        sleeve_ids=[sleeve_id],
    )


@router.get(
    "/strategies/{strategy_id}/performance/periods", response_model=PeriodsResponse
)
def strategy_periods(
    strategy_id: str,
    grain: str = _GRAIN,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    benchmark: Optional[str] = _BENCHMARK,
    db: Session = Depends(get_db),
):
    """A strategy's performance by period: every sleeve running it, together."""
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    sleeve_ids = [
        row[0] for row in db.query(Sleeve.id).filter(Sleeve.strategy_id == strategy_id)
    ]
    return _periods(
        db,
        "strategy",
        strategy_id,
        strategy.name,
        grain,
        start_date,
        end_date,
        benchmark,
        sleeve_ids=sleeve_ids,
    )


@router.get(
    "/clients/{client_id}/accounts/{account_id}/performance/statistics",
    response_model=StatisticsResponse,
)
def account_statistics(
    client_id: str,
    account_id: str,
    as_of: Optional[date] = Query(None, description="Report date; default latest"),
    db: Session = Depends(get_db),
):
    """Period returns, account activity, drawdowns and risk for an account."""
    account = _account_or_404(db, client_id, account_id)
    stats = PerformanceStatsService(db)
    figures = stats.statistics(stats.daily(account_ids=[account_id]), as_of)
    return {"level": "account", "id": account_id, "name": account.name, **figures}


@router.get("/clients/{client_id}/accounts/{account_id}/report")
def account_report(
    client_id: str,
    account_id: str,
    as_of: Optional[date] = Query(None, description="Report date; default latest"),
    format: str = Query("pdf", description="pdf | html"),
    db: Session = Depends(get_db),
):
    """The account's investment performance report."""
    from app.services.report_service import (
        ReportService,
        ReportUnavailable,
        _display_name,
    )

    client = _client_or_404(db, client_id)
    account = _account_or_404(db, client_id, account_id)
    service = ReportService(db)
    try:
        if format == "html":
            return Response(
                service.html(client, account, as_of), media_type="text/html"
            )
        pdf = service.pdf(client, account, as_of)
    except ReportUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    # Header values must be plain ASCII, and custodians' account names are not
    # (and carry the full account number, which a filename should not).
    label = re.sub(r"[^A-Za-z0-9]+", "-", _display_name(account.name)).strip("-")
    name = f"{label or 'account'}-performance-{as_of or date.today()}.pdf"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
