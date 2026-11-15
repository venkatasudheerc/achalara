"""Which strategy each kind of holding belongs to, in a linked account.

A feed or a file brings stocks, funds, options and cash together. Rather than
leave them all in one sleeve, an account is set up with one sleeve per
strategy, and ``brokerage_accounts.sleeve_routes`` maps each security type to
the sleeve that takes it:

    stocks and ADRs         -> Stocks
    ETFs                    -> ETFs
    mutual funds            -> Mutual funds   (what 401(k) and 529 plans hold)
    options                 -> Options
    cash with no security   -> Cash           (deposits, interest, fees)

A dividend follows its security, and a security already in one of the
account's sleeves stays there (``ConnectionService._route``), so a symbol never
straddles two sleeves and one moved by hand stays moved. Anything with no type,
or a type with no route, goes to the account's default sleeve (Stocks).

An account that is not invested (a bank, a card, a loan) has only a Cash sleeve.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.services.account_kind import INVESTED, kind_of

STOCKS = "Stocks"
ETFS = "ETFs"
FUNDS = "Mutual funds"
OPTIONS = "Options"
CASH = "Cash"

DESCRIPTIONS = {
    STOCKS: "Individual stocks and ADRs",
    ETFS: "Exchange-traded funds",
    FUNDS: "Mutual funds, including those held in 401(k) and 529 plans",
    OPTIONS: "Options contracts",
    CASH: "Cash movements that belong to no security: deposits, interest, fees",
}

# The key in ``sleeve_routes`` that takes cash with no security.
CASH_ROUTE = "CASH"

# A security type, as the feeds and files give it, and the strategy taking it.
# ADR trades as a stock; anything unclassified is treated as one too.
TYPE_STRATEGY = {
    "STOCK": STOCKS,
    "ADR": STOCKS,
    "OTHER": STOCKS,
    "ETF": ETFS,
    "MUTUAL_FUND": FUNDS,
    "OPTION": OPTIONS,
}

# Feed sleeves are real brokerage activity: sales take the oldest shares first.
ACCOUNTING_METHOD = "FIFO"


def strategy_named(db: Session, name: str) -> Strategy:
    """The firm-wide strategy of this name (names are unique ignoring case),
    made when it does not exist yet."""
    strategy = (
        db.query(Strategy).filter(func.lower(Strategy.name) == name.lower()).first()
    )
    if strategy is None:
        strategy = Strategy(name=name, description=DESCRIPTIONS.get(name))
        db.add(strategy)
        db.flush()
    return strategy


def sleeve_in(db: Session, account_id: str, strategy_name: str) -> Sleeve:
    """The account's sleeve for a strategy, made when it does not exist yet."""
    strategy = strategy_named(db, strategy_name)
    sleeve = (
        db.query(Sleeve)
        .filter(Sleeve.account_id == account_id, Sleeve.strategy_id == strategy.id)
        .first()
    )
    if sleeve is None:
        sleeve = Sleeve(
            account_id=account_id,
            strategy_id=strategy.id,
            accounting_method=ACCOUNTING_METHOD,
        )
        db.add(sleeve)
        db.flush()
    return sleeve


def set_up(db: Session, account: Account) -> Tuple[str, Optional[Dict[str, str]]]:
    """Give an account its strategies' sleeves. Returns the default sleeve's id
    and the routes (None for an account that is not invested, which has only
    its Cash sleeve). Safe to repeat: what exists is reused."""
    if kind_of(account) not in INVESTED:
        return sleeve_in(db, account.id, CASH).id, None
    sleeves = {name: sleeve_in(db, account.id, name) for name in DESCRIPTIONS}
    routes = {
        security_type: sleeves[strategy].id
        for security_type, strategy in TYPE_STRATEGY.items()
    }
    routes[CASH_ROUTE] = sleeves[CASH].id
    return sleeves[STOCKS].id, routes


def sleeve_for_type(ba, security_type: Optional[str]) -> str:
    """Where a security of this type goes in a brokerage account."""
    return (ba.sleeve_routes or {}).get(security_type or "", ba.default_sleeve_id)


def sleeve_for_cash(ba) -> str:
    """Where cash that belongs to no security goes."""
    return (ba.sleeve_routes or {}).get(CASH_ROUTE, ba.default_sleeve_id)
