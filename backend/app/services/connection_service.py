"""Brokerage connections — linking, account mapping, and the shared sync.

Sits on the connector seam: a connector fetches and normalizes brokerage data,
the shared ``IngestionService`` dedups and persists it, and this service owns
the bookkeeping in between (which login, which account, how far synced).

``sync_brokerage_account`` is the single sync path. The manual route, the
scheduler job and the webhook handler all call it — do not inline it.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors.models import NotSupported, RawAccount, is_option_symbol
from app.connectors.registry import get_connector
from app.models.account import Account
from app.models.brokerage_connection import (
    BrokerageAccount,
    BrokerageActivity,
    BrokerageConnection,
)
from app.models.client import Client
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

SOURCE = "snaptrade"

# Strategy a linked account's trades land in until they are split out.
DEFAULT_STRATEGY_NAME = "Unallocated"

# The source asks for at least this long between transaction pulls per account.
MIN_SYNC_INTERVAL = timedelta(hours=24)

# Each sync re-reads this far behind the previous watermark. Brokerages post
# and correct rows late; dedup makes the overlap free.
SYNC_OVERLAP = timedelta(days=7)

# The portal URL the source hands back is only valid this long.
LINK_EXPIRES_SECONDS = 300

# Share-count differences below this are rounding, not drift.
_QUANTITY_TOLERANCE = Decimal("0.000001")


class ConnectionService:
    """Links brokerage logins and keeps their accounts synced."""

    def __init__(self, db: Session, connector=None):
        self.db = db
        self.connector = connector or get_connector(SOURCE)

    # ------------------------------------------------------------------
    # Linking and discovery
    # ------------------------------------------------------------------

    def start_link(
        self,
        client_id: str,
        redirect_uri: str = "",
        connection_id: Optional[str] = None,
    ) -> Dict:
        """A hosted portal URL where the client authorizes a brokerage.

        With ``connection_id`` the portal signs in again to that existing link
        (one the brokerage has stopped sharing), keeping its accounts and their
        mappings. Without it, the portal adds a new link.
        """
        self._client_or_raise(client_id)
        reconnect = None
        if connection_id:
            connection = (
                self.db.query(BrokerageConnection)
                .filter(
                    BrokerageConnection.id == connection_id,
                    BrokerageConnection.source == SOURCE,
                    BrokerageConnection.status != "deleted",
                )
                .first()
            )
            if connection is None:
                raise LookupError("Brokerage link not found")
            reconnect = connection.external_connection_id
        session = self.connector.initiate_link(
            self._user_id(), redirect_uri, reconnect=reconnect
        )
        return {
            "redirect_url": session.redirect_url,
            "expires_in_seconds": LINK_EXPIRES_SECONDS,
        }

    def discover(self, client_id: str) -> List[BrokerageConnection]:
        """Record the logins and accounts the source currently reports.

        There is no callback to exchange after the portal, so this is how a new
        link becomes known. Safe to repeat: existing rows are updated, mappings
        are never touched, and a login the source no longer lists is marked
        deleted.
        """
        self._client_or_raise(client_id)
        user_id = self._user_id()

        seen: Dict[str, BrokerageConnection] = {}
        for remote in self.connector.list_connections(user_id):
            if not remote.connection_id:
                continue
            row = (
                self.db.query(BrokerageConnection)
                .filter(
                    BrokerageConnection.source == SOURCE,
                    BrokerageConnection.external_connection_id == remote.connection_id,
                )
                .first()
            )
            if row is None:
                row = BrokerageConnection(
                    client_id=client_id,
                    source=SOURCE,
                    external_user_id=user_id,
                    external_connection_id=remote.connection_id,
                )
                self.db.add(row)
            row.institution = remote.institution or row.institution or ""
            self._record_link_state(row, remote)
            seen[remote.connection_id] = row
        self.db.flush()

        for row in self.db.query(BrokerageConnection).filter(
            BrokerageConnection.source == SOURCE,
            BrokerageConnection.external_user_id == user_id,
            BrokerageConnection.status != "deleted",
        ):
            if row.external_connection_id not in seen:
                row.status = "deleted"

        for remote_account in self.connector.fetch_accounts(user_id):
            connection = seen.get(remote_account.connection_ref or "")
            if connection is None and len(seen) == 1:
                connection = next(iter(seen.values()))
            if connection is None or not remote_account.external_ref:
                continue
            self._upsert_brokerage_account(connection, remote_account)

        self.db.commit()
        return self.list_connections(client_id)

    def list_connections(self, client_id: str) -> List[BrokerageConnection]:
        """A client's connections that have not been removed."""
        return (
            self.db.query(BrokerageConnection)
            .filter(
                BrokerageConnection.client_id == client_id,
                BrokerageConnection.status != "deleted",
            )
            .order_by(BrokerageConnection.created_at)
            .all()
        )

    def remove_connection(self, connection_id: str) -> None:
        """Revoke a login at the source and stop syncing it.

        Trades already ingested stay: they are the client's history, and
        removing a link should not rewrite past performance.
        """
        connection = (
            self.db.query(BrokerageConnection)
            .filter(BrokerageConnection.id == connection_id)
            .first()
        )
        if connection is None or connection.status == "deleted":
            raise LookupError("Connection not found")
        self.connector.remove_connection(connection.external_connection_id)
        connection.status = "deleted"
        self.db.commit()

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def map_account(
        self,
        brokerage_account_id: str,
        account_id: Optional[str] = None,
        strategy_id: Optional[str] = None,
        client_id: Optional[str] = None,
        strategy_routes: Optional[Dict[str, str]] = None,
        history_start: Optional[date] = None,
    ) -> BrokerageAccount:
        """Bring a discovered account into the hierarchy.

        Creates the Achalara account unless an existing one is named, and
        resolves the sleeve its trades are ingested into (the named strategy,
        or "Unallocated"). The sleeve must be empty: a sleeve holds trades from
        one source, so brokerage activity is never mixed into imported ones.

        The account need not belong to the client who owns the login. One
        person's login routinely reaches accounts they only act on as agent, so
        ``client_id`` names the account's actual owner (default: the login's).

        ``strategy_routes`` splits the account by what is traded: it maps a
        security type ("ETF") to the strategy whose sleeve takes those trades,
        and every other type goes to ``strategy_id``. ``history_start`` limits
        how far back the first sync reaches.
        """
        ba = self.get_brokerage_account(brokerage_account_id)
        if ba.last_synced_at is not None:
            raise ValueError("Account has already been synced and cannot be remapped")

        if account_id:
            account = self.db.query(Account).filter(Account.id == account_id).first()
            if account is None:
                raise LookupError("Account not found")
            if client_id and account.client_id != client_id:
                raise ValueError("That account belongs to a different client")
        else:
            owner = self._client_or_raise(client_id or ba.connection.client_id)
            account = Account(
                client_id=owner.id,
                name=ba.name,
                account_number=f"****{ba.number_last4}" if ba.number_last4 else None,
                description=f"Linked via {ba.connection.institution or SOURCE}",
            )
            self.db.add(account)
            self.db.flush()

        if strategy_id:
            strategy = self._strategy_or_raise(strategy_id)
        else:
            strategy = self._default_strategy()
        sleeve = self._empty_fifo_sleeve(account, strategy)

        routes: Dict[str, str] = {}
        for security_type, routed_strategy_id in (strategy_routes or {}).items():
            routed = self._empty_fifo_sleeve(
                account, self._strategy_or_raise(routed_strategy_id)
            )
            routes[security_type.strip().upper()] = routed.id

        ba.account_id = account.id
        ba.default_sleeve_id = sleeve.id
        ba.sleeve_routes = routes or None
        ba.sync_start_date = history_start
        ba.status = "mapped"
        self.db.commit()
        return ba

    def _strategy_or_raise(self, strategy_id: str) -> Strategy:
        strategy = self.db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if strategy is None:
            raise LookupError("Strategy not found")
        return strategy

    def _empty_fifo_sleeve(self, account: Account, strategy: Strategy) -> Sleeve:
        """The account's sleeve for ``strategy``, created if missing, set to FIFO.

        Refuses a sleeve that already holds trades: those came from another
        source, and a sleeve holds trades from one source only.
        """
        sleeve = (
            self.db.query(Sleeve)
            .filter(Sleeve.account_id == account.id, Sleeve.strategy_id == strategy.id)
            .first()
        )
        if sleeve is None:
            sleeve = Sleeve(account_id=account.id, strategy_id=strategy.id)
            self.db.add(sleeve)
            self.db.flush()
        elif self.db.query(Trade.id).filter(Trade.sleeve_id == sleeve.id).first():
            raise ValueError(
                "That account and strategy already hold trades from another "
                "source; choose a different strategy"
            )
        sleeve.accounting_method = "FIFO"
        return sleeve

    def ignore_account(self, brokerage_account_id: str) -> BrokerageAccount:
        """Leave a discovered account out of Achalara; it is never synced."""
        ba = self.get_brokerage_account(brokerage_account_id)
        ba.status = "ignored"
        self.db.commit()
        return ba

    def get_brokerage_account(self, brokerage_account_id: str) -> BrokerageAccount:
        ba = (
            self.db.query(BrokerageAccount)
            .filter(BrokerageAccount.id == brokerage_account_id)
            .first()
        )
        if ba is None:
            raise LookupError("Brokerage account not found")
        return ba

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def sync(
        self,
        brokerage_account_id: str,
        force: bool = False,
        full_history: bool = False,
    ) -> Dict:
        """Pull new activity for one mapped account. See ``sync_brokerage_account``."""
        ba = self.get_brokerage_account(brokerage_account_id)
        if ba.status != "mapped" or not ba.default_sleeve_id:
            raise ValueError("Map the account to a sleeve before syncing it")
        if ba.connection.status != "active":
            raise ValueError(
                f"Connection is {ba.connection.status}; re-link the brokerage first"
            )

        now = datetime.now(timezone.utc)
        result = {
            "status": "skipped",
            "reason": None,
            "imported": 0,
            "duplicates": 0,
            "cash_imported": 0,
            "skipped_rows": {},
            "next_sync_allowed_at": None,
            "transactions_synced_through": ba.transactions_synced_through,
        }

        last = _aware(ba.last_synced_at)
        if not force and last is not None and now - last < MIN_SYNC_INTERVAL:
            result["reason"] = "synced_recently"
            result["next_sync_allowed_at"] = last + MIN_SYNC_INTERVAL
            return result

        user_id = ba.connection.external_user_id
        remote = self._remote_account(user_id, ba.external_account_ref)
        if remote is not None and remote.initial_sync_completed is not None:
            ba.initial_sync_completed = remote.initial_sync_completed
        if remote is not None and remote.initial_sync_completed is False:
            # The source returns no activity at all until its first history
            # pull finishes; syncing now would only spend the daily call.
            self.db.commit()
            result["reason"] = "initial_sync_pending"
            return result

        since = None
        if full_history:
            # Everything the source holds, back to the account's first day.
            # Rows already on file are recognised and left alone.
            ba.sync_start_date = None
        elif last is None and ba.sync_start_date is not None:
            since = datetime.combine(
                ba.sync_start_date, datetime.min.time(), tzinfo=timezone.utc
            )
        elif last is not None:
            watermark = ba.transactions_synced_through or last.date()
            since = datetime.combine(
                watermark - SYNC_OVERLAP, datetime.min.time(), tzinfo=timezone.utc
            )

        try:
            batch = self.connector.fetch_activities(
                user_id, ba.external_account_ref, since=since
            )
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "status", None) != 429:
                raise
            # Rate limited: report it and wait for the next scheduled run.
            # Retrying here would only dig the limit deeper.
            logger.warning("SnapTrade rate limit hit syncing account %s", ba.id)
            result["reason"] = "rate_limited"
            return result

        self._store_raw(ba, batch.raw)
        self._ingest(ba, batch, result)

        ba.last_synced_at = now
        self._refresh_cash_balance(ba)
        if remote is not None and remote.transactions_synced_through:
            ba.transactions_synced_through = remote.transactions_synced_through
        elif batch.trades:
            ba.transactions_synced_through = batch.trades[-1].executed_at.date()
        self.db.commit()

        try:
            self.reconcile(ba.id, skipped_rows=batch.skipped)
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.warning("Reconciliation failed for account %s: %s", ba.id, exc)

        # After reconciling: the cash history leans on what it found.
        self._after_trades_changed(ba)

        result["status"] = "synced"
        result["skipped_rows"] = dict(batch.skipped)
        result["security_type_sources"] = dict(batch.security_type_sources)
        result["transactions_synced_through"] = ba.transactions_synced_through
        result["next_sync_allowed_at"] = now + MIN_SYNC_INTERVAL
        return result

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

    def rederive(self, brokerage_account_id: str) -> Dict:
        """Re-read the account's stored source rows under the current rules.

        For when the mapping changes — a new kind of activity is understood, a
        route is added — and the rows already fetched should be read again.
        Makes no call to the source, so it is not subject to the sync limit.
        Trades already on file are recognised as duplicates: none is moved or
        removed, and only their fees are brought up to date.
        """
        ba = self.get_brokerage_account(brokerage_account_id)
        if ba.status != "mapped" or not ba.default_sleeve_id:
            raise ValueError("Map the account to a sleeve before re-deriving it")

        records = (
            self.db.query(BrokerageActivity)
            .filter(BrokerageActivity.brokerage_account_id == ba.id)
            .order_by(BrokerageActivity.activity_date, BrokerageActivity.id)
            .all()
        )
        batch = self.connector.parse_activities(
            [record.payload for record in records], ba.external_account_ref
        )
        for record, raw in zip(records, batch.raw):
            record.outcome = raw.outcome
            record.cash_amount = raw.cash_amount
            record.is_external_flow = raw.is_external_flow

        result = {
            "rows": len(records),
            "imported": 0,
            "duplicates": 0,
            "cash_imported": 0,
            "skipped_rows": dict(batch.skipped),
        }
        self._ingest(ba, batch, result)
        result["fees_corrected"] = self._restate_fees(ba, batch)
        self.db.commit()
        self._after_trades_changed(ba)
        return result

    def _restate_fees(self, ba: BrokerageAccount, batch) -> int:
        """Bring the fees of trades already on file to the current reading.

        A fee is not part of what identifies a trade, so a change in how it is
        read leaves the trade a duplicate and would otherwise never reach it.
        """
        read = {t.external_id: t.commission for t in batch.trades if t.external_id}
        corrected = 0
        for trade in self.db.query(Trade).filter(
            Trade.sleeve_id.in_(
                self.db.query(Sleeve.id).filter(Sleeve.account_id == ba.account_id)
            ),
            Trade.external_id.in_(list(read)),
        ):
            fee = read[trade.external_id]
            if Decimal(str(trade.commission or 0)) != fee:
                trade.commission = fee
                corrected += 1
        return corrected

    def _refresh_cash_balance(self, ba: BrokerageAccount) -> None:
        """Record the cash the source reports for the account now.

        Best-effort: without it the account simply stays securities-only.
        """
        fetch = getattr(self.connector, "fetch_cash_balance", None)
        if fetch is None:
            return
        try:
            cash = fetch(ba.connection.external_user_id, ba.external_account_ref)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cash balance unavailable for account %s: %s", ba.id, exc)
            return
        if cash is not None:
            ba.cash_balance = cash
            ba.cash_balance_at = datetime.now(timezone.utc)

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

    def sync_all_mapped(self) -> Dict[str, str]:
        """Sync every mapped account on an active connection (scheduler job).

        One account failing does not stop the rest.
        """
        accounts = (
            self.db.query(BrokerageAccount)
            .join(BrokerageConnection)
            .filter(
                BrokerageAccount.status == "mapped",
                BrokerageConnection.status == "active",
                BrokerageConnection.source == SOURCE,
            )
            .all()
        )
        logger.info("Brokerage sync job starting: %d account(s)", len(accounts))
        outcomes: Dict[str, str] = {}
        for account_id in [a.id for a in accounts]:
            try:
                result = self.sync(account_id)
                outcomes[account_id] = result["reason"] or result["status"]
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                logger.error(
                    "Brokerage sync failed for account %s: %s", account_id, exc
                )
                outcomes[account_id] = "failed"
        return outcomes

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile(
        self,
        brokerage_account_id: str,
        skipped_rows: Optional[Dict] = None,
        holdings: Optional[list] = None,
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
            holdings = self.connector.fetch_positions(
                ba.connection.external_user_id, ba.external_account_ref
            )
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
            self._valuation_adjustment(ba, holdings, sleeve_ids)
        )
        ba.reconciliation = report

        self.db.commit()
        return report

    def _valuation_adjustment(self, ba, holdings, sleeve_ids) -> Decimal:
        """What the brokerage's account total implies our options are mispriced by.

        Nothing here can quote an option, so open contracts sit at their last
        traded price, which can be far from market. The brokerage's total is
        its holdings plus cash plus those contracts at market; taking the
        first two away leaves what the contracts are really worth, and the gap
        to our figure is the correction. Zero when the brokerage reports no
        total or no cash, or when no options are open.
        """
        if ba.cash_balance is None:
            return Decimal(0)
        remote = self._remote_account(
            ba.connection.external_user_id, ba.external_account_ref
        )
        if remote is None or remote.total_value is None:
            return Decimal(0)

        net: Dict[str, Decimal] = {}
        last_price: Dict[str, Decimal] = {}
        for trade in (
            self.db.query(Trade)
            .filter(Trade.sleeve_id.in_(sleeve_ids), Trade.security_type == "OPTION")
            .order_by(Trade.trade_date, Trade.id)
        ):
            signed = trade.quantity if trade.action == "BUY" else -trade.quantity
            net[trade.symbol] = net.get(trade.symbol, Decimal(0)) + signed
            last_price[trade.symbol] = trade.price
        ours = sum((qty * last_price[s] for s, qty in net.items()), Decimal(0))
        if not any(net.values()):
            return Decimal(0)

        holdings_value = sum(
            (
                h.quantity * h.market_price
                for h in holdings
                if h.market_price is not None
            ),
            Decimal(0),
        )
        implied = remote.total_value - holdings_value - Decimal(str(ba.cash_balance))
        return implied - ours

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    def handle_webhook(self, event: Dict) -> str:
        """Act on a verified webhook event; returns what was done.

        Unknown events and events for logins we do not know are acknowledged
        and ignored, so the source does not keep retrying them.
        """
        event_type = str(event.get("eventType") or "")
        connection_ref = event.get("brokerageAuthorizationId") or event.get(
            "brokerageId"
        )
        account_ref = event.get("accountId")

        connection = None
        if connection_ref:
            connection = (
                self.db.query(BrokerageConnection)
                .filter(
                    BrokerageConnection.source == SOURCE,
                    BrokerageConnection.external_connection_id == str(connection_ref),
                )
                .first()
            )

        if event_type in ("CONNECTION_BROKEN", "CONNECTION_DELETED"):
            if connection is None:
                return "ignored"
            connection.status = (
                "broken" if event_type == "CONNECTION_BROKEN" else "deleted"
            )
            self.db.commit()
            return "status_updated"

        if event_type in ("CONNECTION_FIXED", "NEW_ACCOUNT_AVAILABLE"):
            if connection is None:
                return "ignored"
            self.discover(connection.client_id)
            return "discovered"

        if event_type in (
            "ACCOUNT_TRANSACTIONS_INITIAL_UPDATE",
            "ACCOUNT_TRANSACTIONS_UPDATED",
        ):
            ba = (
                self.db.query(BrokerageAccount)
                .filter(BrokerageAccount.external_account_ref == str(account_ref))
                .first()
                if account_ref
                else None
            )
            if ba is None or ba.status != "mapped":
                return "ignored"
            # The source is telling us new data is ready, so this pull is the
            # one it expects; the interval guard is for unprompted polling.
            self.sync(ba.id, force=True)
            return "synced"

        if event_type == "ACCOUNT_HOLDINGS_UPDATED":
            ba = (
                self.db.query(BrokerageAccount)
                .filter(BrokerageAccount.external_account_ref == str(account_ref))
                .first()
                if account_ref
                else None
            )
            if ba is None or ba.status != "mapped":
                return "ignored"
            # The brokerage's holdings have just been refreshed: the moment
            # to record the day.
            from app.services.daily_capture_service import DailyCaptureService

            DailyCaptureService(self.db, self).capture(ba.id)
            return "captured"

        # CONNECTION_ADDED lands here too: a new login has no client yet, so it
        # is picked up when that client runs discovery.
        return "ignored"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_link_state(row: BrokerageConnection, remote) -> None:
        """Take the source's word on whether a link is still sharing data."""
        row.status = "active" if remote.status == "active" else "broken"
        row.status_checked_at = datetime.now(timezone.utc)
        row.disabled_at = None
        if row.status != "active":
            stamp = str((remote.raw or {}).get("disabled_date") or "")
            try:
                row.disabled_at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                row.disabled_at = None

    def check_links(self) -> List[BrokerageConnection]:
        """Ask the source whether each link on file is still sharing data.

        Lighter than ``discover``: it touches only the links already known,
        adds none, and reads no accounts. A brokerage ends a session without
        notice, and until someone asks, the stored state still says "active".
        """
        user_id = self._user_id()
        reported = {
            remote.connection_id: remote
            for remote in self.connector.list_connections(user_id)
            if remote.connection_id
        }
        rows = (
            self.db.query(BrokerageConnection)
            .filter(
                BrokerageConnection.source == SOURCE,
                BrokerageConnection.external_user_id == user_id,
                BrokerageConnection.status != "deleted",
            )
            .all()
        )
        for row in rows:
            remote = reported.get(row.external_connection_id)
            if remote is None:
                # The source no longer lists it at all.
                row.status = "broken"
                row.status_checked_at = datetime.now(timezone.utc)
            else:
                self._record_link_state(row, remote)
        self.db.commit()
        return rows

    def _user_id(self) -> str:
        if not settings.snaptrade_user_id:
            raise NotSupported("SnapTrade is not configured; set SNAPTRADE_USER_ID")
        return settings.snaptrade_user_id

    def _client_or_raise(self, client_id: str) -> Client:
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if client is None:
            raise LookupError("Client not found")
        return client

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

    def _remote_account(self, user_id: str, account_ref: str) -> Optional[RawAccount]:
        for remote in self.connector.fetch_accounts(user_id):
            if remote.external_ref == account_ref:
                return remote
        return None

    def _upsert_brokerage_account(
        self, connection: BrokerageConnection, remote: RawAccount
    ) -> BrokerageAccount:
        row = None
        if connection.id:
            row = (
                self.db.query(BrokerageAccount)
                .filter(
                    BrokerageAccount.connection_id == connection.id,
                    BrokerageAccount.external_account_ref == remote.external_ref,
                )
                .first()
            )
        if row is None:
            row = BrokerageAccount(
                connection_id=connection.id,
                external_account_ref=remote.external_ref,
                status="unmapped",
            )
            self.db.add(row)
        row.name = remote.name
        digits = "".join(ch for ch in (remote.account_number or "") if ch.isalnum())
        row.number_last4 = digits[-4:] or None
        if remote.initial_sync_completed is not None:
            row.initial_sync_completed = remote.initial_sync_completed
        return row


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """Treat a stored naive timestamp as UTC (SQLite drops the offset)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def sync_brokerage_account(
    db: Session,
    brokerage_account_id: str,
    force: bool = False,
    full_history: bool = False,
) -> Dict:
    """Pull new trades and cash activity for one mapped brokerage account.

    Skips, with a reason, when the account was synced under 24 hours ago, when
    the source has not finished its first history pull, or when it rate limits
    us. Otherwise ingests through the shared pipeline, advances the watermark,
    recomputes snapshots, and reconciles against the brokerage's holdings.
    ``full_history`` reloads from the account's first day instead of from the
    last watermark.

    Raises LookupError / ValueError so callers can translate to HTTP errors.
    """
    return ConnectionService(db).sync(
        brokerage_account_id, force=force, full_history=full_history
    )


def run_link_check(db: Session) -> int:
    """Called by the scheduler: refresh the state of every link; how many were checked."""
    if not settings.snaptrade_user_id:
        return 0
    return len(ConnectionService(db).check_links())


def run_all_brokerage_syncs(db: Session) -> Dict[str, str]:
    """Called by the APScheduler job — syncs every mapped brokerage account."""
    return ConnectionService(db).sync_all_mapped()
