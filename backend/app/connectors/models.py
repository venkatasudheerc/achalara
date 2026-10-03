"""Normalized types — the only vocabulary that crosses the connector boundary.

Every adapter translates its vendor/source payload *into* these types. The
original payload is stashed in ``raw`` for audit/debug only and must never be
read by upstream code. Services, routes, and the ingestion pipeline depend on
these types and on ``base.BrokerageConnector`` — never on a vendor shape.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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


class RawAccount(BaseModel):
    """An account discovered at a source, before it is mapped into the hierarchy."""

    external_ref: str
    name: str
    account_number: Optional[str] = None
    institution: str = ""
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
