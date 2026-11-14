"""Upload and import: what a file would add to an account, and what it did."""
from datetime import date
from typing import Dict, List, Optional

from pydantic import BaseModel


class ImportTrade(BaseModel):
    action: str
    symbol: str
    quantity: float
    # Per share; per contract (100 shares) for an option.
    price: float


class ImportCash(BaseModel):
    type: str
    symbol: Optional[str] = None
    amount: float


class ImportDay(BaseModel):
    date: date
    trades: List[ImportTrade]
    cash: List[ImportCash]


class ImportNotRead(BaseModel):
    line: int
    date: date
    type: str
    symbol: str


class ImportDifference(BaseModel):
    symbol: str
    custodian_quantity: float
    our_quantity: float


class ImportCheck(BaseModel):
    """Our holdings against the custodian's last recorded ones."""

    as_of: date
    matched: int
    differences: List[ImportDifference]
    # The last recorded day our holdings agreed with the custodian's, and the
    # first one they differed after it (None while they agree now): a report
    # from the first date to today covers what is missing.
    last_agreed: Optional[date] = None
    first_differed: Optional[date] = None
    # Where a report should start to cover what is missing; None while they agree.
    download_from: Optional[date] = None


class ImportPreview(BaseModel):
    """What the file holds and what of it is not on file yet. Nothing is written."""

    account_id: str
    # vanguard_activity | template
    file_kind: str
    rows: int
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    on_file_trades: int
    on_file_cash: int
    # Recognised although the feed dated them a trading day later (option
    # expiries and assignments), or spelled their symbol differently.
    on_file_a_day_later: int
    on_file_other_symbol: int
    # Rows that are not activity: sweeps and transfers within the account.
    set_aside: Dict[str, int]
    to_add_trades: int
    to_add_cash: int
    days: List[ImportDay]
    # Rows this cannot represent (splits, mergers): the feed records those.
    not_read: List[ImportNotRead]


class ImportResult(ImportPreview):
    """The preview as it stood when written, what was added, and the check."""

    added_trades: int
    added_cash: int
    check: Optional[ImportCheck] = None
