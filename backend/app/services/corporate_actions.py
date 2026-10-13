"""Corporate actions — putting share counts on one basis.

A stock split changes how many shares a holding is without any trade. Trades
before it are in old shares and trades after it in new ones, so adding them up
as they stand gives nonsense: a position that looks sold ten times over.

The fix applied here is the one price histories use: restate everything before
a split in today's shares. A trade of 4 shares at 1,000 before a 10-for-1 split
is read as 40 shares at 100. Its cash is unchanged, so flows and returns are
unaffected; only the counts and per-share prices move onto the current basis,
where they agree with later trades and with split-adjusted price history.

Stored trades are never altered. The restatement happens on read, through
``adjusted_trades``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.brokerage_connection import BrokerageAccount, BrokerageActivity
from app.models.perf import CorporateAction
from app.models.sleeve import Sleeve
from app.connectors.models import is_option_symbol
from app.models.trade import Trade

# A split entry undone within this long was never held through.
_REVERSAL_WINDOW = timedelta(days=7)
# Starts the notes of a trade made from a merger row (set by the connector).
MERGER_NOTE = "Merger: "
# Start the notes of the trade that ends an option without a price, as the
# connector writes them from the brokerage's own row type.
ASSIGNMENT_NOTE = "Assignment:"
EXPIRY_NOTE = "Expired:"
# Shares one option contract covers.
OPTION_CONTRACT_SHARES = Decimal(100)


@dataclass(frozen=True)
class TradeView:
    """A trade as the calculations should see it: in today's shares.

    Carries the fields the calculations read from ``Trade``. A separate type
    so that restating a quantity can never be flushed back to the database.
    """

    id: str
    sleeve_id: str
    trade_date: date
    symbol: str
    action: str
    quantity: Decimal
    price: Decimal
    commission: Decimal
    security_type: Optional[str]
    # False for a trade that did not happen at a market price: shares that
    # changed hands at a strike because an option was assigned.
    at_market: bool = True


def split_factors(db: Session) -> Dict[str, List[Tuple[date, Decimal]]]:
    """Every recorded split, by symbol, oldest first."""
    factors: Dict[str, List[Tuple[date, Decimal]]] = {}
    for action in (
        db.query(CorporateAction)
        .filter(CorporateAction.action_type == "SPLIT")
        .order_by(CorporateAction.effective_date)
    ):
        factors.setdefault(action.symbol, []).append(
            (action.effective_date, Decimal(str(action.ratio)))
        )
    return factors


def _factor(splits: List[Tuple[date, Decimal]], traded_on: date) -> Decimal:
    """How many of today's shares one share traded on ``traded_on`` is.

    A trade dated on the split's effective date is already in new shares.
    """
    factor = Decimal(1)
    for effective, ratio in splits:
        if effective > traded_on:
            factor *= ratio
    return factor


def adjusted_trades(db: Session, trades: Iterable[Trade]) -> List[TradeView]:
    """``trades`` as the calculations should read them, in the order given.

    Two things are applied, neither of them to the stored rows: an assigned
    option's premium is moved onto the shares that changed hands (see
    ``assignment_adjustments``), and everything before a split is restated in
    today's shares.
    """
    trades = list(trades)
    factors = split_factors(db)
    prices, deliveries = assignment_adjustments(db, {t.sleeve_id for t in trades})
    views: List[TradeView] = []
    for trade in trades:
        quantity = Decimal(str(trade.quantity))
        price = prices.get(trade.id, Decimal(str(trade.price)))
        splits = factors.get(trade.symbol)
        if splits:
            factor = _factor(splits, trade.trade_date)
            if factor != 1:
                quantity *= factor
                price /= factor
        views.append(
            TradeView(
                id=trade.id,
                sleeve_id=trade.sleeve_id,
                trade_date=trade.trade_date,
                symbol=trade.symbol,
                action=trade.action,
                quantity=quantity,
                price=price,
                commission=Decimal(str(trade.commission or 0)),
                security_type=trade.security_type,
                at_market=trade.id not in deliveries,
            )
        )
    return views


def option_event(trade) -> Optional[str]:
    """``assigned`` or ``expired`` for the trade that ends an option that way."""
    notes = trade.notes or ""
    if notes.startswith(ASSIGNMENT_NOTE):
        return "assigned"
    if notes.startswith(EXPIRY_NOTE):
        return "expired"
    return None


def assignment_adjustments(
    db: Session, sleeve_ids: Iterable[str]
) -> Tuple[Dict[str, Decimal], Set[str]]:
    """How an assigned option changes the way its trades are read.

    When an option is assigned, the brokerage reports the option leaving at
    no price and, separately, shares changing hands at the strike. Read as
    they stand, the whole premium looks like a profit on the option and the
    shares look bought (or sold) at the strike. That is not what happened, nor
    how it is taxed or how the brokerage itself states the cost of the shares:
    the premium belongs to the shares.

    - A written put that is assigned: the shares cost the strike **less** the
      premium received.
    - A written call that is assigned: the shares are sold for the strike
      **plus** the premium received.
    - A bought call that is exercised: the shares cost the strike **plus** the
      premium paid. A bought put: sold for the strike **less** it.

    In every case the option itself closes at what was received or paid for
    it, so it shows no gain or loss. An option that expires, or is bought or
    sold to close, is untouched: its gain or loss is its own.

    Returns ``(prices, deliveries)``: the price each affected trade should be
    read at, by trade id, and the ids of the share trades that were deliveries
    (which did not happen at a market price). The adjustment is made only
    when the delivery is found, in full, among the account's trades, so the
    cash of the two legs together is never changed. It is worked out across
    all sleeves of the account, because the option and the shares usually sit
    in different ones.
    """
    sleeve_ids = [s for s in set(sleeve_ids) if s]
    if not sleeve_ids:
        return {}, set()
    account_ids = [
        row[0]
        for row in db.query(Sleeve.account_id)
        .filter(Sleeve.id.in_(sleeve_ids))
        .distinct()
    ]
    account_sleeves = [
        row[0] for row in db.query(Sleeve.id).filter(Sleeve.account_id.in_(account_ids))
    ]
    # An option that left at no price. The brokerage's own label says whether
    # it was assigned or expired; an unlabelled one is taken as assigned only
    # if its delivery turns up below, which an expiry never has.
    closes = [
        t
        for t in db.query(Trade).filter(
            Trade.sleeve_id.in_(account_sleeves), Trade.price == 0
        )
        if is_option_symbol(t.symbol) and option_event(t) != "expired"
    ]
    if not closes:
        return {}, set()

    symbols = {t.symbol for t in closes}
    option_trades = (
        db.query(Trade)
        .filter(Trade.sleeve_id.in_(account_sleeves), Trade.symbol.in_(symbols))
        .all()
    )
    # The order the lot matching itself uses: by day, buys before sells.
    option_trades.sort(key=lambda t: (t.trade_date, t.action != "BUY", t.id))
    days = {t.trade_date for t in closes}
    share_trades = [
        t
        for t in db.query(Trade)
        .filter(Trade.sleeve_id.in_(account_sleeves), Trade.trade_date.in_(days))
        .order_by(Trade.trade_date, Trade.id)
        if not is_option_symbol(t.symbol)
    ]
    claimed: Dict[str, Decimal] = {}  # share trade id -> shares already spoken for

    prices: Dict[str, Decimal] = {}
    deliveries: Set[str] = set()
    longs: Dict[str, List[list]] = {}
    shorts: Dict[str, List[list]] = {}
    close_ids = {t.id for t in closes}
    for trade in option_trades:
        quantity = Decimal(str(trade.quantity))
        per_contract_fee = Decimal(str(trade.commission or 0)) / quantity
        buying = trade.action == "BUY"
        # A buy closes written contracts first; a sell closes bought ones.
        unit = Decimal(str(trade.price)) + (
            per_contract_fee if buying else -per_contract_fee
        )
        closing = (shorts if buying else longs).setdefault(trade.symbol, [])
        remaining, matched, premium = quantity, Decimal(0), Decimal(0)
        while remaining > 0 and closing:
            lot = closing[0]
            take = min(remaining, lot[0])
            matched += take
            premium += take * lot[1]
            lot[0] -= take
            remaining -= take
            if lot[0] <= 0:
                closing.pop(0)
        if remaining > 0:
            (longs if buying else shorts).setdefault(trade.symbol, []).append(
                [remaining, unit]
            )
        if trade.id not in close_ids or matched != quantity or premium <= 0:
            continue

        # ``buying`` here means a written option was assigned; otherwise a
        # bought one was exercised. With the contract's right that gives the
        # direction of the share trade and which way the premium moves it.
        strike = Decimal(trade.symbol[-8:]) / 1000
        is_put = trade.symbol[-9] == "P"
        shares_bought = (buying and is_put) or (not buying and not is_put)
        raises_price = buying != is_put
        needed = quantity * OPTION_CONTRACT_SHARES
        legs: List[Tuple[Trade, Decimal]] = []
        for share in share_trades:
            if needed <= 0:
                break
            if (
                share.trade_date != trade.trade_date
                or Decimal(str(share.price)) != strike
                or (share.action == "BUY") != shares_bought
            ):
                continue
            free = Decimal(str(share.quantity)) - claimed.get(share.id, Decimal(0))
            if free <= 0:
                continue
            take = min(free, needed)
            legs.append((share, take))
            needed -= take
        if needed > 0:
            continue  # the delivery is not on file in full: leave both as reported

        prices[trade.id] = premium / quantity
        total = quantity * OPTION_CONTRACT_SHARES
        for share, take in legs:
            claimed[share.id] = claimed.get(share.id, Decimal(0)) + take
            deliveries.add(share.id)
            moved = (premium * take / total) / Decimal(str(share.quantity))
            base = prices.get(share.id, Decimal(str(share.price)))
            prices[share.id] = base + moved if raises_price else base - moved
    return prices, deliveries


def record_splits(db: Session, brokerage_account_id: str) -> int:
    """Record the splits a brokerage account's stored activity reports.

    The brokerage reports a split as the number of shares it added. The ratio
    is that addition over what was held just before, which the trades give.
    A split is a fact about the security, so one account reporting it serves
    every account. Returns how many new splits were recorded.
    """
    account = (
        db.query(BrokerageAccount)
        .filter(BrokerageAccount.id == brokerage_account_id)
        .first()
    )
    if account is None or account.account_id is None:
        return 0
    sleeve_ids = [
        row[0]
        for row in db.query(Sleeve.id).filter(Sleeve.account_id == account.account_id)
    ]
    known = {
        (a.symbol, a.effective_date)
        for a in db.query(CorporateAction).filter(
            CorporateAction.action_type == "SPLIT"
        )
    }

    recorded = 0
    rows = (
        db.query(BrokerageActivity)
        .filter(
            BrokerageActivity.brokerage_account_id == brokerage_account_id,
            BrokerageActivity.type == "SPLIT",
            BrokerageActivity.symbol.isnot(None),
            BrokerageActivity.activity_date.isnot(None),
        )
        .order_by(BrokerageActivity.activity_date)
        .all()
    )
    # Shares added and then taken back within days: the position was sold
    # before the split took effect and the brokerage undid its own entry. The
    # split still happened, on the day of the reversal.
    reversed_on: Dict[str, date] = {}
    for row in rows:
        try:
            units = Decimal(str((row.payload or {}).get("units")))
        except Exception:  # noqa: BLE001 - a malformed row is not a split
            continue
        for other in rows:
            try:
                undone = Decimal(str((other.payload or {}).get("units")))
            except Exception:  # noqa: BLE001
                continue
            if (
                other.symbol == row.symbol
                and units > 0
                and undone == -units
                and timedelta(0)
                < other.activity_date - row.activity_date
                <= _REVERSAL_WINDOW
            ):
                reversed_on[row.id] = other.activity_date

    factors = split_factors(db)
    for row in rows:
        effective = reversed_on.get(row.id, row.activity_date)
        if (row.symbol, effective) in known:
            continue
        try:
            added = Decimal(str((row.payload or {}).get("units")))
        except Exception:  # noqa: BLE001 - a malformed row is not a split
            continue
        # Shares held going into the split, counted as they were that day:
        # splits before it are applied, this one and any later one are not.
        # (A later split may already be on file from another account.)
        before = [
            split
            for split in factors.get(row.symbol, [])
            if split[0] < row.activity_date
        ]
        earlier = (
            db.query(Trade)
            .filter(
                Trade.sleeve_id.in_(sleeve_ids),
                Trade.symbol == row.symbol,
                Trade.trade_date < row.activity_date,
            )
            .all()
        )
        held = Decimal(0)
        for trade in earlier:
            quantity = Decimal(str(trade.quantity)) * _factor(before, trade.trade_date)
            held += quantity if trade.action == "BUY" else -quantity
        if held <= 0 or added <= 0:
            continue
        ratio = (held + added) / held
        db.add(
            CorporateAction(
                symbol=row.symbol,
                effective_date=effective,
                action_type="SPLIT",
                ratio=ratio,
                source="brokerage",
            )
        )
        db.flush()
        known.add((row.symbol, effective))
        factors.setdefault(row.symbol, []).append((effective, ratio))
        factors[row.symbol].sort()
        recorded += 1
    return recorded


def carry_exchange_costs(db: Session, account_id: str) -> int:
    """Price the legs of share-for-share mergers so cost carries across.

    Such a leg arrives with no price. Left at zero, the shares given up would
    look sold for nothing and the shares received would look free. Each leg is
    instead priced at the cost of what was given up: the old position closes
    with no gain or loss, and the new one starts at the same total cost.
    Returns how many trades were priced.
    """
    from app.services.portfolio_calculation import PortfolioCalculationService

    sleeve_ids = [
        row[0] for row in db.query(Sleeve.id).filter(Sleeve.account_id == account_id)
    ]
    if not sleeve_ids:
        return 0
    legs = (
        db.query(Trade)
        .filter(
            Trade.sleeve_id.in_(sleeve_ids),
            Trade.notes.like(f"{MERGER_NOTE}%"),
            Trade.price == 0,
        )
        .order_by(Trade.trade_date)
        .all()
    )
    by_day: Dict[date, List[Trade]] = {}
    for leg in legs:
        by_day.setdefault(leg.trade_date, []).append(leg)

    calc = PortfolioCalculationService(db)
    priced = 0
    for day, day_legs in by_day.items():
        given = [t for t in day_legs if t.action == "SELL"]
        received = [t for t in day_legs if t.action == "BUY"]
        if not given or not received:
            continue  # shares simply arrived (a spin-off) or left: nothing to carry
        total = Decimal(0)
        costs: Dict[str, Decimal] = {}
        for leg in given:
            held = {
                p["symbol"]: p
                for p in calc.calculate_positions(
                    [leg.sleeve_id], as_of_date=day - timedelta(days=1)
                )["open"]
            }.get(leg.symbol)
            if not held or Decimal(str(held["quantity"])) <= 0:
                continue
            unit = Decimal(str(held["cost_basis"])) / Decimal(str(held["quantity"]))
            costs[leg.id] = unit * Decimal(str(leg.quantity))
            total += costs[leg.id]
        if total <= 0:
            continue
        for leg in given:
            if leg.id in costs:
                leg.price = costs[leg.id] / Decimal(str(leg.quantity))
                priced += 1
        shares_in = sum((Decimal(str(t.quantity)) for t in received), Decimal(0))
        for leg in received:
            leg.price = total / shares_in
            priced += 1
    if priced:
        db.flush()
    return priced
