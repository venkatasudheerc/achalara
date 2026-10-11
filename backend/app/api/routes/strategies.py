"""Strategy definition endpoints (firm-wide, global).

A Strategy is a reusable way of investing (e.g. "Growth"). It is applied to an
account via a Sleeve; trades/positions/performance live at the sleeve level.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional
import uuid

from app.db.database import get_db
from app.models.strategy import Strategy
from app.models.sleeve import Sleeve
from app.models.account import Account
from app.services.performance_service import PerformanceService
from app.api.schemas.performance import (
    LevelPerformance,
    MonthlyReturnsResponse,
    MonthlyReturn,
)

router = APIRouter()


class StrategyCreate(BaseModel):
    """Create strategy definition request"""

    name: str
    description: str = ""


class StrategyResponse(BaseModel):
    """Strategy definition response"""

    id: str
    name: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


@router.post("/", response_model=StrategyResponse, status_code=201)
def create_strategy(body: StrategyCreate, db: Session = Depends(get_db)):
    """Create a new global strategy definition.

    Names are unique case-insensitively; a duplicate (e.g. "growth" when "Growth"
    exists) returns 409.
    """
    name = body.name.strip()
    existing = (
        db.query(Strategy).filter(func.lower(Strategy.name) == name.lower()).first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail="A strategy with this name already exists"
        )

    strategy = Strategy(id=str(uuid.uuid4()), name=name, description=body.description)
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


@router.get("/", response_model=list[StrategyResponse])
def list_strategies(db: Session = Depends(get_db)):
    """List all global strategy definitions."""
    return db.query(Strategy).order_by(Strategy.name).all()


@router.get("/{strategy_id}", response_model=StrategyResponse)
def get_strategy(strategy_id: str, db: Session = Depends(get_db)):
    """Get a strategy definition by ID."""
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@router.get("/{strategy_id}/performance", response_model=LevelPerformance)
def get_strategy_performance(
    strategy_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Roll up performance for one strategy across every account that runs it."""
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    # Fetch sleeves with their account info so we can populate drill-down fields
    sleeve_rows = (
        db.query(Sleeve, Account)
        .join(Account, Sleeve.account_id == Account.id)
        .filter(Sleeve.strategy_id == strategy_id)
        .all()
    )
    sleeve_ids = [s.id for s, _ in sleeve_rows]

    svc = PerformanceService(db)
    perf = svc.performance(sleeve_ids, start_date, end_date)

    children = []
    for sleeve, account in sleeve_rows:
        child = svc.performance([sleeve.id], start_date, end_date)
        children.append(
            {
                "level": "sleeve",
                "id": sleeve.id,
                "name": None,
                "summary": child["summary"],
                "account_id": account.id,
                "client_id": account.client_id,
            }
        )

    return {
        "level": "strategy",
        "id": strategy_id,
        "name": strategy.name,
        "start_date": perf.get("start_date"),
        "end_date": perf.get("end_date"),
        "summary": perf["summary"],
        "timeseries": perf["timeseries"],
        "children": children,
    }


@router.get("/{strategy_id}/performance/returns-series")
def get_strategy_returns_series(
    strategy_id: str,
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
    """Weekly TWR + MWR timeseries for a strategy (all sleeves running that strategy)."""
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    sleeve_ids = [
        s[0]
        for s in db.query(Sleeve.id).filter(Sleeve.strategy_id == strategy_id).all()
    ]
    from app.services.weekly_snapshot_service import WeeklySnapshotService

    series = WeeklySnapshotService(db).returns_series(
        sleeve_ids, start_date, end_date, basis=basis
    )
    return {"level": "strategy", "id": strategy_id, "series": series}


@router.get("/{strategy_id}/performance/monthly", response_model=MonthlyReturnsResponse)
def get_strategy_monthly_returns(
    strategy_id: str,
    basis: str = Query(
        "market",
        pattern="^(market|realized)$",
        description="market: holdings at each day's prices. realized: at cost, "
        "so unrealised gains are left out",
    ),
    db: Session = Depends(get_db),
):
    """Month-on-month return breakdown since inception for a strategy."""
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    sleeve_ids = [
        s[0]
        for s in db.query(Sleeve.id).filter(Sleeve.strategy_id == strategy_id).all()
    ]
    svc = PerformanceService(db)
    months = svc.monthly_returns(sleeve_ids, basis=basis)
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
