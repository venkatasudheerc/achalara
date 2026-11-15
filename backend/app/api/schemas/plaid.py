"""Linking an institution through Plaid."""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class PlaidLinkAvailability(BaseModel):
    """Whether linking with Plaid is offered, and how many logins are left."""

    available: bool
    logins_left: int


class PlaidLinkStart(BaseModel):
    link_token: str
    expiration: Optional[str] = None
    logins_left: int


class PlaidLinkFinish(BaseModel):
    """The token Plaid Link handed back."""

    public_token: str = Field(min_length=1, max_length=500)


class PlaidCandidate(BaseModel):
    """One of the client's accounts this one might be, and the evidence."""

    account_id: str
    name: str
    last_four: Optional[str] = None
    shared: bool
    relinked: bool
    same_last_four: bool
    same_institution: bool
    # None: no holdings on one side or the other to compare.
    same_holdings: Optional[bool] = None
    same_balance: bool


class PlaidFoundAccount(BaseModel):
    link_id: str
    name: str
    mask: Optional[str] = None  # the institution's real last four
    plaid_type: Optional[str] = None
    plaid_subtype: Optional[str] = None
    kind: str  # offered from Plaid's type; the person may change it
    owed: bool
    balance: Optional[float] = None
    status: str  # unmapped | mapped | matched (linked, moved over later) | ignored
    # same: one account agrees on institution, last four and holdings or balance;
    # choose: some agree on less; new: none.
    proposal: Literal["same", "choose", "new"]
    account_id: Optional[str] = None
    candidates: List[PlaidCandidate]


class PlaidFound(BaseModel):
    connection_id: str
    institution: str
    logins_left: int
    accounts: List[PlaidFoundAccount]


class PlaidChoice(BaseModel):
    link_id: str
    action: Literal["link", "new", "skip"]
    account_id: Optional[str] = None  # with link
    kind: Optional[str] = None
    # With new: whose it is (default: the person linking), who it is held for
    # (a custodial account), who else sees it (default nobody; view only) and,
    # for a brokerage account, the cost basis method.
    owner_ids: Optional[List[str]] = None
    held_for: Optional[str] = None
    share_with: List[str] = []
    share_advisor: bool = False
    cost_basis: Optional[Literal["FIFO", "MIN_TAX"]] = None


class PlaidConfirm(BaseModel):
    choices: List[PlaidChoice] = Field(min_length=1, max_length=50)


class PlaidConfirmed(BaseModel):
    linked: int
    added: int
    skipped: int
    # Linked to an account another feed still writes to: moved over later.
    waiting: int


class PlaidRefreshed(BaseModel):
    """How the viewer's own logins fared when refreshed now."""

    refreshed: int
    up_to_date: int
    needs_sign_in: int
    failed: int
    at: datetime


class PlaidDiscovered(BaseModel):
    """What checking the viewer's own logins for accounts not seen before found."""

    checked: int  # logins Plaid answered for
    new_accounts: int  # accounts shared that had no row here, now waiting to be chosen
    needs_sign_in: int  # logins that must be signed in to again first
    failed: int


class PlaidRepaired(BaseModel):
    """``active`` once Plaid reads the login again; ``needs signing in`` if not yet."""

    status: str
