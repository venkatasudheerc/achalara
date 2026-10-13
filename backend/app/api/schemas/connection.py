"""Brokerage connection request/response schemas"""
from datetime import date, datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class LinkRequest(BaseModel):
    """Start linking a brokerage login."""

    redirect_uri: str = ""
    # An existing link to sign in to again, when the brokerage has stopped
    # sharing it. Omit to add a new link.
    connection_id: Optional[str] = None


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
    # Value of the brokerage's holdings beyond ours (negative if short of
    # them), at current prices. Added to today's total where cash is tracked.
    holdings_adjustment: float = 0.0
    # Correction to open options, which are held at their last traded price,
    # implied by the brokerage's own account total. Applied to today's value.
    valuation_adjustment: float = 0.0
    skipped_rows: Dict[str, int] = {}


class DuplicateAccount(BaseModel):
    """The account already in Achalara that a discovered one appears to be."""

    # same: the brokerage and full account number agree, and it cannot be added.
    # likely: the brokerage and last four digits agree; adding needs confirming.
    certainty: Literal["same", "likely"]
    account_id: str
    account_name: str
    client_id: str
    client_name: str


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
    # Security type -> sleeve id; types without an entry use default_sleeve_id.
    sleeve_routes: Optional[Dict[str, str]] = None
    sync_start_date: Optional[date] = None
    initial_sync_completed: bool
    transactions_synced_through: Optional[date] = None
    last_synced_at: Optional[datetime] = None
    last_reconciled_at: Optional[datetime] = None
    reconciliation: Optional[Reconciliation] = None
    # Advisors only, on an account not yet brought in.
    duplicate_of: Optional[DuplicateAccount] = None

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
    # mapped only: split the account by what is traded. Maps a security type
    # ("ETF") to the strategy taking those trades; other types use strategy_id.
    strategy_routes: Optional[Dict[str, str]] = None
    # mapped only: earliest activity date to load (omit for full history).
    history_start: Optional[date] = None
    # mapped only: the account shares its brokerage and last four digits with
    # one already here, and is a different account all the same.
    confirmed_distinct: bool = False


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
