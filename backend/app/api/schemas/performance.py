"""Performance metrics response schemas"""
from pydantic import BaseModel
from datetime import date
from typing import List, Optional, Any


class PerformancePoint(BaseModel):
    """One point on a portfolio value time-series."""

    date: date
    value: float
    cost_basis: float
    # Cash held that day, already included in value and cost_basis. Present
    # only for views of whole accounts whose cash is known.
    cash: Optional[float] = None
    # Net money put in since the previous point (negative if taken out), so a
    # benchmark can be given the same money on the same days.
    net_flow: float = 0.0


class PerformanceSummary(BaseModel):
    """Headline metrics for a set of sleeves (a level)."""

    mwr_pct: Optional[float] = None
    twr_pct: Optional[float] = None
    twr_note: Optional[str] = None
    total_return_pct: Optional[float] = None
    # Open-position fields (0 when portfolio is fully closed)
    total_cost_basis: float = 0.0
    total_market_value: float = 0.0
    total_unrealized_gain: float = 0.0
    # Cash held now, for views of whole accounts whose cash is known. When set,
    # mwr_pct and twr_pct are measured on securities plus cash.
    cash_balance: Optional[float] = None
    # Whole-account value now (securities + cash + corrections); the last
    # point of the value chart. None when cash is not tracked.
    total_value: Optional[float] = None
    # Corrections from the brokerage's own current figures, included in today's
    # total and returns: securities it holds that our trades do not show yet,
    # and the repricing of options held at their last traded price.
    holdings_adjustment: Optional[float] = None
    # Closed-position fields
    total_invested: float = 0.0
    total_proceeds: float = 0.0
    total_realized_gain: float = 0.0
    # Dividends and interest received less fees and tax withheld
    total_income: float = 0.0
    closed_positions_count: int = 0
    trades_count: int = 0


class ChildPerformance(BaseModel):
    """A child entity's headline summary within a roll-up."""

    level: str  # "sleeve", "account"
    id: str
    name: Optional[str] = None
    summary: PerformanceSummary
    # Populated only when level == "sleeve" and the parent is a strategy,
    # so the frontend can build the full drill-down URL.
    account_id: Optional[str] = None
    client_id: Optional[str] = None


class MonthlyReturn(BaseModel):
    """MoM return for one calendar month."""

    year: int
    month: int
    month_label: str  # e.g. "Mar 2025"
    start_value: float
    end_value: float
    cash_in: float   # BUY cash deployed this month
    cash_out: float  # SELL proceeds plus net investment income this month
    net_cash_flow: float
    realized_gain: float
    return_pct: Optional[float] = None  # None while no capital is at work
    # True for the latest month, which also carries the unrealised gain on
    # open positions to date (earlier months reflect gains as realised).
    includes_unrealized: bool = False


class MonthlyReturnsResponse(BaseModel):
    months: List[MonthlyReturn]
    cumulative_return_pct: Optional[float] = None


class LevelPerformance(BaseModel):
    """Performance at a level (sleeve / account / client): summary + chart series."""

    level: str  # "sleeve", "account", or "client"
    id: str
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    summary: PerformanceSummary
    timeseries: List[PerformancePoint] = []
    children: List[ChildPerformance] = []
