"""Weekly portfolio snapshot — persisted Monday-boundary returns per sleeve."""
import uuid
from sqlalchemy import Column, String, Date, Float, ForeignKey, UniqueConstraint
from app.models.base import BaseModel


class WeeklyPortfolioSnapshot(BaseModel):
    """One row per (sleeve, week_start_date) capturing cumulative returns.

    week_start_date is always a Monday. Snapshots are upserted after any trade
    write that affects a sleeve; a full rebuild is available via
    POST /admin/rebuild-snapshots.

    twr_period  — HPR for the single week ending on this Monday
    twr_cumul   — geometric-linked TWR from the sleeve's inception to this week
    mwr_cumul   — IRR-derived MWR from inception to this week (holding-period)
    cost_basis  — aggregate open-position cost basis at week close
    market_value — aggregate open-position market value at week close
    cash_in     — gross BUY notional during the week
    cash_out    — gross SELL proceeds during the week, plus net investment
                  income (dividends less fees)
    realized_gain — net realized P&L from round-trips closed during the week
    """

    __tablename__ = "weekly_portfolio_snapshots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sleeve_id = Column(
        String(36), ForeignKey("sleeves.id", ondelete="CASCADE"), nullable=False
    )
    week_start_date = Column(Date, nullable=False)

    twr_period = Column(Float, nullable=True)
    twr_cumul = Column(Float, nullable=True)
    mwr_cumul = Column(Float, nullable=True)

    cost_basis = Column(Float, nullable=False, default=0.0)
    market_value = Column(Float, nullable=False, default=0.0)
    cash_in = Column(Float, nullable=False, default=0.0)
    cash_out = Column(Float, nullable=False, default=0.0)
    realized_gain = Column(Float, nullable=False, default=0.0)

    __table_args__ = (
        UniqueConstraint("sleeve_id", "week_start_date", name="uq_snapshot_sleeve_week"),
    )
