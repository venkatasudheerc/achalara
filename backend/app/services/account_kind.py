"""What kind of account an account is, read from the name the brokerage gives it.

Every account today is an investment account at a brokerage, and the brokerage's name
for it says what it is ("Roth IRA Brokerage Account", "UTMA Brokerage Account", "Cash
Plus Account"). The landing page groups accounts by this kind. Bank, card, loan and
property accounts will bring kinds of their own when they are linked.
"""
import re

TAXABLE = "taxable"
RETIREMENT = "retirement"
KIDS = "kids"
CASH = "cash"
KINDS = (TAXABLE, RETIREMENT, KIDS, CASH)

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
