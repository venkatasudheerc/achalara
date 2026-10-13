"""Performance models — the ``perf`` schema.

Everything that describes how accounts and sleeves performed over time lives
here, apart from the operational tables in ``public``. New performance tables
belong in this schema too.

The stored grain is the day. Weeks, months, quarters, year-to-date and the
client and strategy roll-ups are all read from these rows; none is stored.
"""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    false,
)
import uuid
from app.models.base import BaseModel

SCHEMA = "perf"


def _uuid() -> str:
    return str(uuid.uuid4())


# The source of a price entered by hand (``python -m app.cli set-price``).
MANUAL_SOURCE = "manual"


class DailyPrice(BaseModel):
    """A security's closing price on one day, from one source.

    ``webull`` closes are adjusted for later splits and dividends, as the
    source delivers them; ``brokerage`` closes are the price the brokerage put
    on a holding that day, unadjusted. The two are not interchangeable, which
    is why the source is part of the key. ``manual`` closes are entered by
    hand for what no source prices: the year-end price an index option is
    marked to (quoted per share, like the option itself).
    """

    __tablename__ = "daily_price"

    id = Column(String(36), primary_key=True, default=_uuid)
    symbol = Column(String(50), nullable=False, index=True)
    price_date = Column(Date, nullable=False)
    close = Column(Numeric(15, 6), nullable=False)
    source = Column(String(20), nullable=False)  # webull | brokerage | manual
    fetched_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "symbol", "price_date", "source", name="uq_daily_price_symbol_date_source"
        ),
        {"schema": SCHEMA},
    )


class DailyHolding(BaseModel):
    """One security the brokerage reported an account as holding on one day.

    A record of fact, captured on the day: it cannot be recovered accurately
    afterwards. A security appears on the days it was held and on no others;
    this is not a per-position performance history.
    """

    __tablename__ = "daily_holding"

    id = Column(String(36), primary_key=True, default=_uuid)
    account_id = Column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    # The sleeve the holding is attributed to that day.
    sleeve_id = Column(String(36), ForeignKey("sleeves.id", ondelete="SET NULL"))
    as_of_date = Column(Date, nullable=False)
    symbol = Column(String(50), nullable=False)
    security_type = Column(String(20))
    quantity = Column(Numeric(18, 8), nullable=False)  # negative for a short
    price = Column(Numeric(15, 6))
    market_value = Column(Numeric(18, 2), nullable=False)
    # The brokerage's own cost per unit; NULL when it reported none (a lot
    # bought since its last transaction sync).
    avg_cost = Column(Numeric(15, 6))
    captured_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "account_id", "as_of_date", "symbol", name="uq_daily_holding_account_day"
        ),
        {"schema": SCHEMA},
    )


class DailyValuation(BaseModel):
    """What one sleeve or one account was worth on one day, and what moved.

    The single table every return, period figure and report number is read
    from. A row is for a sleeve or for an account, never both.

    ``basis`` says how the value was arrived at: ``observed`` rows were
    captured from the brokerage's own figures on the day and their values are
    never rewritten; ``reconstructed`` rows were rebuilt from trades and price
    history and are replaced whenever that history changes.
    """

    __tablename__ = "daily_valuation"

    id = Column(String(36), primary_key=True, default=_uuid)
    sleeve_id = Column(String(36), ForeignKey("sleeves.id", ondelete="CASCADE"))
    account_id = Column(String(36), ForeignKey("accounts.id", ondelete="CASCADE"))
    as_of_date = Column(Date, nullable=False)
    securities_value = Column(Numeric(18, 2), nullable=False)
    # What the positions open at the day's close had cost (first-in-first-out
    # lots; a short counts as the proceeds received, negative). Valuing at
    # this instead of at market gives returns on a realised basis.
    cost_value = Column(Numeric(18, 2))
    # Account rows only; NULL where cash is not tracked.
    cash_value = Column(Numeric(18, 2))
    total_value = Column(Numeric(18, 2), nullable=False)
    flow_in = Column(Numeric(18, 2), nullable=False, default=0)
    flow_out = Column(Numeric(18, 2), nullable=False, default=0)
    advisory_fees = Column(Numeric(18, 2), nullable=False, default=0)
    # 1 + the day's net time-weighted return; NULL with no capital at work.
    return_factor = Column(Numeric(18, 10))
    # Part of securities_value held at its last traded price for want of a
    # close: options, delisted names.
    unpriced_value = Column(Numeric(18, 2), nullable=False, default=0)
    basis = Column(String(15), nullable=False)  # observed | reconstructed
    # True while the brokerage's transactions for the day may still be
    # arriving: the value is final, its split into flows and gain is not.
    is_provisional = Column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    computed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "(sleeve_id IS NULL) <> (account_id IS NULL)",
            name="daily_valuation_one_owner",
        ),
        UniqueConstraint("sleeve_id", "as_of_date", name="uq_daily_valuation_sleeve"),
        UniqueConstraint("account_id", "as_of_date", name="uq_daily_valuation_account"),
        {"schema": SCHEMA},
    )


class CorporateAction(BaseModel):
    """An event that changes share counts without a trade.

    Only splits are recorded and applied so far; ``action_type`` leaves room
    for mergers and spin-offs.
    """

    __tablename__ = "corporate_action"

    id = Column(String(36), primary_key=True, default=_uuid)
    symbol = Column(String(50), nullable=False, index=True)
    effective_date = Column(Date, nullable=False)
    action_type = Column(String(20), nullable=False)  # SPLIT
    # For a split: shares after / shares before.
    ratio = Column(Numeric(12, 6), nullable=False)
    source = Column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "effective_date",
            "action_type",
            name="uq_corporate_action_symbol_date_type",
        ),
        {"schema": SCHEMA},
    )
