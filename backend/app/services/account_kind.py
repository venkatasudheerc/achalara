"""What kind of account an account is.

The kind is chosen when an account is added (``accounts.kind``). An account made
before kinds were chosen has none, and its kind is read from the name the
brokerage gives it ("Roth IRA Brokerage Account", "UTMA Brokerage Account",
"Cash Plus Account"). The landing page groups accounts by kind, and owed kinds
(cards and loans) count against net worth.
"""
import re
from typing import Optional

# Investments and cash at a brokerage.
TAXABLE = "taxable"
RETIREMENT = "retirement"
KIDS = "kids"
CASH = "cash"
# At a bank.
CHECKING = "checking"
SAVINGS = "savings"
# Owed.
CREDIT_CARD = "credit_card"
MORTGAGE = "mortgage"
CAR_LOAN = "car_loan"
LOAN = "loan"

KINDS = (
    TAXABLE, RETIREMENT, KIDS, CASH, CHECKING, SAVINGS, CREDIT_CARD, MORTGAGE, CAR_LOAN, LOAN,
)
# Kinds whose balance is money owed: shown as owed, and subtracted from net worth.
OWED = (CREDIT_CARD, MORTGAGE, CAR_LOAN, LOAN)
# Kinds that hold investments (holdings, trades, returns).
INVESTED = (TAXABLE, RETIREMENT, KIDS)

# Checked in order: a "Roth IRA Brokerage Account" is retirement, not taxable.
_RULES = (
    (
        RETIREMENT,
        r"\b(ira|roth|401\s*\(?k\)?|403\s*\(?b\)?|457|sep|simple|keogh|rollover|pension)\b",
    ),
    (KIDS, r"\b(utma|ugma|529|custodial|coverdell|esa)\b"),
    (CASH, r"\b(cash plus|money market|cash management|savings|checking)\b"),
)


def account_kind(name: str) -> str:
    """The kind for an account called ``name``; taxable when its name says nothing."""
    text = (name or "").lower()
    for kind, pattern in _RULES:
        if re.search(pattern, text):
            return kind
    return TAXABLE


def kind_of(account) -> str:
    """An account's kind: the one chosen for it, else the one its name implies."""
    chosen = getattr(account, "kind", None)
    return chosen if chosen in KINDS else account_kind(account.name)


_PLAID_INVESTMENT = {
    # Retirement
    **{s: RETIREMENT for s in (
        "401a", "401k", "403b", "457b", "ira", "roth", "roth 401k", "sep ira", "simple ira",
        "keogh", "pension", "retirement", "rollover ira", "sarsep", "lif", "lira", "lrif",
        "lrsp", "prif", "rdsp", "resp", "rlif", "rrif", "rrsp", "sipp", "tfsa", "thrift savings plan",
        "profit sharing plan", "stock plan", "non-taxable brokerage account",
    )},
    # Children
    **{s: KIDS for s in ("utma", "ugma", "529", "education savings account")},
    "cash management": CASH,
}


def kind_from_plaid(plaid_type: Optional[str], subtype: Optional[str], name: str = "") -> str:
    """The kind to offer for an account Plaid found, from its type and subtype;
    the client can change it before adding the account."""
    plaid_type, subtype = (plaid_type or "").lower(), (subtype or "").lower()
    if plaid_type == "credit":
        return CREDIT_CARD
    if plaid_type == "loan":
        if subtype == "mortgage":
            return MORTGAGE
        if subtype == "auto":
            return CAR_LOAN
        return LOAN
    if plaid_type == "depository":
        if subtype == "checking":
            return CHECKING
        if subtype in ("savings", "money market", "cd", "hsa"):
            return SAVINGS
        return CASH  # cash management and the like
    if plaid_type == "investment":
        return _PLAID_INVESTMENT.get(subtype) or account_kind(name)
    return account_kind(name)
