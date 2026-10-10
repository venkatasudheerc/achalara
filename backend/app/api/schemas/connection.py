"""Brokerage connection request/response schemas"""
from datetime import date, datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class LinkRequest(BaseModel):
    """Start linking a brokerage login."""

    redirect_uri: str = ""


class LinkResponse(BaseModel):
    """A hosted portal URL; open it straight away, it expires quickly."""

    redirect_url: str
    expires_in_seconds: int


class ReconciliationDrift(BaseModel):
    """One symbol where brokerage holdings and our trades disagree."""

    symbol: str
    brokerage_quantity: float
    derived_quantity: float
    difference: float
    awaiting_transactions: bool


class Reconciliation(BaseModel):
    """Brokerage holdings compared with positions derived from trades."""

    matched: int = 0
    drifted: List[ReconciliationDrift] = []
    # Symbols the trades on file leave net short.
    unmatched_sells: int = 0
    skipped_rows: Dict[str, int] = {}


class BrokerageAccountResponse(BaseModel):
    """An account discovered under a connection."""

    id: str
    connection_id: str
    name: str
    number_last4: Optional[str] = None
    status: str  # unmapped | mapped | ignored
    account_id: Optional[str] = None
    default_sleeve_id: Optional[str] = None
    # Client who owns the mapped account; may differ from the connection's.
    owner_client_id: Optional[str] = None
    initial_sync_completed: bool
    transactions_synced_through: Optional[date] = None
    last_synced_at: Optional[datetime] = None
    last_reconciled_at: Optional[datetime] = None
    reconciliation: Optional[Reconciliation] = None

    class Config:
        from_attributes = True


class ConnectionResponse(BaseModel):
    """A linked brokerage login and the accounts under it."""

    id: str
    client_id: str
    source: str
    institution: str
    status: str  # active | broken | deleted
    brokerage_accounts: List[BrokerageAccountResponse] = []

    class Config:
        from_attributes = True


class BrokerageAccountUpdate(BaseModel):
    """Map a discovered account into the hierarchy, or leave it out."""

    status: Literal["mapped", "ignored"]
    # mapped only: an existing account to attach to (omit to create one), and
    # the strategy its trades land in (omit for "Unallocated").
    account_id: Optional[str] = None
    strategy_id: Optional[str] = None
    # mapped only: the client who owns the account, when that is not the client
    # whose login reaches it (an agent with authority over someone's account).
    client_id: Optional[str] = None


class SyncResult(BaseModel):
    """Outcome of one brokerage account sync."""

    status: str  # synced | skipped
    reason: Optional[str] = None  # why it was skipped
    imported: int = 0
    duplicates: int = 0
    cash_imported: int = 0
    skipped_rows: Dict[str, int] = {}
    next_sync_allowed_at: Optional[datetime] = None
    transactions_synced_through: Optional[date] = None


class ReassignRequest(BaseModel):
    """Move every trade of the named symbols to another sleeve of the account."""

    from_sleeve_id: str
    to_sleeve_id: str
    symbols: List[str]


class ReassignResult(BaseModel):
    symbols: List[str]
    trades_moved: int
    cash_activities_moved: int


class CashActivityResponse(BaseModel):
    """A dividend, fee or other non-trade money movement."""

    id: str
    sleeve_id: str
    activity_date: date
    type: str
    symbol: Optional[str] = None
    amount: float
    notes: Optional[str] = None
    counts_toward_returns: bool
