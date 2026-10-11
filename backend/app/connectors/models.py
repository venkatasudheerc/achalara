"""Normalized types — the only vocabulary that crosses the connector boundary.

Every adapter translates its vendor/source payload *into* these types. The
original payload is stashed in ``raw`` for audit/debug only and must never be
read by upstream code. Services, routes, and the ingestion pipeline depend on
these types and on ``base.BrokerageConnector`` — never on a vendor shape.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# OCC option symbol: root, yymmdd, C/P, strike x1000 ("BULL270115P00020000").
# The root can carry a digit after a corporate action ("NFE1270115P00000500").
_OCC_SYMBOL = re.compile(r"^[A-Z0-9.]{1,6}\d{6}[CP]\d{8}$")


def is_option_symbol(symbol: str) -> bool:
    """Whether ``symbol`` is an option contract rather than a security."""
    return bool(_OCC_SYMBOL.match(symbol or ""))


class TradeAction(str, Enum):
    """Canonical trade action for the connector layer."""

    BUY = "BUY"
    SELL = "SELL"


class NotSupported(Exception):
    """Raised when a connector is asked for a capability it does not advertise.

    Callers should branch on ``connector.capabilities`` rather than catching
    this, but it guards the contract for the methods a source cannot honor
    (e.g. ``place_order`` on a read-only source, linking on CSV/manual).
    """


class NormalizedTrade(BaseModel):
    """A single executed trade, normalized across every source.

    ``external_id`` is the idempotent dedup key: a stable id derived from the
    source so the same trade arriving twice (e.g. a sync then a CSV re-upload)
    collapses to one. Ingestion dedups on this — never bypass it.

    ``strategy``/``account``/``notes`` carry the routing hints that CSV and
    Sheets rows provide so the shared pipeline can auto-route to the right
    sleeve without upstream code ever seeing a CSV/sheet row shape.
    """

    external_id: str
    symbol: str
    action: TradeAction
    quantity: Decimal
    price: Decimal
    currency: str = "USD"
    executed_at: datetime
    commission: Decimal = Decimal("0")
    source: str
    # ETF | STOCK | ADR | MUTUAL_FUND | CLOSED_END_FUND | PREFERRED | OTHER, or
    # None when the source does not say what kind of security this is.
    security_type: Optional[str] = None

    # Routing hints (sleeve resolution); empty when the target sleeve is explicit.
    strategy: str = ""
    account: str = ""
    notes: str = ""

    raw: dict = Field(default_factory=dict)


class NormalizedPosition(BaseModel):
    """A current holding, normalized across every source."""

    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    currency: str = "USD"
    market_price: Optional[Decimal] = None
    as_of: Optional[datetime] = None
    raw: dict = Field(default_factory=dict)


class NormalizedCashActivity(BaseModel):
    """A non-trade money movement: dividend, interest, fee, transfer.

    ``amount`` is signed from the holder's side — positive is cash received.
    ``external_id`` is the idempotent dedup key, as on ``NormalizedTrade``.
    """

    external_id: str
    type: str  # DIVIDEND | INTEREST | FEE | WITHHOLDING | CONTRIBUTION | ...
    amount: Decimal
    occurred_at: datetime
    symbol: Optional[str] = None
    security_type: Optional[str] = None
    currency: str = "USD"
    source: str
    notes: str = ""
    raw: dict = Field(default_factory=dict)


class RawActivity(BaseModel):
    """One activity exactly as the source sent it, with what was done with it.

    Kept so trades and cash rows can be re-derived when the mapping rules
    change, without asking a rate-limited source for the same data again.
    ``payload`` is for storage and audit; upstream code must not interpret it.
    """

    source_id: str  # the source's own id for the row; may be empty
    type: str  # the source's type string, unmapped
    occurred_on: Optional[date] = None
    symbol: Optional[str] = None
    outcome: str  # trade | cash | skipped:<reason>
    # What the row did to the account's cash, signed (0 for a move between
    # cash and its sweep fund, which is cash either way).
    cash_amount: Decimal = Decimal("0")
    # Whether that cash came from or went outside the account (a deposit,
    # withdrawal or transfer) rather than from trading or income within it.
    is_external_flow: bool = False
    payload: dict = Field(default_factory=dict)


class ActivityBatch(BaseModel):
    """Everything a source reported for an account over a window.

    ``skipped`` counts rows that were deliberately not ingested, by reason, so
    a gap in coverage is reported rather than silent.
    """

    trades: List[NormalizedTrade] = Field(default_factory=list)
    cash: List[NormalizedCashActivity] = Field(default_factory=list)
    # Every row fetched, including the skipped ones, verbatim.
    raw: List[RawActivity] = Field(default_factory=list)
    skipped: Dict[str, int] = Field(default_factory=dict)
    # How each trade's security type was determined, by method, so reliance on
    # a weak signal (a word in the description) is visible.
    security_type_sources: Dict[str, int] = Field(default_factory=dict)


class RawAccount(BaseModel):
    """An account discovered at a source, before it is mapped into the hierarchy."""

    external_ref: str
    name: str
    account_number: Optional[str] = None
    institution: str = ""
    # The connection (login) this account sits under, where the source has one.
    connection_ref: Optional[str] = None
    # The source's own report of transaction-history completeness. None when
    # the source does not say.
    initial_sync_completed: Optional[bool] = None
    transactions_synced_through: Optional[date] = None
    # What the source says the whole account is worth now, when it says.
    total_value: Optional[Decimal] = None
    raw: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Linking / connection lifecycle types
#
# Present in the contract from day one. Non-linkable sources (CSV, manual)
# implement the lifecycle methods as stubs and declare it via capabilities;
# the linking adapter (SnapTrade) fills these in later.
# ---------------------------------------------------------------------------


class LinkSession(BaseModel):
    """A hosted-auth session for a client to link a brokerage."""

    redirect_url: str
    session_ref: str = ""
    raw: dict = Field(default_factory=dict)


class ConnectionResult(BaseModel):
    """Outcome of completing a link flow."""

    connection_id: str
    institution: str = ""
    raw: dict = Field(default_factory=dict)


class Connection(BaseModel):
    """An established connection between a client and a brokerage."""

    connection_id: str
    institution: str = ""
    status: str = "active"
    raw: dict = Field(default_factory=dict)


class ConnectionStatus(BaseModel):
    """Health/refresh status of a connection."""

    connection_id: str
    status: str
    last_refreshed_at: Optional[datetime] = None
    raw: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Trading types (dormant until Grow; guarded by capabilities.can_trade)
# ---------------------------------------------------------------------------


class OrderRequest(BaseModel):
    """A request to place an order at a brokerage."""

    symbol: str
    action: TradeAction
    quantity: Decimal
    order_type: str = "MARKET"
    limit_price: Optional[Decimal] = None


class OrderResult(BaseModel):
    """Outcome of placing an order."""

    order_ref: str
    status: str
    raw: dict = Field(default_factory=dict)
