"""The shared work behind every feed: storing source rows, ingesting them into
an account's sleeves, and comparing the institution's holdings with ours.

Plaid (``plaid_link_service``, ``plaid_refresh_service``) and a custodian's own
files (``account_import_service``) both come through ``ingest_batch``: rows are
kept verbatim in ``brokerage_activities``, routed to the account's sleeves,
deduplicated across them, and everything derived is brought up to date.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.connectors.models import is_option_symbol
from app.models.brokerage_connection import BrokerageAccount, BrokerageActivity
from app.models.position import Position
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.services.cash_activity_service import CashActivityService
from app.services.ingestion_service import IngestionService
from app.services.portfolio_calculation import PortfolioCalculationService
from app.services.corporate_actions import carry_exchange_costs, record_splits
from app.services.performance_build_service import rebuild_for_sleeves

logger = logging.getLogger(__name__)

# Strategy a linked account's trades land in until they are split out.
DEFAULT_STRATEGY_NAME = "Unallocated"

# Share-count differences below this are rounding, not drift.
_QUANTITY_TOLERANCE = Decimal("0.000001")


class ConnectionService:
    """Ingests a feed's rows into an account and reconciles its holdings."""

    def __init__(self, db: Session, connector=None):
        self.db = db
        # Kept for callers that pass one; nothing here fetches from a source.
        self.connector = connector

    def get_brokerage_account(self, brokerage_account_id: str) -> BrokerageAccount:
        ba = (
            self.db.query(BrokerageAccount)
            .filter(BrokerageAccount.id == brokerage_account_id)
            .first()
        )
        if ba is None:
            raise LookupError("Brokerage account not found")
        return ba

    def _ingest(self, ba: BrokerageAccount, batch, result: Dict) -> Dict[str, date]:
        """Route a batch into the account's sleeves and persist what is new.

        Adds the counts to ``result`` and returns, per sleeve touched, the
        earliest date newly written. Does not commit the cash rows; the caller
        does, along with its own bookkeeping.
        """
        account_sleeves = [
            row[0]
            for row in self.db.query(Sleeve.id).filter(
                Sleeve.account_id == ba.account_id
            )
        ]
        trades_by_sleeve, cash_by_sleeve = self._route(ba, batch, account_sleeves)

        # Earliest newly written date per sleeve, to recompute snapshots from.
        earliest: Dict[str, date] = {}

        def touched(sleeve_id: str, when: Optional[date]) -> None:
            if when is not None and (
                sleeve_id not in earliest or when < earliest[sleeve_id]
            ):
                earliest[sleeve_id] = when

        ingestion = IngestionService(self.db)
        for sleeve_id, trades in trades_by_sleeve.items():
            ingest = ingestion.ingest_to_sleeve(
                trades,
                sleeve_id,
                mode="IMPORT",
                import_type="BROKERAGE",
                dedup_sleeve_ids=account_sleeves,
            )
            if not ingest["success"]:
                raise RuntimeError("; ".join(ingest["errors"]) or "Ingestion failed")
            result["imported"] += ingest["imported"]
            result["duplicates"] += ingest["duplicates"]
            touched(sleeve_id, ingest["earliest_trade_date"])

        cash_service = CashActivityService(self.db)
        for sleeve_id, activities in cash_by_sleeve.items():
            cash = cash_service.ingest(
                activities, sleeve_id, dedup_sleeve_ids=account_sleeves
            )
            result["cash_imported"] += cash["imported"]
            touched(sleeve_id, cash["earliest_activity_date"])

        return earliest

    def ingest_batch(
        self, ba: BrokerageAccount, batch, holdings: Optional[list] = None
    ) -> Dict:
        """Add rows that came from outside the feed, such as a custodian's own
        activity report, as a sync would: routed to the account's sleeves,
        deduplicated across them, kept as source rows (so the cash ledger has
        their cash), then everything derived brought up to date.

        ``holdings`` (the custodian's last recorded holdings) refreshes the
        reconciliation without asking the source; the option correction is
        kept as it was, since working it out needs the source's total.
        """
        if ba.status != "mapped" or not ba.default_sleeve_id:
            raise ValueError("Map the account to a sleeve before adding rows to it")
        result = {"imported": 0, "duplicates": 0, "cash_imported": 0}
        self._store_raw(ba, batch.raw)
        self._ingest(ba, batch, result)
        self.db.commit()
        if holdings is not None:
            try:
                self.reconcile(
                    ba.id,
                    holdings=holdings,
                    valuation_adjustment=Decimal(
                        str((ba.reconciliation or {}).get("valuation_adjustment", 0))
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                logger.warning("Reconciliation failed for account %s: %s", ba.id, exc)
        self._after_trades_changed(ba)
        return result

    def _after_trades_changed(self, ba: BrokerageAccount) -> None:
        """Bring everything derived from the account's trades up to date.

        Splits first, since they change how every earlier trade is read; then
        the positions that reading produces; then the daily valuation.
        """
        sleeve_ids = [
            row[0]
            for row in self.db.query(Sleeve.id).filter(
                Sleeve.account_id == ba.account_id
            )
        ]
        try:
            changed = bool(record_splits(self.db, ba.id))
            changed = bool(carry_exchange_costs(self.db, ba.account_id)) or changed
            if changed:
                self.db.commit()
                positions = PortfolioCalculationService(self.db)
                for sleeve_id in sleeve_ids:
                    positions.persist_all_positions(sleeve_id)
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.error(
                "Recording corporate actions failed for account %s: %s", ba.id, exc
            )
        rebuild_for_sleeves(self.db, sleeve_ids)

    def _store_raw(self, ba: BrokerageAccount, rows) -> None:
        """Keep every fetched row verbatim, replacing any we already hold.

        Each sync re-reads an overlap window, so a row usually arrives more
        than once; the latest copy wins.
        """
        existing = {
            row.source_activity_id: row
            for row in self.db.query(BrokerageActivity).filter(
                BrokerageActivity.brokerage_account_id == ba.id
            )
        }
        for position, raw in enumerate(rows):
            # A row with no id of its own still has to be stored once.
            key = raw.source_id or (
                f"noid:{raw.occurred_on}:{raw.type}:{raw.symbol}:{position}"
            )
            record = existing.get(key)
            if record is None:
                record = BrokerageActivity(
                    brokerage_account_id=ba.id, source_activity_id=key
                )
                self.db.add(record)
                existing[key] = record
            record.activity_date = raw.occurred_on
            record.type = raw.type
            record.symbol = raw.symbol
            record.outcome = raw.outcome
            record.cash_amount = raw.cash_amount
            record.is_external_flow = raw.is_external_flow
            record.payload = raw.payload
        self.db.flush()

    def _route(self, ba: BrokerageAccount, batch, account_sleeves: List[str]):
        """Decide which sleeve each trade and cash activity belongs in.

        In order: the sleeve already holding that symbol in this account, so a
        symbol never straddles two sleeves and one that was moved by hand stays
        moved; then the sleeve routed for its security type; then the default.
        A symbol's first placement in this batch holds for the rest of it.
        """
        placed: Dict[str, str] = {}
        for symbol, sleeve_id in (
            self.db.query(Trade.symbol, Trade.sleeve_id)
            .filter(Trade.sleeve_id.in_(account_sleeves))
            .distinct()
        ):
            placed.setdefault(symbol, sleeve_id)

        routes = ba.sleeve_routes or {}

        def sleeve_for(symbol: Optional[str], security_type: Optional[str]) -> str:
            if not symbol:
                return ba.default_sleeve_id
            if symbol not in placed:
                placed[symbol] = routes.get(security_type or "", ba.default_sleeve_id)
            return placed[symbol]

        trades_by_sleeve: Dict[str, list] = {}
        for trade in batch.trades:
            trades_by_sleeve.setdefault(
                sleeve_for(trade.symbol, trade.security_type), []
            ).append(trade)
        # Cash follows the security it was paid on; trades are placed first so
        # a dividend lands with its shares even when its own row has no type.
        cash_by_sleeve: Dict[str, list] = {}
        for activity in batch.cash:
            cash_by_sleeve.setdefault(
                sleeve_for(activity.symbol, activity.security_type), []
            ).append(activity)
        return trades_by_sleeve, cash_by_sleeve

    def reconcile(
        self,
        brokerage_account_id: str,
        skipped_rows: Optional[Dict] = None,
        holdings: Optional[list] = None,
        valuation_adjustment: Optional[Decimal] = None,
    ) -> Dict:
        """Compare the brokerage's holdings with what our trades add up to.

        Transactions lag holdings by days and some activity is not ingested
        (options, splits, unresolvable symbols), so differences are expected.
        This makes them visible per symbol instead of leaving a wrong number
        unexplained. Also marks open positions to the brokerage's own prices,
        which covers funds the market-data source cannot quote.
        """
        ba = self.get_brokerage_account(brokerage_account_id)
        if not ba.account_id:
            raise ValueError("Account is not mapped")

        if holdings is None:
            raise ValueError("Pass the institution's holdings to reconcile against")
        sleeve_ids = [
            row[0]
            for row in self.db.query(Sleeve.id).filter(
                Sleeve.account_id == ba.account_id
            )
        ]
        derived = PortfolioCalculationService(self.db).calculate_positions(sleeve_ids)
        ours = {p["symbol"]: Decimal(str(p["quantity"])) for p in derived["open"]}

        theirs: Dict[str, Decimal] = {}
        prices: Dict[str, Decimal] = {}
        uncosted = set()
        for holding in holdings:
            theirs[holding.symbol] = (
                theirs.get(holding.symbol, Decimal(0)) + holding.quantity
            )
            if holding.market_price is not None:
                prices[holding.symbol] = holding.market_price
            if not holding.avg_cost:
                uncosted.add(holding.symbol)

        drifted = []
        matched = 0
        for symbol in sorted(set(ours) | set(theirs)):
            brokerage_qty = theirs.get(symbol, Decimal(0))
            derived_qty = ours.get(symbol, Decimal(0))
            if abs(brokerage_qty - derived_qty) <= _QUANTITY_TOLERANCE:
                matched += 1
                continue
            drifted.append(
                {
                    "symbol": symbol,
                    "brokerage_quantity": float(brokerage_qty),
                    "derived_quantity": float(derived_qty),
                    "difference": float(brokerage_qty - derived_qty),
                    # No cost basis yet means the brokerage holds a lot whose
                    # purchase has not reached its transaction feed.
                    "awaiting_transactions": symbol in uncosted,
                }
            )

        previous = ba.reconciliation or {}
        report = {
            "matched": matched,
            "drifted": drifted,
            "unmatched_sells": derived["unmatched_sells"],
            "skipped_rows": (
                dict(skipped_rows)
                if skipped_rows is not None
                else previous.get("skipped_rows", {})
            ),
        }
        ba.last_reconciled_at = datetime.now(timezone.utc)

        if prices:
            for position in self.db.query(Position).filter(
                Position.sleeve_id.in_(sleeve_ids), Position.status == "OPEN"
            ):
                price = prices.get(position.symbol)
                if price is None:
                    continue
                position.current_price = price
                position.market_value = Decimal(str(position.quantity)) * price
                position.unrealized_gain = position.market_value - Decimal(
                    str(position.cost_basis)
                )
        # What the brokerage's holdings are worth beyond (or short of) ours.
        # Its holdings and cash are both current, while our trades trail them;
        # this is the correction that puts today's total on its footing.
        # Options are left out: the holdings feed does not list them.
        # Price each symbol as the valuation of our own positions will: the
        # current price where one is on file, else what it last traded for.
        fallback: Dict[str, Decimal] = {}
        for symbol, price in (
            self.db.query(Trade.symbol, Trade.price)
            .filter(Trade.sleeve_id.in_(sleeve_ids))
            .order_by(Trade.trade_date, Trade.id)
        ):
            fallback[symbol] = Decimal(str(price))
        for position in self.db.query(Position).filter(
            Position.sleeve_id.in_(sleeve_ids),
            Position.status == "OPEN",
            Position.current_price.isnot(None),
        ):
            fallback[position.symbol] = Decimal(str(position.current_price))
        adjustment = Decimal(0)
        for row in drifted:
            symbol = row["symbol"]
            price = prices.get(symbol, fallback.get(symbol))
            if price is None or is_option_symbol(symbol):
                continue
            adjustment += (
                theirs.get(symbol, Decimal(0)) - ours.get(symbol, Decimal(0))
            ) * price
        report["holdings_adjustment"] = float(adjustment)
        report["valuation_adjustment"] = float(
            valuation_adjustment
            if valuation_adjustment is not None
            else (ba.reconciliation or {}).get("valuation_adjustment", 0)
        )
        ba.reconciliation = report

        self.db.commit()
        return report

    def _default_strategy(self) -> Strategy:
        strategy = (
            self.db.query(Strategy)
            .filter(func.lower(Strategy.name) == DEFAULT_STRATEGY_NAME.lower())
            .first()
        )
        if strategy is None:
            strategy = Strategy(
                name=DEFAULT_STRATEGY_NAME,
                description="Brokerage activity not yet assigned to a strategy",
            )
            self.db.add(strategy)
            self.db.flush()
        return strategy
