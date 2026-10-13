"""Position response schemas"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime  # noqa: F401


class PositionResponse(BaseModel):
    """A single open position"""

    symbol: str
    status: str = "OPEN"
    quantity: float
    cost_basis: float
    avg_cost: float
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_gain: Optional[float] = None
    unrealized_gain_pct: Optional[float] = None
    trades_count: int

    class Config:
        from_attributes = True


class ClosedPositionResponse(BaseModel):
    """A closed round-trip: one BUY matched to one SELL of the same quantity"""

    symbol: str
    status: str = "CLOSED"
    matched_quantity: Optional[float] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    realized_gain: float
    realized_gain_pct: float
    opened_at: Optional[date] = None
    closed_at: Optional[date] = None
    trades_count: int
    # As the brokerage reports the lot (see ``services/tax_lots``): cost and
    # proceeds in full, the loss a wash sale disallowed, and the gain after it
    # split by term. None where the sleeve is not matched by lots.
    cost: Optional[float] = None
    proceeds: Optional[float] = None
    disallowed_loss: Optional[float] = None
    reported_gain: Optional[float] = None
    short_term_gain: Optional[float] = None
    long_term_gain: Optional[float] = None
    term: Optional[str] = None  # short | long | mixed (an index option: 60/40)
    adjustments: List[str] = []

    class Config:
        from_attributes = True


class PortfolioSummary(BaseModel):
    """Portfolio value summary"""

    total_cost_basis: float
    total_market_value: float
    total_unrealized_gain: float
    total_return_pct: float
    total_realized_gain: float
    positions_count: int
    closed_positions_count: int

    class Config:
        from_attributes = True


class PortfolioValueResponse(BaseModel):
    """Full portfolio value — open positions + summary"""

    summary: PortfolioSummary
    positions: List[PositionResponse]

    class Config:
        from_attributes = True


class ClosedPositionsResponse(BaseModel):
    """All closed positions for a sleeve"""

    total_realized_gain: float
    total_reported_gain: Optional[float] = None
    total_disallowed_loss: Optional[float] = None
    positions: List[ClosedPositionResponse]

    class Config:
        from_attributes = True
