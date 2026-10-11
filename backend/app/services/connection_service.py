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
from app.connectors.models import NotSupported, RawAccount
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
from app.services.weekly_snapshot_service import WeeklySnapshotService

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

    def start_link(self, client_id: str, redirect_uri: str = "") -> Dict:
        """A hosted portal URL where the client authorizes a brokerage."""
        self._client_or_raise(client_id)
        session = self.connector.initiate_link(self._user_id(), redirect_uri)
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
            row.status = "active" if remote.status == "active" else "broken"
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

    def sync(self, brokerage_account_id: str, force: bool = False) -> Dict:
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
        if last is None and ba.sync_start_date is not None:
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
        earliest = self._ingest(ba, batch, result)

        ba.last_synced_at = now
        if remote is not None and remote.transactions_synced_through:
            ba.transactions_synced_through = remote.transactions_synced_through
        elif batch.trades:
            ba.transactions_synced_through = batch.trades[-1].executed_at.date()
        self.db.commit()

        self._recompute_snapshots(earliest)

        try:
            self.reconcile(ba.id, skipped_rows=batch.skipped)
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            logger.warning("Reconciliation failed for account %s: %s", ba.id, exc)

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

    def _recompute_snapshots(self, earliest: Dict[str, date]) -> None:
        snapshots = WeeklySnapshotService(self.db)
        for sleeve_id, when in earliest.items():
            try:
                snapshots.recompute_from(sleeve_id, when)
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                logger.error(
                    "Snapshot recompute failed for sleeve %s: %s", sleeve_id, exc
                )

    def rederive(self, brokerage_account_id: str) -> Dict:
        """Re-read the account's stored source rows under the current rules.

        For when the mapping changes — a new kind of activity is understood, a
        route is added — and the rows already fetched should be read again.
        Makes no call to the source, so it is not subject to the sync limit.
        Trades already on file are recognised as duplicates and left alone, so
        this only ever adds; it does not move or remove existing trades.
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

        result = {
            "rows": len(records),
            "imported": 0,
            "duplicates": 0,
            "cash_imported": 0,
            "skipped_rows": dict(batch.skipped),
        }
        earliest = self._ingest(ba, batch, result)
        self.db.commit()
        self._recompute_snapshots(earliest)
        return result

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
        self, brokerage_account_id: str, skipped_rows: Optional[Dict] = None
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
        ba.reconciliation = report
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
        self.db.commit()
        return report

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
            self.reconcile(ba.id)
            return "reconciled"

        # CONNECTION_ADDED lands here too: a new login has no client yet, so it
        # is picked up when that client runs discovery.
        return "ignored"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
    db: Session, brokerage_account_id: str, force: bool = False
) -> Dict:
    """Pull new trades and cash activity for one mapped brokerage account.

    Skips, with a reason, when the account was synced under 24 hours ago, when
    the source has not finished its first history pull, or when it rate limits
    us. Otherwise ingests through the shared pipeline, advances the watermark,
    recomputes snapshots, and reconciles against the brokerage's holdings.

    Raises LookupError / ValueError so callers can translate to HTTP errors.
    """
    return ConnectionService(db).sync(brokerage_account_id, force=force)


def run_all_brokerage_syncs(db: Session) -> Dict[str, str]:
    """Called by the APScheduler job — syncs every mapped brokerage account."""
    return ConnectionService(db).sync_all_mapped()
