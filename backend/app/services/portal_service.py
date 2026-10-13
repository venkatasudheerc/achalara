"""What a client sees in their portal: every account they may view, together.

A view is always a set of sleeves (account × strategy), narrowed by the
account and strategy the client picked. Positions, trades and closed lots
are read per sleeve, so each row can name its account and strategy.
"""
from dataclasses import dataclass
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.connectors.models import is_option_symbol
from app.models.account import Account
from app.models.cash_activity import INCOME_TYPES, MARGIN_INTEREST, CashActivity
from app.models.perf import DailyHolding, DailyValuation
from app.models.position import Position
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services import benchmarks
from app.services.auth_service import AuthService, display_name, last_four
from app.services.corporate_actions import ASSIGNMENT_NOTE, EXPIRY_NOTE, option_event
from app.services.live_quotes import live_quotes
from app.services.performance_stats_service import Day, PerformanceStatsService
from app.services.portfolio_calculation import PortfolioCalculationService
from app.services.tax_lots import LONG_TERM_DAYS, MARK

BENCHMARK = benchmarks.DEFAULT
# Where each kind of income or interest cost is totalled in a gains breakdown.
_INCOME_FIELD = {
    "DIVIDEND": "dividends",
    "INTEREST": "interest",
    MARGIN_INTEREST: "margin_interest",
}
# How many of the day's largest gainers, and losers, the home page names.
MOVERS = 3
# A holding this much of the total or more is pointed out on the home page.
# The groups the activity list can be narrowed to, and the cash types in each.
ACTIVITY_GROUPS: Dict[str, Tuple[str, ...]] = {
    "all": (),
    "trades": (),
    "money": ("CONTRIBUTION", "WITHDRAWAL", "TRANSFER"),
    "income": ("DIVIDEND", "INTEREST", "OTHER"),
    "charges": (MARGIN_INTEREST, "FEE", "WITHHOLDING"),
}
_ACTIVITY_FIGURES = (
    "total",
    "trades",
    "bought",
    "sold",
    "money_in",
    "money_out",
    "income",
    "charges",
)
_CASH_KIND = {
    "CONTRIBUTION": "deposit",
    "WITHDRAWAL": "withdrawal",
    "TRANSFER": "transfer",
    "DIVIDEND": "dividend",
    "INTEREST": "interest",
    MARGIN_INTEREST: "margin_interest",
    "FEE": "fee",
    "WITHHOLDING": "withholding",
}
_CASH_LABEL = {
    "deposit": "Deposit",
    "withdrawal": "Withdrawal",
    "dividend": "Dividend",
    "interest": "Interest",
    "margin_interest": "Margin interest",
    "fee": "Fee",
    "withholding": "Tax withheld",
}
# The custodian moving money between the cash and margin sides of one account:
# two rows that cancel, and nothing the client did.
_BOOKKEEPING = re.compile(r"^\s*TRF\s+(FDS|FUNDS)\s+(TO|FRM|FR)\s+TYPE\s+\d", re.I)
# Account, trace and reference numbers in the custodian's wording.
_LONG_NUMBER = re.compile(r"[xX]*\d{5,}[-\d]*")


def _is_bookkeeping(row: CashActivity) -> bool:
    return row.type == "TRANSFER" and bool(_BOOKKEEPING.match(row.notes or ""))


def _cash_detail(notes: Optional[str]) -> Optional[str]:
    """The custodian's description of a cash row, in words a client can read.

    Its bank-transfer wording is from the bank's side ("ACH DIRECT WITHDRAWAL"
    is a deposit here), so that is replaced; long numbers are never shown.
    """
    text = " ".join((notes or "").split())
    if not text:
        return None
    upper = text.upper()
    prefix = "IRA contribution · " if "IRA CONTRIBUTION" in upper else ""
    if "ACH DIRECT" in upper:
        return f"{prefix}Bank transfer (ACH)"
    if "WIRE" in upper:
        return "Wire transfer"
    if "JRL TO" in upper:
        return "To another account at your custodian"
    if "JRL FR" in upper:
        return f"{prefix}From another account at your custodian"
    return " ".join(_LONG_NUMBER.sub("", text).split()) or None


CONCENTRATION_SHARE = 0.20
# Options expiring within this many days are pointed out on the home page.
EXPIRY_DAYS = 14
# Shares per option contract. Trades and positions count options in contracts
# and carry the price per contract, so a per-share figure divides by this.
OPTION_MULTIPLIER = 100
MAX_PERIOD_ROWS = 400
MAX_VALUE_POINTS = 400

# How a trade's security type is grouped for the portal's Type filter.
TYPE_GROUPS: Dict[str, Tuple[str, ...]] = {
    "stock": ("STOCK", "ADR"),
    "etf": ("ETF",),
    "option": ("OPTION",),
}
_KNOWN_TYPES = tuple(t for types in TYPE_GROUPS.values() for t in types)


class PortalError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class SleeveRef:
    """One sleeve in view, with what a row needs to say where it sits."""

    sleeve: Sleeve
    account: Account
    shared: bool

    @property
    def strategy_name(self) -> str:
        return self.sleeve.strategy.name


def type_group(security_type: Optional[str], symbol: str) -> str:
    for group, types in TYPE_GROUPS.items():
        if security_type in types:
            return group
    return "option" if is_option_symbol(symbol) else "other"


def _multiplier(symbol: str) -> int:
    """Shares per unit of quantity: 100 for an option contract, else 1."""
    return OPTION_MULTIPLIER if is_option_symbol(symbol) else 1


def _per_share(price, symbol: str) -> Optional[float]:
    """A stored price as it is quoted: per share, also for an option."""
    return None if price is None else float(price) / _multiplier(symbol)


def _reported(lot: Dict, days: Optional[int]) -> Dict:
    """A closed lot's gain as the brokerage reports it (see ``tax_lots``).

    ``realized_gain`` here is the gain after any loss a wash sale disallowed,
    which is the figure a brokerage's realised-gains list shows. A sleeve that
    is not matched by lots has no such reading, so what happened stands in.
    """
    if "reported_gain" in lot:
        gain, cost = float(lot["reported_gain"]), float(lot["cost"])
        return {
            "term": lot["term"],
            "cost": cost,
            "proceeds": float(lot["proceeds"]),
            "disallowed_loss": float(lot["disallowed_loss"]),
            "short_term_gain": float(lot["short_term_gain"]),
            "long_term_gain": float(lot["long_term_gain"]),
            "realized_gain": gain,
            "realized_gain_pct": gain / cost if cost > 0 else None,
            "adjustments": list(lot["adjustments"]),
        }
    gain = float(lot["realized_gain"])
    is_long = days is not None and days > LONG_TERM_DAYS
    cost = float(lot.get("matched_quantity") or 0) * float(lot.get("entry_price") or 0)
    pct = lot.get("realized_gain_pct")
    return {
        "term": "long" if is_long else "short",
        "cost": cost,
        "proceeds": cost + gain,
        "disallowed_loss": 0.0,
        "short_term_gain": 0.0 if is_long else gain,
        "long_term_gain": gain if is_long else 0.0,
        "realized_gain": gain,
        # Stored as a whole-number percentage; the portal speaks fractions.
        "realized_gain_pct": float(pct) / 100 if pct is not None else None,
        "adjustments": [],
    }


_OPTION = re.compile(r"^([A-Z.]+)\d?(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")


def option_parts(symbol: str) -> Optional[Dict]:
    """An option symbol read apart: what it is on, put or call, strike, expiry.

    The root can carry a digit after a corporate action; the shares it is on
    are the root without it.
    """
    match = _OPTION.match(symbol or "")
    if not match:
        return None
    root, yy, mm, dd, kind, strike = match.groups()
    try:
        expiry = date(2000 + int(yy), int(mm), int(dd))
    except ValueError:
        return None
    return {
        "underlying": root,
        "kind": "put" if kind == "P" else "call",
        "strike": int(strike) / 1000,
        "expiry": expiry,
    }


def _as_date(value) -> Optional[date]:
    return value.date() if isinstance(value, datetime) else value


def _matches(symbol: str, query: Optional[str]) -> bool:
    return not query or query.strip().lower() in symbol.lower()


class PortalService:
    def __init__(self, db: Session, client_id: str):
        self.db = db
        self.client_id = client_id
        self.stats = PerformanceStatsService(db)
        self.calc = PortfolioCalculationService(db)
        self.visible = AuthService(db).accounts_for_client(client_id)
        self._matched_sleeves: Dict[str, Dict] = {}

    # -- what is in view -----------------------------------------------

    def _refs(
        self, account_id: Optional[str] = None, strategy_id: Optional[str] = None
    ) -> List[SleeveRef]:
        visible = self.visible
        if account_id:
            visible = [(a, shared) for a, shared in visible if a.id == account_id]
            if not visible:
                # Not theirs to see, or not there: the same answer either way.
                raise PortalError(404, "Account not found")
        refs = []
        for account, shared in visible:
            for sleeve in sorted(account.sleeves, key=lambda s: s.strategy.name):
                if strategy_id and sleeve.strategy_id != strategy_id:
                    continue
                refs.append(SleeveRef(sleeve=sleeve, account=account, shared=shared))
        return refs

    @staticmethod
    def _account_fields(account: Account, shared: bool) -> Dict:
        return {
            "id": account.id,
            "client_id": account.client_id,
            "name": display_name(account),
            "number_last4": last_four(account),
            "shared": shared,
        }

    def accounts(self) -> List[Dict]:
        """The accounts in view and the strategies each is run as."""
        return [
            {
                **self._account_fields(account, shared),
                "sleeves": [
                    {
                        "sleeve_id": sleeve.id,
                        "strategy_id": sleeve.strategy_id,
                        "strategy_name": sleeve.strategy.name,
                    }
                    for sleeve in sorted(account.sleeves, key=lambda s: s.strategy.name)
                ],
            }
            for account, shared in self.visible
        ]

    def _symbol_types(self, sleeve_ids: Sequence[str]) -> Dict[Tuple[str, str], str]:
        """The security type last recorded for each symbol of each sleeve."""
        if not sleeve_ids:
            return {}
        rows = (
            self.db.query(Trade.sleeve_id, Trade.symbol, Trade.security_type)
            .filter(
                Trade.sleeve_id.in_(list(sleeve_ids)), Trade.security_type.isnot(None)
            )
            .order_by(Trade.trade_date)
        )
        return {(sleeve_id, symbol): kind for sleeve_id, symbol, kind in rows}

    def _row_place(self, ref: SleeveRef) -> Dict:
        return {
            "account_id": ref.account.id,
            "account_name": display_name(ref.account),
            "shared": ref.shared,
            "sleeve_id": ref.sleeve.id,
            "strategy_id": ref.sleeve.strategy_id,
            "strategy_name": ref.strategy_name,
        }

    # -- positions ------------------------------------------------------

    def _matched(self, sleeve_id: str) -> Dict:
        """A sleeve's trades matched into positions and lots, worked out once.

        Positions, realised gains and the home page each read this, and the
        matching is the costly part of all three.
        """
        if sleeve_id not in self._matched_sleeves:
            self._matched_sleeves[sleeve_id] = self.calc.calculate_positions(
                [sleeve_id]
            )
        return self._matched_sleeves[sleeve_id]

    def _recorded_holdings(self, account_id: str) -> Optional[List[DailyHolding]]:
        """What the custodian last reported the account as holding, if ever."""
        latest = (
            self.db.query(func.max(DailyHolding.as_of_date))
            .filter(DailyHolding.account_id == account_id)
            .scalar()
        )
        if latest is None:
            return None
        return (
            self.db.query(DailyHolding)
            .filter(
                DailyHolding.account_id == account_id,
                DailyHolding.as_of_date == latest,
            )
            .all()
        )

    def _stored_prices(
        self, sleeve_ids: Sequence[str]
    ) -> Dict[Tuple[str, str], Decimal]:
        return {
            (row.sleeve_id, row.symbol): row.current_price
            for row in self.db.query(Position).filter(
                Position.sleeve_id.in_(list(sleeve_ids)),
                Position.status == "OPEN",
                Position.current_price.isnot(None),
            )
        }

    def _account_positions(self, refs: Sequence[SleeveRef]) -> List[Dict]:
        """Open positions of one account's sleeves in view.

        Where the custodian's holdings have been recorded they are the list:
        quantity, price, value and cost are the custodian's; a holding it gave
        no cost for takes the average paid from the trade history. Options are not part of that record, so they
        are added from the trade history, without a price. An account with no
        recorded holdings is listed from its trades at the last stored price.
        """
        account = refs[0].account
        by_sleeve = {r.sleeve.id: r for r in refs}
        calculated: Dict[str, Dict[str, Dict]] = {
            sleeve_id: {pos["symbol"]: pos for pos in self._matched(sleeve_id)["open"]}
            for sleeve_id in by_sleeve
        }

        def row(
            ref, symbol, quantity, price, value, known: Optional[Dict], unit_cost=None
        ) -> Dict:
            multiplier = _multiplier(symbol)
            cost = None
            if unit_cost is not None:
                # The custodian's own cost for the holding.
                cost = Decimal(str(unit_cost)) * quantity
            elif known and Decimal(str(known["quantity"])) != 0:
                # The average paid per unit, applied to what is held now.
                unit = Decimal(str(known["cost_basis"])) / Decimal(
                    str(known["quantity"])
                )
                cost = unit * quantity
            gain = value - cost if value is not None and cost is not None else None
            return {
                **self._row_place(ref),
                "symbol": symbol,
                "quantity": float(quantity),
                # Per share: an option is quoted per share and held in
                # contracts of ``multiplier`` shares.
                "avg_cost": (
                    float(cost / quantity / multiplier)
                    if cost is not None and quantity
                    else None
                ),
                "multiplier": multiplier,
                "price": float(price) if price is not None else None,
                "cost_basis": float(cost) if cost is not None else None,
                "market_value": float(value) if value is not None else None,
                "unrealized_gain": float(gain) if gain is not None else None,
                "unrealized_gain_pct": float(gain / abs(cost))
                if gain is not None and cost
                else None,
                "is_short": quantity < 0,
            }

        holdings = self._recorded_holdings(account.id)
        rows: List[Dict] = []
        if holdings is None:
            prices = self._stored_prices(list(by_sleeve))
            for sleeve_id, positions in calculated.items():
                for symbol, pos in positions.items():
                    quantity = Decimal(str(pos["quantity"]))
                    price = prices.get((sleeve_id, symbol))
                    value = (
                        quantity * Decimal(str(price)) if price is not None else None
                    )
                    rows.append(
                        row(by_sleeve[sleeve_id], symbol, quantity, price, value, pos)
                    )
            return rows

        for holding in holdings:
            quantity = Decimal(str(holding.quantity or 0))
            if quantity == 0:
                continue
            # The sleeve it was recorded under, else the one whose trades hold it.
            sleeve_id = (
                holding.sleeve_id
                if holding.sleeve_id in by_sleeve
                else next(
                    (sid for sid, held in calculated.items() if holding.symbol in held),
                    None,
                )
            )
            if sleeve_id is None:
                continue  # belongs to a strategy that is filtered out
            value = (
                Decimal(str(holding.market_value))
                if holding.market_value is not None
                else None
            )
            price = value / quantity if value is not None else holding.price
            rows.append(
                row(
                    by_sleeve[sleeve_id],
                    holding.symbol,
                    quantity,
                    price,
                    value,
                    calculated[sleeve_id].get(holding.symbol),
                    holding.avg_cost,
                )
            )
        for sleeve_id, positions in calculated.items():
            for symbol, pos in positions.items():
                if is_option_symbol(symbol):
                    rows.append(
                        row(
                            by_sleeve[sleeve_id],
                            symbol,
                            Decimal(str(pos["quantity"])),
                            None,
                            None,
                            pos,
                        )
                    )
        return rows

    def positions(
        self,
        account_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        security_type: Optional[str] = None,
        query: Optional[str] = None,
        live: bool = False,
    ) -> Dict:
        """Open positions in view, with totals.

        ``live`` shows each holding at the market's current price where one
        can be had (see ``_at_live_prices``). What is held and what it cost
        are the custodian's either way.
        """
        refs = self._refs(account_id, strategy_id)
        kinds = self._symbol_types([r.sleeve.id for r in refs])
        rows: List[Dict] = []
        # What each account's options cost, whatever the filters hide: with the
        # custodian's value for them it gives their unrealised gain.
        option_costs: Dict[str, Optional[float]] = {}
        for account_refs in self._by_account(refs):
            for position in self._account_positions(account_refs):
                symbol = position["symbol"]
                group = type_group(kinds.get((position["sleeve_id"], symbol)), symbol)
                if group == "option" and position["market_value"] is None:
                    account_id, paid = position["account_id"], position["cost_basis"]
                    known = option_costs.get(account_id, 0.0)
                    option_costs[account_id] = (
                        None if paid is None or known is None else known + paid
                    )
                if security_type and group != security_type:
                    continue
                if not _matches(symbol, query):
                    continue
                rows.append({**position, "security_type": group})
        live_prices_at = self._at_live_prices(rows) if live else None
        rows.sort(key=lambda r: (r["market_value"] is None, -(r["market_value"] or 0)))

        priced = [r for r in rows if r["market_value"] is not None]
        costed = [r for r in priced if r["cost_basis"] is not None]
        gain = sum(r["unrealized_gain"] for r in costed)
        cost = sum(r["cost_basis"] for r in costed)
        value = sum(r["market_value"] for r in priced)

        # Options have no price of their own, but the custodian's account
        # total does value them. Where every option of an account is in view,
        # that combined figure is shown and counted.
        options = None
        if not (query and query.strip()):
            options = self._options_combined(rows)
        if options:
            value += options["market_value"]
            cost += options["cost_basis"]
            gain += options["unrealized_gain"]
        return {
            "as_of": self._as_of(refs),
            "live_prices_at": live_prices_at,
            "count": len(rows),
            "unpriced_count": len(rows) - len(priced),
            "total_market_value": value,
            "total_cost_basis": cost,
            "total_unrealized_gain": gain,
            "total_unrealized_gain_pct": gain / abs(cost) if cost else None,
            "options": options,
            "account_balances": self._account_balances(refs, option_costs),
            "positions": rows,
        }

    def _account_balances(
        self, refs: Sequence[SleeveRef], option_costs: Dict[str, Optional[float]]
    ) -> List[Dict]:
        """What each account in view holds beyond its priced holdings: cash,
        and the custodian's value for its options together.

        Both are the custodian's own figures from its last recorded day, so an
        account's holdings plus these is the total the custodian reports. Cash
        is negative when money is borrowed. An account with no record yet is
        left out.
        """
        balances = []
        for account_refs in self._by_account(refs):
            account = account_refs[0].account
            latest = (
                self.db.query(DailyValuation)
                .filter(
                    DailyValuation.account_id == account.id,
                    DailyValuation.sleeve_id.is_(None),
                )
                .order_by(DailyValuation.as_of_date.desc())
                .first()
            )
            if latest is None:
                continue
            holdings = self._recorded_holdings(account.id)
            options_value = None
            if holdings and holdings[0].as_of_date == latest.as_of_date:
                listed = sum(
                    (Decimal(str(h.market_value)) for h in holdings), Decimal(0)
                )
                rest = Decimal(str(latest.securities_value)) - listed
                # A few cents either way is rounding, not an option.
                options_value = float(rest) if abs(rest) >= 1 else None
            balances.append(
                {
                    "account_id": account.id,
                    "as_of": latest.as_of_date,
                    "cash_value": float(latest.cash_value)
                    if latest.cash_value is not None
                    else None,
                    "options_value": options_value,
                    # Premiums paid, less premiums received for options written.
                    "options_cost": option_costs.get(account.id)
                    if options_value is not None
                    else None,
                }
            )
        return balances

    @staticmethod
    def _at_live_prices(rows: List[Dict]) -> Optional[datetime]:
        """Reprice ``rows`` at the market's current prices, in place.

        Only the price changes, and with it the value and the gain: quantity
        and cost stay as the custodian gave them. A holding with no live quote
        (an option, an unlisted security, the source being down) keeps the
        custodian's price. Each row says which it has in ``price_source``.
        Returns when the oldest live price used was fetched, or None if none.
        """
        quotes = live_quotes(row["symbol"] for row in rows)
        oldest: Optional[datetime] = None
        for row in rows:
            row["price_source"] = "custodian" if row["price"] is not None else None
            row["day_change"] = row["day_change_pct"] = None
            quote = quotes.get(row["symbol"])
            if quote is None:
                continue
            value = float(quote.price) * row["quantity"] * row["multiplier"]
            if quote.prev_close:
                move = float(quote.price - quote.prev_close)
                row["day_change"] = move * row["quantity"] * row["multiplier"]
                row["day_change_pct"] = move / float(quote.prev_close)
            cost = row["cost_basis"]
            gain = value - cost if cost is not None else None
            row.update(
                price=float(quote.price),
                market_value=value,
                unrealized_gain=gain,
                unrealized_gain_pct=gain / abs(cost)
                if gain is not None and cost
                else None,
                price_source="live",
            )
            if oldest is None or quote.fetched_at < oldest:
                oldest = quote.fetched_at
        return oldest

    def _options_combined(self, rows: Sequence[Dict]) -> Optional[Dict]:
        """The custodian's value for the unpriced options in ``rows``, together.

        Its reported securities value less the holdings it lists is what it
        holds the options at. That is one figure per account, so it is only
        given when the rows are all of that account's options.
        """
        unpriced = [
            r
            for r in rows
            if r["market_value"] is None and r["security_type"] == "option"
        ]
        if not unpriced:
            return None
        value = Decimal(0)
        for account_id in {r["account_id"] for r in unpriced}:
            holdings = self._recorded_holdings(account_id)
            if not holdings:
                return None
            day = holdings[0].as_of_date
            account_row = (
                self.db.query(DailyValuation)
                .filter(
                    DailyValuation.account_id == account_id,
                    DailyValuation.as_of_date == day,
                )
                .first()
            )
            if account_row is None:
                return None
            listed = sum((Decimal(str(h.market_value)) for h in holdings), Decimal(0))
            value += Decimal(str(account_row.securities_value)) - listed
        if any(r["cost_basis"] is None for r in unpriced):
            return None
        cost = sum(Decimal(str(r["cost_basis"])) for r in unpriced)
        return {
            "count": len(unpriced),
            "market_value": float(value),
            "cost_basis": float(cost),
            "unrealized_gain": float(value - cost),
        }

    @staticmethod
    def _by_account(refs: Sequence[SleeveRef]) -> List[List[SleeveRef]]:
        grouped: Dict[str, List[SleeveRef]] = {}
        for ref in refs:
            grouped.setdefault(ref.account.id, []).append(ref)
        return list(grouped.values())

    # -- trades ---------------------------------------------------------

    def trades(
        self,
        start: Optional[date] = None,
        end: Optional[date] = None,
        account_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        action: Optional[str] = None,
        security_type: Optional[str] = None,
        query: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Dict:
        refs = self._refs(account_id, strategy_id)
        by_sleeve = {r.sleeve.id: r for r in refs}
        empty = {
            "total": 0,
            "skip": skip,
            "limit": limit,
            "bought": 0.0,
            "sold": 0.0,
            "net_invested": 0.0,
            "accounts": [],
            "trades": [],
        }
        if not by_sleeve:
            return empty

        filters = [Trade.sleeve_id.in_(list(by_sleeve))]
        if start:
            filters.append(Trade.trade_date >= start)
        if end:
            filters.append(Trade.trade_date <= end)
        if action:
            filters.append(Trade.action == action.upper())
        if security_type in TYPE_GROUPS:
            filters.append(Trade.security_type.in_(TYPE_GROUPS[security_type]))
        elif security_type == "other":
            filters.append(
                or_(
                    Trade.security_type.is_(None),
                    Trade.security_type.notin_(_KNOWN_TYPES),
                )
            )
        if query and query.strip():
            needle = query.strip().replace("%", r"\%").replace("_", r"\_")
            filters.append(Trade.symbol.ilike(f"%{needle}%", escape="\\"))

        amount = Trade.quantity * Trade.price
        total, bought, sold = (
            self.db.query(
                func.count(Trade.id),
                func.coalesce(
                    func.sum(case((Trade.action == "BUY", amount), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((Trade.action == "SELL", amount), else_=0)), 0
                ),
            )
            .filter(*filters)
            .one()
        )
        trades = (
            self.db.query(Trade)
            .filter(*filters)
            .order_by(Trade.trade_date.desc(), Trade.id)
            .offset(skip)
            .limit(limit)
            .all()
        )
        # The same totals for each account that has a matching trade.
        per_sleeve = {
            sleeve_id: (count, float(buys), float(sells))
            for sleeve_id, count, buys, sells in self.db.query(
                Trade.sleeve_id,
                func.count(Trade.id),
                func.coalesce(
                    func.sum(case((Trade.action == "BUY", amount), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((Trade.action == "SELL", amount), else_=0)), 0
                ),
            )
            .filter(*filters)
            .group_by(Trade.sleeve_id)
        }
        accounts = []
        for account_refs in self._by_account(refs):
            held = [
                per_sleeve[r.sleeve.id]
                for r in account_refs
                if r.sleeve.id in per_sleeve
            ]
            if not held:
                continue
            place = self._row_place(account_refs[0])
            accounts.append(
                {
                    "account_id": place["account_id"],
                    "account_name": place["account_name"],
                    "shared": place["shared"],
                    "total": sum(h[0] for h in held),
                    "bought": sum(h[1] for h in held),
                    "sold": sum(h[2] for h in held),
                }
            )
        return {
            **empty,
            "accounts": accounts,
            "total": total,
            "bought": float(bought),
            "sold": float(sold),
            "net_invested": float(bought) - float(sold),
            "trades": [
                {
                    **self._row_place(by_sleeve[t.sleeve_id]),
                    "id": t.id,
                    "trade_date": t.trade_date,
                    "symbol": t.symbol,
                    "action": t.action,
                    # How an option ended, when it was not by a trade.
                    "event": option_event(t),
                    "security_type": type_group(t.security_type, t.symbol),
                    "quantity": float(t.quantity),
                    # Per share: an option is stored per contract.
                    "price": float(t.price / _multiplier(t.symbol)),
                    "multiplier": _multiplier(t.symbol),
                    "amount": float(t.quantity * t.price),
                    "commission": float(t.commission or 0),
                }
                for t in trades
            ],
        }

    # -- activity: trades and money movements together --------------------

    def activity(
        self,
        start: Optional[date] = None,
        end: Optional[date] = None,
        account_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        show: str = "all",
        action: Optional[str] = None,
        security_type: Optional[str] = None,
        query: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Dict:
        """Everything that happened in the accounts in view, newest first.

        Trades and the cash that moved: deposits, withdrawals, transfers,
        dividends, interest and charges. ``show`` narrows it to one group. An
        action or a security type can only describe a trade, so either one
        leaves the cash rows out. Totals cover everything matched, not the page.
        """
        if show not in ACTIVITY_GROUPS:
            raise PortalError(422, f"show must be one of {', '.join(ACTIVITY_GROUPS)}")
        refs = self._refs(account_id, strategy_id)
        by_sleeve = {r.sleeve.id: r for r in refs}
        needle = (query or "").strip()
        like = needle.replace("%", r"\%").replace("_", r"\_")

        trades: List[Trade] = []
        if by_sleeve and show in ("all", "trades"):
            filters = [Trade.sleeve_id.in_(list(by_sleeve))]
            if start:
                filters.append(Trade.trade_date >= start)
            if end:
                filters.append(Trade.trade_date <= end)
            if action:
                filters.append(Trade.action == action.upper())
            if security_type in TYPE_GROUPS:
                filters.append(Trade.security_type.in_(TYPE_GROUPS[security_type]))
            elif security_type == "other":
                filters.append(
                    or_(
                        Trade.security_type.is_(None),
                        Trade.security_type.notin_(_KNOWN_TYPES),
                    )
                )
            if needle:
                filters.append(Trade.symbol.ilike(f"%{like}%", escape="\\"))
            trades = self.db.query(Trade).filter(*filters).all()

        cash: List[CashActivity] = []
        if by_sleeve and show != "trades" and not action and not security_type:
            filters = [CashActivity.sleeve_id.in_(list(by_sleeve))]
            if show != "all":
                filters.append(CashActivity.type.in_(ACTIVITY_GROUPS[show]))
            if start:
                filters.append(CashActivity.activity_date >= start)
            if end:
                filters.append(CashActivity.activity_date <= end)
            if needle:
                filters.append(CashActivity.symbol.ilike(f"%{like}%", escape="\\"))
            cash = [
                row
                for row in self.db.query(CashActivity).filter(*filters)
                if not _is_bookkeeping(row)
            ]

        totals: Dict[str, Dict[str, float]] = {}

        def tally(sleeve_id: str, field: str, amount: float) -> None:
            account = by_sleeve[sleeve_id].account.id
            figures = totals.setdefault(account, dict.fromkeys(_ACTIVITY_FIGURES, 0.0))
            figures["total"] += 1
            figures[field] += amount

        for trade in trades:
            tally(trade.sleeve_id, "trades", 1)
            tally_field = "bought" if trade.action == "BUY" else "sold"
            totals[by_sleeve[trade.sleeve_id].account.id][tally_field] += float(
                trade.quantity * trade.price
            )
        for row in cash:
            amount = float(row.amount)
            if row.type in ACTIVITY_GROUPS["money"]:
                tally(
                    row.sleeve_id,
                    "money_in" if amount > 0 else "money_out",
                    abs(amount),
                )
            elif row.type in ACTIVITY_GROUPS["income"]:
                tally(row.sleeve_id, "income", amount)
            else:
                tally(row.sleeve_id, "charges", -amount)

        accounts = []
        for account_refs in self._by_account(refs):
            figures = totals.get(account_refs[0].account.id)
            if figures is None:
                continue
            place = self._row_place(account_refs[0])
            accounts.append(
                {
                    "account_id": place["account_id"],
                    "account_name": place["account_name"],
                    "shared": place["shared"],
                    **figures,
                    "total": int(figures["total"]),
                    "trades": int(figures["trades"]),
                }
            )
        overall = {
            field: sum(a[field] for a in accounts) for field in _ACTIVITY_FIGURES
        }

        # Newest first; on one day the cash rows follow the trades.
        ordered = sorted(
            [(t.trade_date, 0, t.id, t) for t in trades]
            + [(c.activity_date, 1, c.id, c) for c in cash],
            key=lambda entry: (-entry[0].toordinal(), entry[1], entry[2]),
        )
        rows = [
            self._trade_row(item, by_sleeve)
            if kind == 0
            else self._cash_row(item, by_sleeve)
            for _, kind, _, item in ordered[skip : skip + limit]
        ]
        return {
            **overall,
            "net_invested": overall["bought"] - overall["sold"],
            "skip": skip,
            "limit": limit,
            "accounts": accounts,
            "rows": rows,
        }

    def _trade_row(self, t: Trade, by_sleeve: Dict[str, SleeveRef]) -> Dict:
        event = option_event(t)
        return {
            **self._row_place(by_sleeve[t.sleeve_id]),
            "id": t.id,
            "date": t.trade_date,
            "kind": "trade",
            "label": event.capitalize()
            if event
            else ("Bought" if t.action == "BUY" else "Sold"),
            "detail": None,
            "symbol": t.symbol,
            "action": t.action,
            # How an option ended, when it was not by a trade.
            "event": event,
            "security_type": type_group(t.security_type, t.symbol),
            "quantity": float(t.quantity),
            # Per share: an option is stored per contract.
            "price": float(t.price / _multiplier(t.symbol)),
            "multiplier": _multiplier(t.symbol),
            "amount": float(t.quantity * t.price),
        }

    def _cash_row(self, c: CashActivity, by_sleeve: Dict[str, SleeveRef]) -> Dict:
        amount = float(c.amount)
        kind = _CASH_KIND[c.type] if c.type in _CASH_KIND else "other"
        label = _CASH_LABEL.get(kind, "Other")
        if kind == "transfer":
            label = "Transfer in" if amount > 0 else "Transfer out"
        return {
            **self._row_place(by_sleeve[c.sleeve_id]),
            "id": c.id,
            "date": c.activity_date,
            "kind": kind,
            "label": label,
            "detail": _cash_detail(c.notes),
            "symbol": c.symbol,
            "action": None,
            "event": None,
            "security_type": None,
            "quantity": None,
            "price": None,
            "multiplier": None,
            # Signed: money arriving in the account is positive.
            "amount": amount,
        }

    # -- realised gains -------------------------------------------------

    def _closed_lots(self, refs: Sequence[SleeveRef]) -> List[Dict]:
        kinds = self._symbol_types([r.sleeve.id for r in refs])
        # Options that ended by assignment or expiry, by sleeve, symbol and day.
        endings = {
            (t.sleeve_id, t.symbol, t.trade_date): option_event(t)
            for t in self.db.query(Trade).filter(
                Trade.sleeve_id.in_([r.sleeve.id for r in refs] or [""]),
                Trade.price == 0,
                or_(
                    Trade.notes.like(f"{ASSIGNMENT_NOTE}%"),
                    Trade.notes.like(f"{EXPIRY_NOTE}%"),
                ),
            )
        }
        lots: List[Dict] = []
        for ref in refs:
            positions = self._matched(ref.sleeve.id)
            for lot in positions["closed"] + positions.get("marked", []):
                opened, closed = _as_date(lot.get("opened_at")), _as_date(
                    lot["closed_at"]
                )
                days = (closed - opened).days if opened and closed else None
                symbol = lot["symbol"]
                figures = _reported(lot, days)
                marked = MARK in figures["adjustments"]
                lots.append(
                    {
                        **self._row_place(ref),
                        "symbol": symbol,
                        "security_type": type_group(
                            kinds.get((ref.sleeve.id, symbol)), symbol
                        ),
                        "event": "marked"
                        if marked
                        else endings.get((ref.sleeve.id, symbol, closed)),
                        "opened_at": opened,
                        "closed_at": closed,
                        "days_held": days,
                        "quantity": lot.get("matched_quantity"),
                        "multiplier": _multiplier(symbol),
                        "entry_price": _per_share(lot.get("entry_price"), symbol),
                        "exit_price": _per_share(lot.get("exit_price"), symbol),
                        **figures,
                    }
                )
        return lots

    def realized(
        self,
        start: Optional[date] = None,
        end: Optional[date] = None,
        account_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        term: Optional[str] = None,
        security_type: Optional[str] = None,
        result: Optional[str] = None,
        query: Optional[str] = None,
        grain: str = "month",
    ) -> Dict:
        """Closed lots in view with their totals, the same gains by month or
        quarter and by account and strategy, and the dividends and interest
        received over the same dates.

        Income is listed beside capital gains and never added into them: it is
        taxed differently, and a custodian's realised-gains list leaves it out.
        It follows the dates, account and strategy only, since a term, a
        result or a symbol has no meaning for a dividend.
        """
        if start and end and start > end:
            raise PortalError(400, "The start date must be before the end date")
        refs = self._refs(account_id, strategy_id)
        income = self._income_rows(refs, start, end)
        lots = [
            lot
            for lot in self._closed_lots(refs)
            if (start is None or lot["closed_at"] >= start)
            and (end is None or lot["closed_at"] <= end)
            # An index option's gain is part short-term and part long-term.
            and (not term or lot["term"] in (term, "mixed"))
            and (not security_type or lot["security_type"] == security_type)
            and (not result or (result == "gain") == (lot["realized_gain"] >= 0))
            and _matches(lot["symbol"], query)
        ]
        lots.sort(key=lambda lot: (lot["closed_at"], lot["symbol"]), reverse=True)

        def total(rows, field: str = "realized_gain") -> float:
            return sum(row[field] for row in rows)

        return {
            "count": len(lots),
            "net_realized": total(lots),
            "short_term": total(lots, "short_term_gain"),
            "long_term": total(lots, "long_term_gain"),
            "gains": total([lot for lot in lots if lot["realized_gain"] >= 0]),
            "losses": total([lot for lot in lots if lot["realized_gain"] < 0]),
            "cost": total(lots, "cost"),
            "proceeds": total(lots, "proceeds"),
            "disallowed_loss": total(lots, "disallowed_loss"),
            "dividends": sum(a for _, _, kind, a in income if kind == "DIVIDEND"),
            "interest": sum(a for _, _, kind, a in income if kind == "INTEREST"),
            "margin_interest": sum(
                a for _, _, kind, a in income if kind == MARGIN_INTEREST
            ),
            "years": sorted({lot["closed_at"].year for lot in lots}, reverse=True),
            "periods": self._gain_periods(lots, income, grain),
            "accounts": self._gain_groups(refs, lots, income),
            "positions": lots,
        }

    def _income_rows(
        self, refs: Sequence[SleeveRef], start: Optional[date], end: Optional[date]
    ) -> List[Tuple[str, date, str, float]]:
        """Dividends and interest received and margin interest paid (negative),
        as (sleeve, day, kind, amount)."""
        if not refs:
            return []
        rows = self.db.query(
            CashActivity.sleeve_id,
            CashActivity.activity_date,
            CashActivity.type,
            CashActivity.amount,
        ).filter(
            CashActivity.sleeve_id.in_([r.sleeve.id for r in refs]),
            CashActivity.type.in_(("DIVIDEND", "INTEREST", MARGIN_INTEREST)),
        )
        if start:
            rows = rows.filter(CashActivity.activity_date >= start)
        if end:
            rows = rows.filter(CashActivity.activity_date <= end)
        return [(s, d, kind, float(a)) for s, d, kind, a in rows]

    @staticmethod
    def _gain_figures() -> Dict:
        return {
            "count": 0,
            "short_term": 0.0,
            "long_term": 0.0,
            "realized": 0.0,
            "disallowed_loss": 0.0,
            "dividends": 0.0,
            "interest": 0.0,
            "margin_interest": 0.0,
        }

    @staticmethod
    def _add_lot(figures: Dict, lot: Dict) -> None:
        figures["count"] += 1
        figures["short_term"] += lot["short_term_gain"]
        figures["long_term"] += lot["long_term_gain"]
        figures["realized"] += lot["realized_gain"]
        figures["disallowed_loss"] += lot["disallowed_loss"]

    @staticmethod
    def _add_income(figures: Dict, kind: str, amount: float) -> None:
        figures[_INCOME_FIELD[kind]] += amount

    def _gain_periods(self, lots: Sequence[Dict], income, grain: str) -> List[Dict]:
        """Gains and income by month or quarter, newest first; a period with
        neither is left out."""
        months = 3 if grain == "quarter" else 1

        def key(day: date) -> Tuple[int, int]:
            return day.year, (day.month - 1) // months

        buckets: Dict[Tuple[int, int], Dict] = {}
        for lot in lots:
            self._add_lot(
                buckets.setdefault(key(lot["closed_at"]), self._gain_figures()), lot
            )
        for _, day, kind, amount in income:
            self._add_income(
                buckets.setdefault(key(day), self._gain_figures()), kind, amount
            )
        periods = []
        for (year, index), figures in sorted(buckets.items(), reverse=True):
            first = date(year, index * months + 1, 1)
            following = index * months + months + 1
            last = (
                date(year + 1, 1, 1) if following > 12 else date(year, following, 1)
            ) - timedelta(days=1)
            periods.append({"period_start": first, "period_end": last, **figures})
        return periods

    def _gain_groups(self, refs: Sequence[SleeveRef], lots, income) -> List[Dict]:
        """The same figures by account, and by strategy within each account.
        Accounts and strategies with nothing in the period are left out."""
        by_sleeve: Dict[str, Dict] = {}
        for lot in lots:
            self._add_lot(
                by_sleeve.setdefault(lot["sleeve_id"], self._gain_figures()), lot
            )
        for sleeve_id, _, kind, amount in income:
            self._add_income(
                by_sleeve.setdefault(sleeve_id, self._gain_figures()), kind, amount
            )
        groups = []
        for account_refs in self._by_account(refs):
            sleeves = [
                {
                    "sleeve_id": r.sleeve.id,
                    "strategy_id": r.sleeve.strategy_id,
                    "strategy_name": r.strategy_name,
                    **by_sleeve[r.sleeve.id],
                }
                for r in account_refs
                if r.sleeve.id in by_sleeve
            ]
            if not sleeves:
                continue
            whole = self._gain_figures()
            for sleeve in sleeves:
                for field in whole:
                    whole[field] += sleeve[field]
            place = self._row_place(account_refs[0])
            groups.append(
                {
                    "account_id": place["account_id"],
                    "account_name": place["account_name"],
                    "shared": place["shared"],
                    **whole,
                    "sleeves": sorted(sleeves, key=lambda s: s["strategy_name"]),
                }
            )
        return groups

    # -- performance ----------------------------------------------------

    def _series(
        self, refs: Sequence[SleeveRef], whole_accounts: bool
    ) -> Tuple[List[Day], bool]:
        """The daily series for the view and whether it carries cash.

        Whole accounts are read from their own rows, which include cash. An
        account with no daily record yet adds nothing; with none recorded at
        all, and for a single strategy, the sleeves' rows are read instead.
        """
        if whole_accounts:
            recorded = [
                account_id
                for account_id in dict.fromkeys(r.account.id for r in refs)
                if self.stats.has_rows(account_ids=[account_id])
            ]
            if recorded:
                return self.stats.daily(account_ids=recorded), True
        sleeve_ids = [r.sleeve.id for r in refs]
        return (self.stats.daily(sleeve_ids=sleeve_ids) if sleeve_ids else []), False

    def _as_of(self, refs: Sequence[SleeveRef]) -> Optional[date]:
        series, _ = self._series(refs, whole_accounts=True)
        return series[-1].date if series else None

    def performance(
        self,
        account_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
        grain: str = "month",
        benchmark: Optional[str] = None,
    ) -> Dict:
        chosen = benchmarks.find(benchmark or BENCHMARK)
        if chosen is None:
            raise PortalError(422, "That benchmark is not one of those offered")
        compared = chosen["code"]
        if start and end and start > end:
            raise PortalError(400, "The start date must be before the end date")
        refs = self._refs(account_id, strategy_id)
        series, includes_cash = self._series(refs, whole_accounts=strategy_id is None)
        # The record starts when there is first something to measure.
        while series and series[0].total == 0 and series[0].flow_in == 0:
            series = series[1:]
        if not series:
            return {
                "first_date": None,
                "as_of": None,
                "includes_cash": includes_cash,
                "benchmark": compared,
                "benchmarks": benchmarks.choices(),
                "summary": None,
                "series": [],
                "months": [],
                "years": [],
                "periods": [],
            }

        summary = self.stats.window_summary(series, start, end, compared)
        months = self.stats.periods(series, "month")
        if summary:
            if not includes_cash:
                # Deposits are made to an account, not to a strategy within it.
                summary["mwr_pct"] = None
            in_window = [
                m
                for m in months
                if m["twr_pct"] is not None
                and m["period_end"] >= summary["start"]
                and m["period_start"] <= summary["end"]
            ]
            best = max(in_window, key=lambda m: m["twr_pct"], default=None)
            worst = min(in_window, key=lambda m: m["twr_pct"], default=None)
            summary.update(
                best_month=self._month(best),
                worst_month=self._month(worst),
                months_up=sum(1 for m in in_window if m["twr_pct"] >= 0),
                months_total=len(in_window),
            )

        chart = self.stats.cumulative_series(series, start, end, compared)
        if not includes_cash:
            for point in chart:
                point["mwr"] = None
        periods = self.stats.periods(series, grain, start, end, compared)
        periods.reverse()
        return {
            "first_date": series[0].date,
            "as_of": series[-1].date,
            "includes_cash": includes_cash,
            "benchmark": compared,
            "benchmarks": benchmarks.choices(),
            "summary": summary,
            "series": chart,
            "months": [
                {
                    "year": m["period_end"].year,
                    "month": m["period_end"].month,
                    "twr_pct": m["twr_pct"],
                    "is_provisional": m["is_provisional"],
                }
                for m in months
            ],
            "years": [
                {
                    "year": y["period_end"].year,
                    "twr_pct": y["twr_pct"],
                    "is_provisional": y["is_provisional"],
                }
                for y in self.stats.periods(series, "year")
            ],
            "periods": periods[:MAX_PERIOD_ROWS],
        }

    @staticmethod
    def _month(row: Optional[Dict]) -> Optional[Dict]:
        if row is None:
            return None
        return {
            "year": row["period_end"].year,
            "month": row["period_end"].month,
            "twr_pct": row["twr_pct"],
        }

    # -- home -----------------------------------------------------------

    def _year_to_date(self, series: Sequence[Day]) -> Dict:
        if not series:
            return {"value": None, "cash": None, "twr_pct": None, "gain": None}
        last = series[-1]
        summary = self.stats.window_summary(series, date(last.date.year, 1, 1)) or {}
        return {
            "value": float(last.total),
            "cash": float(last.cash) if last.cash is not None else None,
            "twr_pct": summary.get("twr_pct"),
            "gain": summary.get("gain"),
        }

    def overview(self, account_id: Optional[str] = None) -> Dict:
        refs = self._refs(account_id)
        visible = [
            (a, s) for a, s in self.visible if not account_id or a.id == account_id
        ]
        series, includes_cash = self._series(refs, whole_accounts=True)
        as_of = series[-1].date if series else None
        year = (as_of or date.today()).year

        accounts = []
        for account, shared in visible:
            own = [r for r in refs if r.account.id == account.id]
            account_series, has_cash = self._series(own, whole_accounts=True)
            figures = self._year_to_date(account_series)
            accounts.append(
                {
                    **self._account_fields(account, shared),
                    **figures,
                    "cash": figures["cash"] if has_cash else None,
                    "sleeves": [
                        {
                            "sleeve_id": r.sleeve.id,
                            "strategy_id": r.sleeve.strategy_id,
                            "strategy_name": r.strategy_name,
                            **{
                                k: v
                                for k, v in self._year_to_date(
                                    self.stats.daily(sleeve_ids=[r.sleeve.id])
                                ).items()
                                if k != "cash"
                            },
                        }
                        for r in own
                    ],
                }
            )

        lots = self._closed_lots(refs)
        realized = sum(
            lot["realized_gain"] for lot in lots if lot["closed_at"].year == year
        )
        total = self._year_to_date(series)
        step = max(1, -(-len(series) // MAX_VALUE_POINTS))
        return {
            "as_of": as_of,
            "includes_cash": includes_cash,
            "total_value": total["value"],
            "cash_value": total["cash"] if includes_cash else None,
            "ytd_twr_pct": total["twr_pct"],
            "ytd_gain": total["gain"],
            "ytd_realized": realized,
            "is_provisional": bool(series)
            and any(d.provisional for d in series if d.date.year == year),
            "accounts": accounts,
            "timeseries": [
                {"date": d.date, "value": float(d.total)}
                for i, d in enumerate(series)
                if i % step == 0 or i == len(series) - 1
            ],
            "recent": self._recent(refs),
        }

    def home(self, account_id: Optional[str] = None) -> Dict:
        """Everything the home page shows, for all accounts in view or one.

        Value and the day's change are at the market's current prices; the
        year's return, cash and deposits come from the custodian's daily
        record, so they run to its last day, not to this minute.
        """
        refs = self._refs(account_id)
        today = date.today()
        year_start = date(today.year, 1, 1)
        positions = self.positions(account_id=account_id, live=True)
        rows = positions["positions"]
        series, includes_cash = self._series(refs, whole_accounts=True)
        summary = (
            self.stats.window_summary(series, year_start, None, BENCHMARK)
            if series
            else None
        ) or {}
        cash = summary.get("cash_value") if includes_cash else None
        whole = (self.stats.window_summary(series) if series else None) or {}
        total = positions["total_market_value"] + (cash or 0)
        moved = [r["day_change"] for r in rows if r.get("day_change") is not None]
        day_change = sum(moved) if moved else None
        before = total - (day_change or 0)

        by_type: Dict[str, float] = {}
        for row in rows:
            if row["market_value"] is not None:
                by_type[row["security_type"]] = (
                    by_type.get(row["security_type"], 0) + row["market_value"]
                )
        if positions["options"]:
            by_type["option"] = (
                by_type.get("option", 0) + positions["options"]["market_value"]
            )
        if cash is not None:
            by_type["cash"] = cash

        held: Dict[str, Dict] = {}
        for row in rows:
            if row["market_value"] is None or row["security_type"] == "option":
                continue
            entry = held.setdefault(
                row["symbol"], {"symbol": row["symbol"], "value": 0.0, "moved": None}
            )
            entry["value"] += row["market_value"]
            if row.get("day_change") is not None:
                entry["moved"] = (entry["moved"] or 0) + row["day_change"]
        holdings = sorted(held.values(), key=lambda h: -h["value"])
        for entry in holdings:
            moved_today = entry.pop("moved")
            entry["day_change"] = moved_today
            was = entry["value"] - (moved_today or 0)
            entry["day_change_pct"] = (
                moved_today / was if moved_today is not None and was else None
            )
            entry["share"] = entry["value"] / total if total else None

        realized = self.realized(start=year_start, account_id=account_id)
        return {
            "as_of": positions["as_of"],
            "live_prices_at": positions["live_prices_at"],
            "record_through": series[-1].date if series else None,
            "is_provisional": bool(series)
            and any(d.provisional for d in series if d.date >= year_start),
            "total_value": total,
            "day_change": day_change,
            "day_change_pct": day_change / before
            if day_change is not None and before
            else None,
            "ytd_twr_pct": summary.get("twr_pct"),
            "benchmark": BENCHMARK,
            "benchmark_ytd_pct": summary.get("benchmark_return_pct"),
            "excess_ytd_pct": summary.get("excess_return_pct"),
            "first_date": whole.get("start"),
            "since_start_twr_pct": whole.get("twr_pct"),
            "max_drawdown_pct": self.stats.deepest_fall(series),
            "allocation": [
                {
                    "kind": kind,
                    "value": value,
                    "share": value / total if total else None,
                }
                for kind, value in sorted(by_type.items(), key=lambda kv: -kv[1])
            ],
            "cash_value": cash,
            "income_ytd": self._income(refs, year_start),
            "realized_ytd": realized["net_realized"],
            "realized_short_ytd": realized["short_term"],
            "realized_long_ytd": realized["long_term"],
            "added_ytd": summary.get("net_flow"),
            "holdings_count": positions["count"],
            "top_holdings": holdings[:5],
            "movers_up": sorted(
                (h for h in holdings if (h["day_change"] or 0) > 0),
                key=lambda h: -h["day_change"],
            )[:MOVERS],
            "movers_down": sorted(
                (h for h in holdings if (h["day_change"] or 0) < 0),
                key=lambda h: h["day_change"],
            )[:MOVERS],
            "expiring_options": self._expiring_options(rows, today),
            "carried_losses": self._carried_losses(refs),
            "turning_long_term": self._turning_long_term(refs, today),
            "concentrated": [
                h for h in holdings if h["share"] and h["share"] >= CONCENTRATION_SHARE
            ],
        }

    def _income(self, refs: Sequence[SleeveRef], since: date) -> float:
        """Dividends and interest received since ``since``."""
        if not refs:
            return 0.0
        total = (
            self.db.query(func.sum(CashActivity.amount))
            .filter(
                CashActivity.sleeve_id.in_([r.sleeve.id for r in refs]),
                CashActivity.type.in_(("DIVIDEND", "INTEREST")),
                CashActivity.activity_date >= since,
            )
            .scalar()
        )
        return float(total or 0)

    @staticmethod
    def _expiring_options(rows: Sequence[Dict], today: date) -> List[Dict]:
        """Open options that expire within two weeks, nearest first, with how
        far the shares are from the strike where there is a live price."""
        soon = []
        for row in rows:
            parts = option_parts(row["symbol"])
            if parts is None or not 0 <= (parts["expiry"] - today).days <= EXPIRY_DAYS:
                continue
            soon.append({**parts, "row": row})
        quotes = live_quotes(p["underlying"] for p in soon)
        expiring = []
        for parts in sorted(soon, key=lambda p: (p["expiry"], p["underlying"])):
            row, quote = parts.pop("row"), quotes.get(parts["underlying"])
            price = float(quote.price) if quote else None
            expiring.append(
                {
                    **parts,
                    "symbol": row["symbol"],
                    "account_name": row["account_name"],
                    "contracts": abs(row["quantity"]),
                    "written": row["quantity"] < 0,
                    "days": (parts["expiry"] - today).days,
                    "underlying_price": price,
                    # Positive: the shares are above the strike.
                    "above_strike_pct": price / parts["strike"] - 1
                    if price and parts["strike"]
                    else None,
                }
            )
        return expiring

    def _carried_losses(self, refs: Sequence[SleeveRef]) -> float:
        """Wash-sale losses sitting in the cost of shares still held."""
        carried = Decimal(0)
        for ref in refs:
            for pos in self._matched(ref.sleeve.id)["open"]:
                if pos["quantity"] > 0 and "tax_cost" in pos:
                    carried += Decimal(str(pos["tax_cost"])) - Decimal(
                        str(pos["cost_basis"])
                    )
        return float(max(carried, Decimal(0)))

    def _turning_long_term(self, refs: Sequence[SleeveRef], today: date) -> List[Dict]:
        """Holdings with shares that pass one year held before the year ends."""
        year_end = date(today.year, 12, 31)
        first: Dict[str, date] = {}
        for ref in refs:
            for symbol, lots in self._matched(ref.sleeve.id).get("lots", {}).items():
                if is_option_symbol(symbol):
                    continue
                for lot in lots:
                    turns = lot["held_from"] + timedelta(days=LONG_TERM_DAYS + 1)
                    if today < turns <= year_end and (
                        symbol not in first or turns < first[symbol]
                    ):
                        first[symbol] = turns
        return [
            {"symbol": symbol, "date": turns}
            for symbol, turns in sorted(first.items(), key=lambda kv: (kv[1], kv[0]))
        ]

    def _recent(self, refs: Sequence[SleeveRef], limit: int = 6) -> List[Dict]:
        by_sleeve = {r.sleeve.id: r for r in refs}
        if not by_sleeve:
            return []
        trades = (
            self.db.query(Trade)
            .filter(Trade.sleeve_id.in_(list(by_sleeve)))
            .order_by(Trade.trade_date.desc(), Trade.id)
            .limit(limit)
        )
        cash = (
            self.db.query(CashActivity)
            .filter(
                CashActivity.sleeve_id.in_(list(by_sleeve)),
                # Dividends, interest and fees; not sweeps between cash and funds.
                CashActivity.type.in_(INCOME_TYPES),
            )
            .order_by(CashActivity.activity_date.desc(), CashActivity.id)
            .limit(limit)
        )
        events = [
            {
                "date": t.trade_date,
                "kind": t.action,
                "symbol": t.symbol,
                "quantity": float(t.quantity),
                "amount": float(t.quantity * t.price),
                "account_name": display_name(by_sleeve[t.sleeve_id].account),
            }
            for t in trades
        ] + [
            {
                "date": c.activity_date,
                "kind": c.type,
                "symbol": c.symbol,
                "quantity": None,
                "amount": float(c.amount),
                "account_name": display_name(by_sleeve[c.sleeve_id].account),
            }
            for c in cash
        ]
        events.sort(key=lambda e: e["date"], reverse=True)
        return events[:limit]
