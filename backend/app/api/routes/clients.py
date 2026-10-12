"""Client endpoints"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional

from app.db.database import get_db
from app.models.client import Client
from app.models.account import Account
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.api.schemas.client import ClientCreate, ClientResponse
from app.api.schemas.performance import (
    LevelPerformance,
    MonthlyReturnsResponse,
    MonthlyReturn,
)
from app.services.performance_service import PerformanceService

router = APIRouter()


@router.post("/", response_model=ClientResponse, status_code=201)
def create_client(client: ClientCreate, db: Session = Depends(get_db)):
    """Create a new client"""
    existing = db.query(Client).filter(Client.email == client.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    db_client = Client(name=client.name, email=client.email)
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client


@router.get("/", response_model=list[ClientResponse])
def list_clients(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """List all clients with pagination, ordered by creation date."""
    return db.query(Client).order_by(Client.created_at).offset(skip).limit(limit).all()


@router.get("/{client_id}", response_model=ClientResponse)
def get_client(client_id: str, db: Session = Depends(get_db)):
    """Get client by ID"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/{client_id}/performance", response_model=LevelPerformance)
def get_client_performance(
    client_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Client-level roll-up of MWR/TWR computed on the merged cash-flow stream
    across every sleeve in the client, plus per-account children."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be before end_date"
        )
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    svc = PerformanceService(db)
    all_sleeve_ids = svc.sleeve_ids_for_client(client_id)

    perf = svc.performance(
        all_sleeve_ids,
        start_date,
        end_date,
        cash_account_ids=svc.account_ids_for_client(client_id),
    )

    accounts = db.query(Account).filter(Account.client_id == client_id).all()
    children = []
    for account in accounts:
        acct_sleeve_ids = svc.sleeve_ids_for_account(account.id)
        child = svc.performance(
            acct_sleeve_ids, start_date, end_date, cash_account_ids=[account.id]
        )
        children.append(
            {
                "level": "account",
                "id": account.id,
                "name": account.name,
                "summary": child["summary"],
            }
        )

    return {
        "level": "client",
        "id": client_id,
        "name": client.name,
        "start_date": perf.get("start_date"),
        "end_date": perf.get("end_date"),
        "summary": perf["summary"],
        "timeseries": perf["timeseries"],
        "children": children,
    }


@router.get("/{client_id}/performance/returns-series")
def get_client_returns_series(
    client_id: str,
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
    """Weekly TWR + MWR timeseries for a client (aggregated from sleeve snapshots)."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    from app.services.weekly_snapshot_service import WeeklySnapshotService

    svc = PerformanceService(db)
    sleeve_ids = svc.sleeve_ids_for_client(client_id)
    series = WeeklySnapshotService(db).returns_series(
        sleeve_ids,
        start_date,
        end_date,
        cash_account_ids=svc.account_ids_for_client(client_id),
        basis=basis,
    )
    return {"level": "client", "id": client_id, "series": series}


@router.get("/{client_id}/performance/monthly", response_model=MonthlyReturnsResponse)
def get_client_monthly_returns(
    client_id: str,
    basis: str = Query(
        "market",
        pattern="^(market|realized)$",
        description="market: holdings at each day's prices. realized: at cost, "
        "so unrealised gains are left out",
    ),
    db: Session = Depends(get_db),
):
    """Month-on-month return breakdown since inception for a client."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    svc = PerformanceService(db)
    sleeve_ids = svc.sleeve_ids_for_client(client_id)
    months = svc.monthly_returns(
        sleeve_ids, cash_account_ids=svc.account_ids_for_client(client_id), basis=basis
    )
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


@router.get("/{client_id}/positions")
def get_client_positions(client_id: str, db: Session = Depends(get_db)):
    """Get all positions merged across all sleeves for a client"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    svc = PerformanceService(db)
    sleeve_ids = svc.sleeve_ids_for_client(client_id)
    payload = svc.positions_payload(sleeve_ids)
    return {"client_id": client_id, **payload}


@router.get("/{client_id}/trades")
def get_client_trades(
    client_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Get all trades across all sleeves for a client, with pagination"""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    base_query = (
        db.query(Trade)
        .join(Sleeve, Trade.sleeve_id == Sleeve.id)
        .join(Account, Sleeve.account_id == Account.id)
        .filter(Account.client_id == client_id)
    )
    total = base_query.count()
    trades = (
        base_query.order_by(Trade.trade_date.desc()).offset(skip).limit(limit).all()
    )

    return {
        "client_id": client_id,
        "total": total,
        "skip": skip,
        "limit": limit,
        "trades": [
            {
                "id": t.id,
                "sleeve_id": t.sleeve_id,
                "trade_date": t.trade_date,
                "symbol": t.symbol,
                "action": t.action,
                "quantity": float(t.quantity),
                "price": float(t.price),
                "commission": float(t.commission),
                "notes": t.notes,
                "security_type": t.security_type,
            }
            for t in trades
        ],
    }
