"""Account endpoints"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import date
from typing import List, Literal, Optional
import uuid

from app.db.database import get_db
from app.models.account import Account
from app.models.client import Client
from app.models.strategy import Strategy
from app.models.sleeve import Sleeve
from app.services.auth_service import AuthService
from app.services.performance_service import PerformanceService
from app.services.portfolio_calculation import PortfolioCalculationService
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
    account_number: Optional[str] = None
    cost_basis_method: str = "FIFO"
    # True for an account another client owns that this client may view.
    # ``client_id`` is always the owner, so it differs from the client asked
    # about when ``shared``.
    shared: bool = False
    owner_name: Optional[str] = None

    class Config:
        from_attributes = True


class AccountUpdate(BaseModel):
    """Change how an account is read"""

    # Which lots a sale closes first, as set at the brokerage.
    cost_basis_method: Literal["FIFO", "MIN_TAX"]


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


@router.get("/{client_id}/accounts", response_model=List[AccountResponse])
def list_accounts(
    client_id: str,
    include_shared: bool = Query(
        True,
        description="Also list accounts of other clients this client may view, "
        "marked `shared`. False lists only the accounts the client owns.",
    ),
    db: Session = Depends(get_db),
):
    """The accounts a client owns, then those shared with them (read-only)."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return [
        AccountResponse(
            id=account.id,
            client_id=account.client_id,
            name=account.name,
            description=account.description or "",
            account_number=account.account_number,
            cost_basis_method=account.cost_basis_method,
            shared=shared,
            owner_name=account.client.name,
        )
        for account, shared in AuthService(db).accounts_for_client(client_id)
        if include_shared or not shared
    ]


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


@router.patch("/{client_id}/accounts/{account_id}")
def update_account(
    client_id: str,
    account_id: str,
    body: AccountUpdate,
    db: Session = Depends(get_db),
):
    """Set the account's cost basis method and re-read its positions under it."""
    account = _account_or_404(db, client_id, account_id)
    if account.cost_basis_method != body.cost_basis_method:
        account.cost_basis_method = body.cost_basis_method
        db.commit()
        calc = PortfolioCalculationService(db)
        for sleeve in account.sleeves:
            calc.persist_all_positions(sleeve.id)
        db.refresh(account)
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
