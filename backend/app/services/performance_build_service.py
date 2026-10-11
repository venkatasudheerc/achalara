"""Builds ``perf.daily_valuation`` — one row per sleeve and account per day.

Two kinds of row share the table. An *observed* row was captured from the
brokerage's own figures on the day (see ``daily_capture_service``); its values
are fact and are never rewritten here. A *reconstructed* row is worked out
from trades and price history, for the days nothing was captured: the past
before capture began, and any day the capture did not run.

A rebuild replaces every reconstructed row of an account and its sleeves, and
on observed rows refreshes only what later information can change: the money
in and out and the day's return, which firm up as late transactions arrive.

Valuing a past holding. The price history is adjusted for later splits and
dividends, so a past close is not what the security traded at. Each holding
therefore carries a scale that ties the adjusted series to reality at the
price it actually traded for; between trades the series' *movement* is what
is used. When a dividend is paid the scale is lowered by it, because the
adjusted series never fell for that dividend and the cash now sits separately.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.brokerage_connection import BrokerageAccount, BrokerageActivity
from app.models.cash_activity import CashActivity
from app.models.perf import DailyValuation
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services.cash_activity_service import CashActivityService
from app.services.cash_ledger import CashLedger
from app.services.corporate_actions import adjusted_trades
from app.services.price_history_service import PriceHistoryService

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
CENT = Decimal("0.01")


def dietz_factor(
    start_value: Decimal, end_value: Decimal, flow_in: Decimal, flow_out: Decimal
) -> Optional[Decimal]:
    """1 + the day's return, Modified Dietz with flows at mid-day.

    ``(end - start - net) / (start + net / 2)``. None when that base is not
    positive: with no capital at work there is no return to speak of.
    """
    net = flow_in - flow_out
    base = start_value + net / 2
    if base <= 0:
        return None
    return 1 + (end_value - start_value - net) / base


def last_market_day(today: Optional[date] = None) -> date:
    """The most recent weekday on or before ``today``."""
    day = today or date.today()
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


class _Series:
    """A symbol's adjusted closes, read forwards one day at a time."""

    def __init__(self, points: List[Tuple[date, Decimal]]):
        self._points = points
        self._index = -1

    def on(self, day: date) -> Optional[Decimal]:
        """The latest close on or before ``day`` (days are asked in order)."""
        while (
            self._index + 1 < len(self._points)
            and self._points[self._index + 1][0] <= day
        ):
            self._index += 1
        if self._index < 0:
            return None
        found, close = self._points[self._index]
        # A close more than a week stale is no guide to that day's value: the
        # history has stopped (delisted) or does not reach this far.
        return close if (day - found).days <= 7 else None


class _Holding:
    __slots__ = ("quantity", "scale", "last_price")

    def __init__(self):
        self.quantity = ZERO
        self.scale: Optional[Decimal] = None
        self.last_price = ZERO


class PerformanceBuildService:
    """Rebuilds the daily valuation rows of an account and its sleeves."""

    def __init__(self, db: Session):
        self.db = db
        self.prices = PriceHistoryService(db)

    def rebuild_all(self) -> Dict[str, int]:
        """Rebuild every account that has a sleeve. Returns rows written each."""
        account_ids = [row[0] for row in self.db.query(Sleeve.account_id).distinct()]
        return {account_id: self.rebuild_account(account_id) for account_id in account_ids}

    def rebuild_account(self, account_id: str, today: Optional[date] = None) -> int:
        """Rebuild one account and its sleeves. Returns the rows written."""
        sleeve_ids = [
            row[0]
            for row in self.db.query(Sleeve.id).filter(Sleeve.account_id == account_id)
        ]
        ledger = CashLedger.for_accounts(self.db, [account_id])
        trades = adjusted_trades(
            self.db,
            self.db.query(Trade)
            .filter(Trade.sleeve_id.in_(sleeve_ids))
            .order_by(Trade.trade_date, Trade.id)
            .all(),
        )

        observed = self._observed_rows(account_id, sleeve_ids)
        self._delete_reconstructed(account_id, sleeve_ids)

        starts = [t.trade_date for t in trades[:1]]
        if ledger is not None and ledger.changes:
            starts.append(min(ledger.changes))
        starts.extend(day for _, day in observed)
        if not starts:
            self.db.commit()
            return 0
        end = last_market_day(today)
        days = self.prices.market_days(min(starts), end)
        if not days:
            self.db.commit()
            return 0

        series = {
            symbol: _Series(points)
            for symbol, points in self.prices.closes({t.symbol for t in trades}).items()
        }
        dividends = self._dividends(sleeve_ids)
        income = {
            sleeve_id: dict(CashActivityService(self.db).income_flows([sleeve_id]))
            for sleeve_id in sleeve_ids
        }
        provisional_after = self._transactions_through(account_id)

        holdings: Dict[Tuple[str, str], _Holding] = {}
        previous_total: Dict[str, Decimal] = {sid: ZERO for sid in sleeve_ids}
        previous_account_total = (
            ledger.balance_on(days[0] - timedelta(days=1)) if ledger else ZERO
        )
        now = datetime.now(timezone.utc)
        new_rows: List[dict] = []
        trade_index = 0
        previous_day = days[0] - timedelta(days=3650)

        for day in days:
            flows_in = {sid: ZERO for sid in sleeve_ids}
            flows_out = {sid: ZERO for sid in sleeve_ids}

            # Trades since the previous market day, weekends included.
            while trade_index < len(trades) and trades[trade_index].trade_date <= day:
                trade = trades[trade_index]
                trade_index += 1
                holding = holdings.setdefault((trade.sleeve_id, trade.symbol), _Holding())
                gross = trade.quantity * trade.price
                if trade.action == "BUY":
                    holding.quantity += trade.quantity
                    flows_in[trade.sleeve_id] += gross + trade.commission
                else:
                    holding.quantity -= trade.quantity
                    flows_out[trade.sleeve_id] += gross - trade.commission
                holding.last_price = trade.price
                close = series[trade.symbol].on(day) if trade.symbol in series else None
                # Tie the adjusted series to the price that really traded.
                holding.scale = trade.price / close if close and trade.price > 0 else None

            for paid_on, sleeve_id, symbol, amount in dividends:
                if not previous_day < paid_on <= day:
                    continue
                holding = holdings.get((sleeve_id, symbol))
                close = series[symbol].on(day) if symbol in series else None
                if holding and holding.quantity and holding.scale and close:
                    holding.scale -= (amount / holding.quantity) / close

            securities = {sid: ZERO for sid in sleeve_ids}
            unpriced = {sid: ZERO for sid in sleeve_ids}
            for (sleeve_id, symbol), holding in holdings.items():
                if holding.quantity == 0:
                    continue
                close = series[symbol].on(day) if symbol in series else None
                if close is not None and holding.scale is not None:
                    worth = holding.quantity * close * holding.scale
                else:
                    worth = holding.quantity * holding.last_price
                    unpriced[sleeve_id] += abs(worth)
                securities[sleeve_id] += worth

            provisional = provisional_after is not None and day > provisional_after

            for sleeve_id in sleeve_ids:
                # Income leaves a sleeve like sale proceeds; a net fee is paid in.
                earned = sum(
                    (
                        amount
                        for paid_on, amount in income[sleeve_id].items()
                        if previous_day < paid_on <= day
                    ),
                    ZERO,
                )
                flow_in = flows_in[sleeve_id] + max(-earned, ZERO)
                flow_out = flows_out[sleeve_id] + max(earned, ZERO)
                previous_total[sleeve_id] = self._write(
                    new_rows,
                    observed.get((sleeve_id, day)),
                    {"sleeve_id": sleeve_id},
                    day,
                    securities[sleeve_id],
                    None,
                    flow_in,
                    flow_out,
                    unpriced[sleeve_id],
                    previous_total[sleeve_id],
                    provisional,
                    now,
                )

            if ledger is not None:
                moved = [
                    amount
                    for moved_on, amount in ledger.external.items()
                    if previous_day < moved_on <= day
                ]
                account_in = sum((a for a in moved if a > 0), ZERO)
                account_out = -sum((a for a in moved if a < 0), ZERO)
                cash = ledger.balance_on(day)
            else:
                # No cash known: the account is its sleeves, flows and all.
                account_in = sum(flows_in.values(), ZERO)
                account_out = sum(flows_out.values(), ZERO)
                for sleeve_id in sleeve_ids:
                    earned = sum(
                        (
                            amount
                            for paid_on, amount in income[sleeve_id].items()
                            if previous_day < paid_on <= day
                        ),
                        ZERO,
                    )
                    account_in += max(-earned, ZERO)
                    account_out += max(earned, ZERO)
                cash = None
            previous_account_total = self._write(
                new_rows,
                observed.get((account_id, day)),
                {"account_id": account_id},
                day,
                sum(securities.values(), ZERO),
                cash,
                account_in,
                account_out,
                sum(unpriced.values(), ZERO),
                previous_account_total,
                provisional,
                now,
            )
            previous_day = day

        if new_rows:
            self.db.bulk_insert_mappings(DailyValuation, new_rows)
        self.db.commit()
        return len(new_rows)

    # ------------------------------------------------------------------

    @staticmethod
    def _write(
        new_rows: List[dict],
        observed_row: Optional[DailyValuation],
        owner: dict,
        day: date,
        securities: Decimal,
        cash: Optional[Decimal],
        flow_in: Decimal,
        flow_out: Decimal,
        unpriced: Decimal,
        previous_total: Decimal,
        provisional: bool,
        now: datetime,
    ) -> Decimal:
        """Record one entity's day and return its closing total.

        On a captured day the captured value stands, and only the flows and
        the return they imply are refreshed.
        """
        flow_in = flow_in.quantize(CENT)
        flow_out = flow_out.quantize(CENT)
        if observed_row is not None:
            total = Decimal(str(observed_row.total_value))
            observed_row.flow_in = flow_in
            observed_row.flow_out = flow_out
            observed_row.return_factor = dietz_factor(
                previous_total, total, flow_in, flow_out
            )
            observed_row.is_provisional = provisional
            observed_row.computed_at = now
            return total

        securities = securities.quantize(CENT)
        cash = cash.quantize(CENT) if cash is not None else None
        total = securities + (cash or ZERO)
        new_rows.append(
            {
                "sleeve_id": owner.get("sleeve_id"),
                "account_id": owner.get("account_id"),
                "as_of_date": day,
                "securities_value": securities,
                "cash_value": cash,
                "total_value": total,
                "flow_in": flow_in,
                "flow_out": flow_out,
                "advisory_fees": ZERO,
                "return_factor": dietz_factor(previous_total, total, flow_in, flow_out),
                "unpriced_value": unpriced.quantize(CENT),
                "basis": "reconstructed",
                "is_provisional": provisional,
                "computed_at": now,
            }
        )
        return total

    def _observed_rows(self, account_id: str, sleeve_ids: List[str]):
        rows = (
            self.db.query(DailyValuation)
            .filter(
                DailyValuation.basis == "observed",
                (DailyValuation.account_id == account_id)
                | DailyValuation.sleeve_id.in_(sleeve_ids),
            )
            .all()
        )
        return {(row.sleeve_id or row.account_id, row.as_of_date): row for row in rows}

    def _delete_reconstructed(self, account_id: str, sleeve_ids: List[str]) -> None:
        self.db.query(DailyValuation).filter(
            DailyValuation.basis == "reconstructed",
            (DailyValuation.account_id == account_id)
            | DailyValuation.sleeve_id.in_(sleeve_ids),
        ).delete(synchronize_session=False)

    def _dividends(self, sleeve_ids: List[str]):
        """Dividends paid on a named security, oldest first."""
        return [
            (row.activity_date, row.sleeve_id, row.symbol, Decimal(str(row.amount)))
            for row in self.db.query(CashActivity)
            .filter(
                CashActivity.sleeve_id.in_(sleeve_ids),
                CashActivity.type == "DIVIDEND",
                CashActivity.symbol.isnot(None),
            )
            .order_by(CashActivity.activity_date)
        ]

    def _transactions_through(self, account_id: str) -> Optional[date]:
        """The latest day the brokerage's transactions reach for this account.

        Days after it are provisional. None for an account with no brokerage
        feed, whose trades are whatever was entered and never arrive late.
        """
        return (
            self.db.query(func.max(BrokerageActivity.activity_date))
            .join(
                BrokerageAccount,
                BrokerageAccount.id == BrokerageActivity.brokerage_account_id,
            )
            .filter(BrokerageAccount.account_id == account_id)
            .scalar()
        )


def rebuild_for_sleeves(db: Session, sleeve_ids) -> None:
    """Rebuild the daily valuation of every account these sleeves belong to.

    Called after anything that changes trades. Best-effort: a failed rebuild
    must never undo or block the change that prompted it, and the rows can
    always be rebuilt again.
    """
    sleeve_ids = [sid for sid in set(sleeve_ids) if sid]
    if not sleeve_ids:
        return
    account_ids = {
        row[0] for row in db.query(Sleeve.account_id).filter(Sleeve.id.in_(sleeve_ids))
    }
    service = PerformanceBuildService(db)
    for account_id in account_ids:
        try:
            service.rebuild_account(account_id)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("Performance rebuild failed for account %s: %s", account_id, exc)
