"""Daily capture — recording what the brokerage reports, on the day.

Each market day, for every linked account, this stores the holdings, cash and
account total the brokerage reports. Those are the day's facts: nothing has to
be inferred from trades, price history or the timing of a transaction feed.
What is captured is never rewritten; what cannot be captured on the day (a day
the job did not run) can only be reconstructed afterwards, less surely.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from app.models.perf import DailyHolding, DailyPrice, DailyValuation
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services.connection_service import ConnectionService
from app.services.performance_build_service import (
    CENT,
    ZERO,
    PerformanceBuildService,
    last_market_day,
)

logger = logging.getLogger(__name__)


class DailyCaptureService:
    """Captures the brokerage's figures for the day into the perf schema."""

    def __init__(self, db: Session, connections: Optional[ConnectionService] = None):
        self.db = db
        self.connections = connections or ConnectionService(db)

    def capture_all(self, as_of: Optional[date] = None) -> Dict[str, str]:
        """Capture every mapped account on an active connection.

        One account failing does not stop the rest.
        """
        accounts = (
            self.db.query(BrokerageAccount)
            .join(BrokerageConnection)
            .filter(
                BrokerageAccount.status == "mapped",
                BrokerageConnection.status == "active",
            )
            .all()
        )
        outcomes: Dict[str, str] = {}
        for account_id in [a.id for a in accounts]:
            try:
                self.capture(account_id, as_of)
                outcomes[account_id] = "captured"
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                logger.error("Daily capture failed for account %s: %s", account_id, exc)
                outcomes[account_id] = "failed"
        return outcomes

    def needs_capture(self, today: Optional[date] = None) -> bool:
        """Whether any mapped account lacks an observed row for the latest market day."""
        day = last_market_day(today)
        mapped = [
            row[0]
            for row in self.db.query(BrokerageAccount.account_id)
            .join(BrokerageConnection)
            .filter(
                BrokerageAccount.status == "mapped",
                BrokerageConnection.status == "active",
            )
        ]
        if not mapped:
            return False
        captured = {
            row[0]
            for row in self.db.query(DailyValuation.account_id).filter(
                DailyValuation.account_id.in_(mapped),
                DailyValuation.as_of_date == day,
                DailyValuation.basis == "observed",
            )
        }
        return any(account_id not in captured for account_id in mapped)

    def capture(self, brokerage_account_id: str, as_of: Optional[date] = None) -> Dict:
        """Capture one account's holdings, cash and total for the day.

        The figures are stored against the latest market day: read at the
        weekend, they are Friday's close. Capturing the same day again replaces
        that day's capture, so a later read supersedes an earlier one.
        """
        ba = self.connections.get_brokerage_account(brokerage_account_id)
        if ba.status != "mapped" or not ba.default_sleeve_id or not ba.account_id:
            raise ValueError("Map the account to a sleeve before capturing it")
        day = as_of or last_market_day()
        now = datetime.now(timezone.utc)
        user_id = ba.connection.external_user_id

        holdings = self.connections.connector.fetch_positions(
            user_id, ba.external_account_ref
        )
        self.connections._refresh_cash_balance(ba)
        remote = self.connections._remote_account(user_id, ba.external_account_ref)
        reported_total = remote.total_value if remote is not None else None
        cash = Decimal(str(ba.cash_balance)) if ba.cash_balance is not None else None

        sleeve_ids = [
            row[0]
            for row in self.db.query(Sleeve.id).filter(Sleeve.account_id == ba.account_id)
        ]
        placed = self._placements(sleeve_ids)
        routes = ba.sleeve_routes or {}

        # --- holdings, and the prices they came with ---------------------
        self.db.query(DailyHolding).filter(
            DailyHolding.account_id == ba.account_id, DailyHolding.as_of_date == day
        ).delete(synchronize_session=False)
        by_sleeve: Dict[str, Decimal] = {sid: ZERO for sid in sleeve_ids}
        merged: Dict[str, dict] = {}
        for holding in holdings:
            price = holding.market_price
            value = holding.quantity * price if price is not None else ZERO
            entry = merged.setdefault(
                holding.symbol,
                {
                    "quantity": ZERO,
                    "value": ZERO,
                    "price": price,
                    "type": holding.security_type,
                },
            )
            entry["quantity"] += holding.quantity
            entry["value"] += value
        holdings_value = ZERO
        for symbol, entry in merged.items():
            sleeve_id = placed.get(symbol) or routes.get(
                entry["type"] or "", ba.default_sleeve_id
            )
            value = entry["value"].quantize(CENT)
            self.db.add(
                DailyHolding(
                    account_id=ba.account_id,
                    sleeve_id=sleeve_id,
                    as_of_date=day,
                    symbol=symbol,
                    security_type=entry["type"],
                    quantity=entry["quantity"],
                    price=entry["price"],
                    market_value=value,
                    captured_at=now,
                )
            )
            by_sleeve[sleeve_id] = by_sleeve.get(sleeve_id, ZERO) + value
            holdings_value += value
            if entry["price"] is not None:
                self._store_price(symbol, day, entry["price"], now)

        # --- the account, as the brokerage totals it ----------------------
        if reported_total is None:
            reported_total = holdings_value + (cash or ZERO)
        reported_total = Decimal(str(reported_total)).quantize(CENT)
        securities = reported_total - (cash or ZERO)

        # What the total holds beyond the listed holdings and the cash is the
        # options the holdings feed leaves out, at the brokerage's own value.
        beyond = securities - holdings_value
        unpriced: Dict[str, Decimal] = {sid: ZERO for sid in by_sleeve}
        if beyond != 0:
            options_sleeve = routes.get("OPTION", ba.default_sleeve_id)
            by_sleeve[options_sleeve] = by_sleeve.get(options_sleeve, ZERO) + beyond
            unpriced[options_sleeve] = unpriced.get(options_sleeve, ZERO) + abs(beyond)

        self._store_valuation(
            {"account_id": ba.account_id}, day, securities, cash, reported_total, abs(beyond), now
        )
        for sleeve_id in sleeve_ids:
            value = by_sleeve.get(sleeve_id, ZERO)
            self._store_valuation(
                {"sleeve_id": sleeve_id}, day, value, None, value,
                unpriced.get(sleeve_id, ZERO), now,
            )
        self.db.commit()

        # Brokerage figures are in hand, so refresh the comparison with our
        # trades from the same read, then work the day's flows and return in.
        try:
            self.connections.reconcile(ba.id, holdings=holdings)
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.warning("Reconciliation failed for account %s: %s", ba.id, exc)
        PerformanceBuildService(self.db).rebuild_account(ba.account_id)

        return {
            "as_of_date": day,
            "holdings": len(merged),
            "holdings_value": float(holdings_value),
            "cash_value": float(cash) if cash is not None else None,
            "total_value": float(reported_total),
        }

    # ------------------------------------------------------------------

    def _placements(self, sleeve_ids: List[str]) -> Dict[str, str]:
        """The sleeve of this account that already holds each symbol."""
        placed: Dict[str, str] = {}
        for symbol, sleeve_id in (
            self.db.query(Trade.symbol, Trade.sleeve_id)
            .filter(Trade.sleeve_id.in_(sleeve_ids))
            .distinct()
        ):
            placed.setdefault(symbol, sleeve_id)
        return placed

    def _store_price(self, symbol: str, day: date, price: Decimal, now: datetime) -> None:
        row = (
            self.db.query(DailyPrice)
            .filter(
                DailyPrice.symbol == symbol,
                DailyPrice.price_date == day,
                DailyPrice.source == "brokerage",
            )
            .first()
        )
        if row is None:
            row = DailyPrice(symbol=symbol, price_date=day, source="brokerage")
            self.db.add(row)
        row.close = price
        row.fetched_at = now

    def _store_valuation(
        self, owner: dict, day: date, securities, cash, total, unpriced, now
    ) -> None:
        query = self.db.query(DailyValuation).filter(DailyValuation.as_of_date == day)
        if "account_id" in owner:
            query = query.filter(DailyValuation.account_id == owner["account_id"])
        else:
            query = query.filter(DailyValuation.sleeve_id == owner["sleeve_id"])
        row = query.first()
        if row is None:
            row = DailyValuation(as_of_date=day, **owner)
            self.db.add(row)
        row.securities_value = Decimal(str(securities)).quantize(CENT)
        row.cash_value = cash.quantize(CENT) if cash is not None else None
        row.total_value = Decimal(str(total)).quantize(CENT)
        row.unpriced_value = Decimal(str(unpriced)).quantize(CENT)
        row.basis = "observed"
        row.computed_at = now
        # Flows and the day's return are worked in by the rebuild that follows.
        row.flow_in = row.flow_in or ZERO
        row.flow_out = row.flow_out or ZERO
        row.advisory_fees = row.advisory_fees or ZERO


def run_daily_capture(db: Session) -> Dict[str, str]:
    """Called by the scheduler — captures every mapped account for the day."""
    return DailyCaptureService(db).capture_all()
