"""Linking an institution through Plaid."""
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
    # Another feed still writing to it: linking replaces that feed's history
    # with Plaid's (earlier history comes from the owner's files).
    replaces: Optional[str] = None


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


class PlaidConfirm(BaseModel):
    choices: List[PlaidChoice] = Field(min_length=1, max_length=50)


class PlaidConfirmed(BaseModel):
    linked: int
    added: int
    skipped: int
    # Linked to an account another feed still writes to: moved over later.
    waiting: int
