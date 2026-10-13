"""Market index history: reference data, not client data.

Kept in the ``public`` schema. The ``perf`` schema is for how clients'
accounts performed; this describes the market and belongs to no client.
"""
from sqlalchemy import BigInteger, Column, Date, DateTime, Numeric, String
from sqlalchemy import UniqueConstraint
import uuid
from app.models.base import BaseModel


class IndexBar(BaseModel):
    """One day of a market index: its open, high, low, close and volume.

    Reference data, kept as far back as a source gives it, and apart from
    ``perf.daily_price`` on purpose: nothing that values an account or works
    out its own return may read this table. An index may be chosen as a
    benchmark; its level leaves dividends out, unlike a fund's closes.

    The early years of an index were published as a closing level only. Those
    days have no ``open``, ``high`` or ``low``; none is ever filled in.
    """

    __tablename__ = "index_bars"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String(20), nullable=False, index=True)  # SPX | DJI | IXIC | NDX
    bar_date = Column(Date, nullable=False)
    open = Column(Numeric(15, 4))
    high = Column(Numeric(15, 4))
    low = Column(Numeric(15, 4))
    close = Column(Numeric(15, 4), nullable=False)
    volume = Column(BigInteger)
    source = Column(String(20), nullable=False)
    fetched_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("symbol", "bar_date", name="uq_index_bars_symbol_date"),
    )
