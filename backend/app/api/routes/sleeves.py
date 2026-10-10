"""Sleeve endpoints — a strategy as run within a specific account.

Sleeves own trades, positions, market prices and performance. They live under
an account: /clients/{client_id}/accounts/{account_id}/sleeves.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from decimal import Decimal
from datetime import date
from typing import Optional
import uuid

from app.db.database import get_db
from app.models.account import Account
from app.models.strategy import Strategy
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.models.position import Position as PositionModel
from app.services.portfolio_calculation import PortfolioCalculationService
from app.services.market_price import MarketPriceService
from app.connectors.webull_connector import WebullConnector
from app.services.performance_service import PerformanceService
from app.services.cash_activity_service import CashActivityService
from app.api.schemas.connection import CashActivityResponse
from app.api.schemas.position import (
    PositionResponse,
    ClosedPositionResponse,
    PortfolioValueResponse,
    ClosedPositionsResponse,
    PortfolioSummary,
)
from app.api.schemas.performance import LevelPerformance, MonthlyReturnsResponse, MonthlyReturn

router = APIRouter()


class SleeveCreate(BaseModel):
    """Create sleeve request — links a global strategy to this account."""

    strategy_id: str


class SleeveResponse(BaseModel):
    """Sleeve response."""

    id: str
    account_id: str
    strategy_id: str
    strategy_name: Optional[str] = None

    class Config:
        from_attributes = True


class MarketPriceUpdate(BaseModel):
    """Update market prices."""

    prices: dict  # {symbol: price}


def _get_account_or_404(db: Session, client_id: str, account_id: str) -> Account:
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.client_id == client_id)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _get_sleeve_or_404(
    db: Session, client_id: str, account_id: str, sleeve_id: str
) -> Sleeve:
    _get_account_or_404(db, client_id, account_id)
    sleeve = (
        db.query(Sleeve)
        .filter(Sleeve.id == sleeve_id, Sleeve.account_id == account_id)
        .first()
    )
    if not sleeve:
        raise HTTPException(status_code=404, detail="Sleeve not found")
    return sleeve


@router.post(
    "/{client_id}/accounts/{account_id}/sleeves",
    response_model=SleeveResponse,
    status_code=201,
)
def create_sleeve(
    client_id: str,
    account_id: str,
    body: SleeveCreate,
    db: Session = Depends(get_db),
):
    """Apply a global strategy to this account (create a sleeve)."""
    _get_account_or_404(db, client_id, account_id)

    strategy = db.query(Strategy).filter(Strategy.id == body.strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    existing = (
        db.query(Sleeve)
        .filter(Sleeve.account_id == account_id, Sleeve.strategy_id == body.strategy_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail="Sleeve already exists for this strategy"
        )

    sleeve = Sleeve(
        id=str(uuid.uuid4()), account_id=account_id, strategy_id=body.strategy_id
    )
    db.add(sleeve)
    db.commit()
    db.refresh(sleeve)
    return SleeveResponse(
        id=sleeve.id,
        account_id=sleeve.account_id,
        strategy_id=sleeve.strategy_id,
        strategy_name=strategy.name,
    )


@router.get("/{client_id}/accounts/{account_id}/sleeves")
def list_sleeves(client_id: str, account_id: str, db: Session = Depends(get_db)):
    """List all sleeves in an account."""
    _get_account_or_404(db, client_id, account_id)
    sleeves = (
        db.query(Sleeve, Strategy)
        .join(Strategy, Sleeve.strategy_id == Strategy.id)
        .filter(Sleeve.account_id == account_id)
        .all()
    )
    return [
        SleeveResponse(
            id=s.id,
            account_id=s.account_id,
            strategy_id=s.strategy_id,
            strategy_name=strat.name,
        )
        for s, strat in sleeves
    ]


@router.get(
    "/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}",
    response_model=SleeveResponse,
)
def get_sleeve(
    client_id: str, account_id: str, sleeve_id: str, db: Session = Depends(get_db)
):
    """Get a single sleeve."""
    sleeve = _get_sleeve_or_404(db, client_id, account_id, sleeve_id)
    strategy = db.query(Strategy).filter(Strategy.id == sleeve.strategy_id).first()
    return SleeveResponse(
        id=sleeve.id,
        account_id=sleeve.account_id,
        strategy_id=sleeve.strategy_id,
        strategy_name=strategy.name if strategy else None,
    )


@router.get(
    "/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/performance",
    response_model=LevelPerformance,
)
def get_sleeve_performance(
    client_id: str,
    account_id: str,
    sleeve_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Sleeve-level performance: summary + value time-series."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date must be before end_date"
        )
    sleeve = _get_sleeve_or_404(db, client_id, account_id, sleeve_id)
    strategy = db.query(Strategy).filter(Strategy.id == sleeve.strategy_id).first()

    perf = PerformanceService(db).performance([sleeve_id], start_date, end_date)
    return {
        "level": "sleeve",
        "id": sleeve_id,
        "name": strategy.name if strategy else None,
        "start_date": perf.get("start_date"),
        "end_date": perf.get("end_date"),
        "summary": perf["summary"],
        "timeseries": perf["timeseries"],
        "children": [],
    }


@router.get(
    "/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/performance/returns-series",
)
def get_sleeve_returns_series(
    client_id: str,
    account_id: str,
    sleeve_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """Weekly TWR + MWR timeseries for a sleeve."""
    _get_sleeve_or_404(db, client_id, account_id, sleeve_id)
    from app.services.weekly_snapshot_service import WeeklySnapshotService
    series = WeeklySnapshotService(db).returns_series([sleeve_id], start_date, end_date)
    return {"level": "sleeve", "id": sleeve_id, "series": series}


@router.get(
    "/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/performance/monthly",
    response_model=MonthlyReturnsResponse,
)
def get_sleeve_monthly_returns(
    client_id: str,
    account_id: str,
    sleeve_id: str,
    db: Session = Depends(get_db),
):
    """Month-on-month return breakdown since inception."""
    _get_sleeve_or_404(db, client_id, account_id, sleeve_id)
    svc = PerformanceService(db)
    months = svc.monthly_returns([sleeve_id])
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


@router.get(
    "/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions",
    response_model=PortfolioValueResponse,
)
def get_sleeve_positions(
    client_id: str, account_id: str, sleeve_id: str, db: Session = Depends(get_db)
):
    """Get open positions and portfolio value for a sleeve."""
    _get_sleeve_or_404(db, client_id, account_id, sleeve_id)

    calc_service = PortfolioCalculationService(db)
    perf_svc = PerformanceService(db)

    open_positions = (
        db.query(PositionModel)
        .filter(PositionModel.sleeve_id == sleeve_id, PositionModel.status == "OPEN")
        .all()
    )
    raw_prices = perf_svc.fetch_and_persist_prices(open_positions)
    prices = {sym: p for sym, p in raw_prices.items()}

    portfolio = calc_service.calculate_account_value(sleeve_id, prices)

    summary = PortfolioSummary(**portfolio)
    position_responses = [
        PositionResponse(
            symbol=pos["symbol"],
            status="OPEN",
            quantity=float(pos["quantity"]),
            cost_basis=float(pos["cost_basis"]),
            avg_cost=float(pos["avg_cost"]),
            current_price=float(pos["current_price"])
            if pos.get("current_price")
            else None,
            market_value=float(pos["market_value"])
            if pos.get("market_value")
            else None,
            unrealized_gain=float(pos["unrealized_gain"])
            if pos.get("unrealized_gain")
            else None,
            unrealized_gain_pct=pos.get("unrealized_gain_pct"),
            trades_count=pos["trades_count"],
        )
        for pos in portfolio["positions"]
    ]

    return PortfolioValueResponse(summary=summary, positions=position_responses)


@router.get(
    "/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions/closed",
    response_model=ClosedPositionsResponse,
)
def get_sleeve_closed_positions(
    client_id: str, account_id: str, sleeve_id: str, db: Session = Depends(get_db)
):
    """Get all closed round-trips and their realized gains for a sleeve."""
    _get_sleeve_or_404(db, client_id, account_id, sleeve_id)

    calc_service = PortfolioCalculationService(db)
    result = calc_service.calculate_positions(sleeve_id)

    closed = result["closed"]
    total_realized = sum(p["realized_gain"] for p in closed)

    position_responses = [
        ClosedPositionResponse(
            symbol=pos["symbol"],
            status="CLOSED",
            matched_quantity=pos.get("matched_quantity"),
            entry_price=pos.get("entry_price"),
            exit_price=pos.get("exit_price"),
            realized_gain=float(pos["realized_gain"]),
            realized_gain_pct=float(pos["realized_gain_pct"]),
            opened_at=pos.get("opened_at"),
            closed_at=pos.get("closed_at"),
            trades_count=pos["trades_count"],
        )
        for pos in closed
    ]

    return ClosedPositionsResponse(
        total_realized_gain=float(total_realized),
        positions=position_responses,
    )


@router.get("/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/trades")
def get_sleeve_trades(
    client_id: str,
    account_id: str,
    sleeve_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Get trades for a sleeve with pagination."""
    _get_sleeve_or_404(db, client_id, account_id, sleeve_id)

    trades = (
        db.query(Trade)
        .filter(Trade.sleeve_id == sleeve_id)
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "sleeve_id": sleeve_id,
        "total": db.query(Trade).filter(Trade.sleeve_id == sleeve_id).count(),
        "trades": [
            {
                "id": t.id,
                "trade_date": t.trade_date,
                "symbol": t.symbol,
                "action": t.action,
                "quantity": float(t.quantity),
                "price": float(t.price),
                "commission": float(t.commission),
                "notes": t.notes,
            }
            for t in trades
        ],
    }


@router.get(
    "/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/cash-activities",
    response_model=list[CashActivityResponse],
)
def get_sleeve_cash_activities(
    client_id: str, account_id: str, sleeve_id: str, db: Session = Depends(get_db)
):
    """Dividends, fees and other non-trade money movements for a sleeve."""
    _get_sleeve_or_404(db, client_id, account_id, sleeve_id)
    return CashActivityService(db).list_for_sleeves([sleeve_id])


@router.post("/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/market-prices")
def update_market_prices(
    client_id: str,
    account_id: str,
    sleeve_id: str,
    prices_update: MarketPriceUpdate,
    db: Session = Depends(get_db),
):
    """Update market prices for a sleeve's symbols."""
    _get_sleeve_or_404(db, client_id, account_id, sleeve_id)

    decimal_prices = {
        symbol: Decimal(str(price)) for symbol, price in prices_update.prices.items()
    }

    # Update in-memory override store
    market_service = MarketPriceService()
    result = market_service.update_prices_bulk(decimal_prices)

    # Persist to Position table for consistency
    calc_service = PortfolioCalculationService(db)
    portfolio = calc_service.calculate_account_value(sleeve_id, decimal_prices)
    calc_service.persist_positions(sleeve_id, portfolio["positions"])

    return result


@router.post(
    "/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/fetch-market-prices"
)
def fetch_market_prices_from_webull(
    client_id: str, account_id: str, sleeve_id: str, db: Session = Depends(get_db)
):
    """Fetch current market prices from Webull API for a sleeve's symbols."""
    _get_sleeve_or_404(db, client_id, account_id, sleeve_id)

    # Get symbols from trades
    trades = db.query(Trade).filter(Trade.sleeve_id == sleeve_id).all()
    if not trades:
        raise HTTPException(status_code=400, detail="No trades in sleeve")

    symbols = list(set(t.symbol for t in trades))

    # Fetch live prices through the connector layer (vendor stays sealed inside).
    connector = WebullConnector()
    fetched_prices = {}
    failed_symbols = []

    for symbol in symbols:
        try:
            price = connector.get_price(symbol)
            if price is not None:
                fetched_prices[symbol] = float(price)
            else:
                failed_symbols.append(symbol)
        except Exception as e:
            failed_symbols.append(f"{symbol} ({str(e)})")

    if fetched_prices:
        decimal_prices = {s: Decimal(str(p)) for s, p in fetched_prices.items()}
        calc_service = PortfolioCalculationService(db)
        portfolio = calc_service.calculate_account_value(sleeve_id, decimal_prices)
        calc_service.persist_positions(sleeve_id, portfolio["positions"])

    return {
        "status": "success" if not failed_symbols else "partial",
        "fetched": len(fetched_prices),
        "symbols": list(fetched_prices.keys()),
        "prices": fetched_prices,
        "failed": failed_symbols,
    }
