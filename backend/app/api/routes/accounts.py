"""Account endpoints"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional
import uuid

from app.db.database import get_db
from app.models.account import Account
from app.models.client import Client
from app.models.strategy import Strategy
from app.models.sleeve import Sleeve
from app.services.performance_service import PerformanceService
from app.api.schemas.performance import (
    LevelPerformance,
    MonthlyReturnsResponse,
    MonthlyReturn,
)

router = APIRouter()


class AccountCreate(BaseModel):
    """Create account request"""

    name: str
    description: str = ""
    account_number: Optional[str] = None


class AccountResponse(BaseModel):
    """Account response"""

    id: str
    client_id: str
    name: str
    description: str
    account_number: str

    class Config:
        from_attributes = True


@router.post("/{client_id}/accounts", status_code=201)
def create_account(
    client_id: str, account_data: AccountCreate, db: Session = Depends(get_db)
):
    """Create a new account for a client"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    account = Account(
        id=str(uuid.uuid4()),
        client_id=client_id,
        name=account_data.name,
        description=account_data.description,
        account_number=account_data.account_number,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/{client_id}/accounts")
def list_accounts(client_id: str, db: Session = Depends(get_db)):
    """List all accounts for a client"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    accounts = db.query(Account).filter(Account.client_id == client_id).all()
    return accounts


@router.get("/{client_id}/accounts/{account_id}")
def get_account(client_id: str, account_id: str, db: Session = Depends(get_db)):
    """Get a specific account"""
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.client_id == client_id)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return account


def _account_or_404(db: Session, client_id: str, account_id: str) -> Account:
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.client_id == client_id)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get(
    "/{client_id}/accounts/{account_id}/performance",
    response_model=LevelPerformance,
)
def get_account_performance(
    client_id: str,
    account_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Account-level roll-up: merged-flow summary + value series, plus per-sleeve
    children."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be before end_date"
        )
    account = _account_or_404(db, client_id, account_id)

    svc = PerformanceService(db)
    sleeve_rows = (
        db.query(Sleeve, Strategy)
        .join(Strategy, Sleeve.strategy_id == Strategy.id)
        .filter(Sleeve.account_id == account_id)
        .all()
    )
    sleeve_ids = [s.id for s, _ in sleeve_rows]

    perf = svc.performance(
        sleeve_ids, start_date, end_date, cash_account_ids=[account_id]
    )

    children = []
    for sleeve, strat in sleeve_rows:
        child = svc.performance([sleeve.id], start_date, end_date)
        children.append(
            {
                "level": "sleeve",
                "id": sleeve.id,
                "name": strat.name,
                "summary": child["summary"],
            }
        )

    return {
        "level": "account",
        "id": account_id,
        "name": account.name,
        "start_date": perf.get("start_date"),
        "end_date": perf.get("end_date"),
        "summary": perf["summary"],
        "timeseries": perf["timeseries"],
        "children": children,
    }


@router.get("/{client_id}/accounts/{account_id}/performance/returns-series")
def get_account_returns_series(
    client_id: str,
    account_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    basis: str = Query(
        "market",
        pattern="^(market|realized)$",
        description="market: holdings at each day's prices. realized: at cost, "
        "so unrealised gains are left out",
    ),
    db: Session = Depends(get_db),
):
    """Weekly TWR + MWR timeseries for an account."""
    account = _account_or_404(db, client_id, account_id)
    sleeve_ids = [
        s[0] for s in db.query(Sleeve.id).filter(Sleeve.account_id == account_id).all()
    ]
    from app.services.weekly_snapshot_service import WeeklySnapshotService

    series = WeeklySnapshotService(db).returns_series(
        sleeve_ids, start_date, end_date, cash_account_ids=[account_id], basis=basis
    )
    return {"level": "account", "id": account_id, "series": series}


@router.get(
    "/{client_id}/accounts/{account_id}/performance/monthly",
    response_model=MonthlyReturnsResponse,
)
def get_account_monthly_returns(
    client_id: str,
    account_id: str,
    basis: str = Query(
        "market",
        pattern="^(market|realized)$",
        description="market: holdings at each day's prices. realized: at cost, "
        "so unrealised gains are left out",
    ),
    db: Session = Depends(get_db),
):
    """Month-on-month return breakdown since inception for an account."""
    account = _account_or_404(db, client_id, account_id)
    sleeve_ids = [
        s[0] for s in db.query(Sleeve.id).filter(Sleeve.account_id == account_id).all()
    ]
    svc = PerformanceService(db)
    months = svc.monthly_returns(sleeve_ids, cash_account_ids=[account_id], basis=basis)
    cumulative = None
    non_none = [m["return_pct"] for m in months if m["return_pct"] is not None]
    if non_none:
        product = 1.0
        for r in non_none:
            product *= 1 + r / 100
        cumulative = round((product - 1) * 100, 2)
    return MonthlyReturnsResponse(
        months=[MonthlyReturn(**m) for m in months],
        cumulative_return_pct=cumulative,
    )


@router.get("/{client_id}/accounts/{account_id}/positions")
def get_account_positions(
    client_id: str, account_id: str, db: Session = Depends(get_db)
):
    """Merged positions across all sleeves in an account."""
    _account_or_404(db, client_id, account_id)
    sleeve_ids = [
        s[0] for s in db.query(Sleeve.id).filter(Sleeve.account_id == account_id).all()
    ]
    svc = PerformanceService(db)
    payload = svc.positions_payload(sleeve_ids)
    return {"account_id": account_id, **payload}
