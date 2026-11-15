"""Sort an account that was linked as one sleeve into one sleeve per strategy.

Accounts linked before ``sleeve_routing`` have a single sleeve under the
"Unallocated" strategy that holds everything. ``plan`` says what splitting such
an account would do and writes nothing; ``apply`` does it:

* the account's one sleeve becomes its Stocks sleeve (Cash for a bank, card or
  loan), so stock history does not move at all;
* the other sleeves are made and the routes set, so rows that arrive later go
  where they belong;
* ETFs, mutual funds and options move out by symbol (a buy goes with its sells,
  and a dividend with its shares), carrying their recorded holdings;
* cash that belongs to no security moves to the Cash sleeve.

The account's own figures do not change: its returns are worked from every
sleeve together, and each move rebuilds what it touched. Sleeve-level values the
custodian's days recorded before the split stay as recorded (observed days are
never rewritten), so a sleeve's own history before the split date still shows
the old grouping. Safe to repeat: an account with nothing under "Unallocated"
has nothing to do.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.connectors.models import is_option_symbol
from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount
from app.models.cash_activity import CashActivity
from app.models.perf import DailyHolding
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.services import sleeve_routing as routing
from app.services.account_kind import INVESTED, kind_of
from app.services.connection_service import DEFAULT_STRATEGY_NAME
from app.services.trade_reassignment import reassign_symbols, reassign_unnamed_cash


@dataclass
class Move:
    to_strategy: str
    symbols: List[str]
    trades: int


@dataclass
class Plan:
    account_id: str
    # The strategy the account's one sleeve becomes; None when it has no
    # "Unallocated" sleeve (already split, or arranged by hand).
    becomes: Optional[str] = None
    moves: List[Move] = field(default_factory=list)
    unnamed_cash: int = 0
    # Symbols whose type could not be told: they stay in Stocks.
    untyped: List[str] = field(default_factory=list)

    @property
    def nothing_to_do(self) -> bool:
        return self.becomes is None and not self.moves and not self.unnamed_cash


def _unallocated_sleeve(db: Session, account_id: str) -> Optional[Sleeve]:
    return (
        db.query(Sleeve)
        .join(Strategy, Strategy.id == Sleeve.strategy_id)
        .filter(
            Sleeve.account_id == account_id,
            func.lower(Strategy.name) == DEFAULT_STRATEGY_NAME.lower(),
        )
        .first()
    )


def symbol_types(db: Session, sleeve: Sleeve) -> Dict[str, Optional[str]]:
    """Each symbol traded in the sleeve and its security type: the one its
    trades most often carry, else an option's own name, else what the
    custodian last recorded it as, else unknown (None)."""
    counts: Dict[str, Counter] = {}
    for symbol, kind, n in (
        db.query(Trade.symbol, Trade.security_type, func.count(Trade.id))
        .filter(Trade.sleeve_id == sleeve.id)
        .group_by(Trade.symbol, Trade.security_type)
    ):
        counts.setdefault(symbol, Counter())
        if kind:
            counts[symbol][kind] += n
    recorded = {
        symbol: kind
        for symbol, kind in db.query(DailyHolding.symbol, DailyHolding.security_type)
        .filter(
            DailyHolding.account_id == sleeve.account_id,
            DailyHolding.security_type.isnot(None),
        )
        .order_by(DailyHolding.as_of_date)
    }
    types: Dict[str, Optional[str]] = {}
    for symbol, counter in counts.items():
        if counter:
            types[symbol] = counter.most_common(1)[0][0]
        elif is_option_symbol(symbol):
            types[symbol] = "OPTION"
        else:
            types[symbol] = recorded.get(symbol)
    return types


def plan(db: Session, ba: BrokerageAccount) -> Plan:
    """What splitting this account would do. Writes nothing."""
    account = db.get(Account, ba.account_id)
    result = Plan(account_id=account.id)
    sleeve = _unallocated_sleeve(db, account.id)
    if sleeve is None:
        return result
    invested = kind_of(account) in INVESTED
    own = routing.STOCKS if invested else routing.CASH
    taken = (
        db.query(Sleeve.id)
        .join(Strategy, Strategy.id == Sleeve.strategy_id)
        .filter(Sleeve.account_id == account.id, func.lower(Strategy.name) == own.lower())
        .first()
    )
    # The one sleeve becomes the account's Stocks (or Cash) sleeve, unless the
    # account already has one: then its stocks move there as well.
    result.becomes = None if taken else own
    if not invested:
        return result

    grouped: Dict[str, List[str]] = {}
    for symbol, kind in sorted(symbol_types(db, sleeve).items()):
        if kind is None:
            result.untyped.append(symbol)
        target = routing.TYPE_STRATEGY.get(kind or "", routing.STOCKS)
        if target == routing.STOCKS and result.becomes:
            continue
        grouped.setdefault(target, []).append(symbol)
    for target, symbols in sorted(grouped.items()):
        trades = (
            db.query(func.count(Trade.id))
            .filter(Trade.sleeve_id == sleeve.id, Trade.symbol.in_(symbols))
            .scalar()
        )
        result.moves.append(Move(target, symbols, trades))
    result.unnamed_cash = (
        db.query(func.count(CashActivity.id))
        .filter(CashActivity.sleeve_id == sleeve.id, CashActivity.symbol.is_(None))
        .scalar()
    )
    return result


def apply(db: Session, ba: BrokerageAccount) -> Plan:
    """Split the account as ``plan`` says. Returns the plan it carried out."""
    account = db.get(Account, ba.account_id)
    result = plan(db, ba)
    sleeve = _unallocated_sleeve(db, account.id)
    if result.becomes and sleeve is not None:
        sleeve.strategy_id = routing.strategy_named(db, result.becomes).id
        sleeve.accounting_method = routing.ACCOUNTING_METHOD
        db.flush()
    default, routes = routing.set_up(db, account)
    ba.default_sleeve_id = default
    ba.sleeve_routes = routes
    db.commit()
    if sleeve is None:
        return result

    for move in result.moves:
        target = routing.sleeve_in(db, account.id, move.to_strategy)
        db.commit()
        reassign_symbols(db, sleeve.id, target.id, move.symbols)
    if result.unnamed_cash:
        cash = routing.sleeve_in(db, account.id, routing.CASH)
        db.commit()
        reassign_unnamed_cash(db, sleeve.id, cash.id)
    return result
