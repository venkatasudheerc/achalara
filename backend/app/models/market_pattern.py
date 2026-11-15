"""The S&P 500's record for this week and month, copied from market data"""
from sqlalchemy import JSON, Column, DateTime, String

from app.models.base import BaseModel


class MarketPatternCopy(BaseModel):
    """What the Dashboard's market-pattern tile reads.

    The daily job ``market_pattern_copy`` fills it through ``app.md.read``, so the
    tile works when market data cannot be reached and market data never sees a
    client's holdings. One row per pattern (``sp500``); it holds index history
    only, never a client, an account or a figure of theirs. Nothing in ``perf``
    reads it.
    """

    __tablename__ = "market_pattern_copies"

    key = Column(String(30), primary_key=True)
    payload = Column(JSON, nullable=False)
    refreshed_at = Column(DateTime(timezone=True), nullable=False)
