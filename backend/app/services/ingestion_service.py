"""Shared trade ingestion pipeline — one VALIDATE→IMPORT path for every source.

Connectors *produce* ``NormalizedTrade`` objects; this service *validates,
dedups, routes, and persists* them. Every source (CSV, Sheets, Webull, and
future brokers) feeds this single pipeline — do not duplicate it per source.

``NormalizedTrade.external_id`` is the idempotent dedup key. For CSV/Sheets it
encodes the same identity the legacy pipeline used — CSV: ``(date, symbol, qty,
price)`` per sleeve; Sheets: the sheet row id — so dedup behavior is unchanged
behind the new seam.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.connectors.models import NormalizedTrade
from app.models.account import Account
from app.models.client import Client
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.sync_log import SyncLog
from app.models.trade import Trade
from app.services.portfolio_calculation import PortfolioCalculationService

logger = logging.getLogger(__name__)


def _trade_dedup_key(trade_date, symbol, quantity, price) -> tuple:
    """Normalize a trade into the legacy comparable key (date, symbol, qty, price)."""
    if isinstance(trade_date, str):
        trade_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
    return (trade_date, str(symbol).upper(), float(quantity), float(price))


def csv_external_id(trade_date, symbol, quantity, price) -> str:
    """Stable external id for a CSV-sourced trade.

    Encodes the same ``(date, symbol, qty, price)`` identity CSV dedup has
    always used, so re-uploads collapse exactly as before.
    """
    d, s, q, p = _trade_dedup_key(trade_date, symbol, quantity, price)
    return f"csv:{d.isoformat()}:{s}:{q}:{p}"


class IngestionService:
    """Validates, dedups, routes and persists normalized trades."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public entry points — one per routing shape
    # ------------------------------------------------------------------

    def ingest_to_sleeve(
        self,
        trades: List[NormalizedTrade],
        sleeve_id: str,
        mode: str = "IMPORT",
        import_type: str = "HISTORICAL",
        total_rows: Optional[int] = None,
        prior_error_count: int = 0,
    ) -> Dict:
        """Ingest pre-validated normalized trades into a single explicit sleeve.

        Dedup is per sleeve, keyed on each existing trade's identity. Mirrors
        the legacy ``TradeImportService.import_from_file`` result contract.
        ``total_rows`` overrides the reported ``total`` with the source's raw
        row count (CSV/Sheets report raw rows, not valid-trade count).
        ``prior_error_count`` is the number of upstream validation errors, added
        to the SyncLog ``rows_failed`` tally as the legacy pipeline did.
        """
        result = {
            "success": False,
            "total": total_rows if total_rows is not None else len(trades),
            "imported": 0,
            "duplicates": 0,
            "errors": [],
            "sync_log_id": None,
            "affected_sleeve_ids": [],
        }

        sleeve = self.db.query(Sleeve).filter(Sleeve.id == sleeve_id).first()
        if not sleeve:
            result["errors"].append(f"Sleeve {sleeve_id} not found")
            return result

        if not trades:
            result["errors"].insert(0, "No valid trades found")
            return result

        existing_keys = self._existing_keys(sleeve_id)
        to_import: List[NormalizedTrade] = []
        for t in trades:
            key = _trade_dedup_key(t.executed_at.date(), t.symbol, t.quantity, t.price)
            if key in existing_keys:
                result["duplicates"] += 1
                continue
            existing_keys.add(key)
            to_import.append(t)

        result["imported"] = len(to_import)

        if mode == "VALIDATE":
            result["success"] = True
            return result

        sync_log = self._start_log(
            import_type, result["total"], result["duplicates"] + prior_error_count
        )
        result["sync_log_id"] = sync_log.id

        try:
            for t in to_import:
                self.db.add(self._to_trade(sleeve_id, t))
            sync_log.rows_success = result["imported"]
            sync_log.status = "SUCCESS"
            self.db.commit()
            result["success"] = True
            result["affected_sleeve_ids"] = [sleeve_id] if to_import else []
            logger.info(f"Ingested {result['imported']} trades for sleeve {sleeve_id}")
            self._refresh_positions(result["affected_sleeve_ids"])
        except IntegrityError as e:
            self.db.rollback()
            sync_log.status = "FAILED"
            sync_log.error_details = str(e)
            self.db.commit()
            result["errors"].append(f"Database error: {str(e)}")
            result["imported"] = 0
            logger.error(f"Ingestion failed with database error: {e}")
        except Exception as e:  # noqa: BLE001
            self.db.rollback()
            sync_log.status = "FAILED"
            sync_log.error_details = str(e)
            self.db.commit()
            result["errors"].append(f"Unexpected error: {str(e)}")
            result["imported"] = 0
            logger.error(f"Ingestion failed: {e}")

        return result

    def ingest_routed(
        self,
        trades: List[NormalizedTrade],
        client_id: str,
        mode: str = "IMPORT",
        import_type: str = "HISTORICAL",
        total_rows: Optional[int] = None,
        prior_error_count: int = 0,
    ) -> Dict:
        """Ingest normalized trades, auto-routing each to account + strategy.

        Resolves the Account (by ``account`` number), the global Strategy (by
        name), and the linking Sleeve, creating any that are missing (IMPORT
        only). Dedup is per resolved sleeve. Mirrors the legacy
        ``TradeImportService.import_routed`` result contract. ``total_rows`` and
        ``prior_error_count`` carry the source's raw row count and upstream
        validation-error count for the result/SyncLog tallies.
        """
        result = {
            "success": False,
            "total": total_rows if total_rows is not None else len(trades),
            "imported": 0,
            "duplicates": 0,
            "errors": [],
            "sync_log_id": None,
            "accounts_created": 0,
            "strategies_created": 0,
            "sleeves_created": 0,
            "affected_sleeve_ids": [],
        }

        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            result["errors"].append(f"Client {client_id} not found")
            return result

        routable: List[NormalizedTrade] = []
        for t in trades:
            if not t.account:
                result["errors"].append(
                    f"{t.symbol} {t.executed_at.date()}: missing Account for auto-route"
                )
            elif not t.strategy:
                result["errors"].append(
                    f"{t.symbol} {t.executed_at.date()}: missing Strategy for auto-route"
                )
            else:
                routable.append(t)

        if not routable:
            result["errors"].insert(
                0, "No trades have both Account and Strategy for routing"
            )
            return result

        create = mode == "IMPORT"
        account_cache: Dict[str, Optional[Account]] = {}
        strategy_def_cache: Dict[str, Optional[Strategy]] = {}
        sleeve_cache: Dict[tuple, Optional[Sleeve]] = {}
        new_accounts: set = set()
        new_strategies: set = set()
        new_sleeves: set = set()
        seen_keys: Dict[str, set] = {}

        sync_log = None
        if create:
            sync_log = self._start_log(
                import_type, result["total"], result["duplicates"] + prior_error_count
            )
            result["sync_log_id"] = sync_log.id

        affected_sleeves: set = set()
        try:
            for t in routable:
                account = self._resolve_account(
                    client_id, t.account, create, account_cache, new_accounts
                )
                sleeve = self._resolve_sleeve(
                    account,
                    t.account,
                    t.strategy,
                    create,
                    strategy_def_cache,
                    sleeve_cache,
                    new_strategies,
                    new_sleeves,
                )

                bucket = (
                    sleeve.id
                    if sleeve is not None
                    else f"NEW::{t.account}::{t.strategy.lower()}"
                )
                if bucket not in seen_keys:
                    seen_keys[bucket] = (
                        self._existing_keys(sleeve.id) if sleeve is not None else set()
                    )

                key = _trade_dedup_key(
                    t.executed_at.date(), t.symbol, t.quantity, t.price
                )
                if key in seen_keys[bucket]:
                    result["duplicates"] += 1
                    continue
                seen_keys[bucket].add(key)

                result["imported"] += 1
                if create:
                    affected_sleeves.add(sleeve.id)
                    self.db.add(self._to_trade(sleeve.id, t))

            result["accounts_created"] = len(new_accounts)
            result["strategies_created"] = len(new_strategies)
            result["sleeves_created"] = len(new_sleeves)

            if create:
                sync_log.rows_success = result["imported"]
                sync_log.rows_failed = result["duplicates"] + prior_error_count
                sync_log.status = "SUCCESS"
                self.db.commit()
                result["affected_sleeve_ids"] = list(affected_sleeves)
                logger.info(
                    f"Routed ingest: {result['imported']} trades for client {client_id}"
                )
                self._refresh_positions(affected_sleeves)

            result["success"] = True
            return result

        except Exception as e:  # noqa: BLE001
            self.db.rollback()
            if sync_log is not None:
                sync_log.status = "FAILED"
                sync_log.error_details = str(e)
                self.db.commit()
            result["errors"].append(f"Routed ingest error: {str(e)}")
            result["imported"] = 0
            logger.error(f"Routed ingest failed: {e}")
            return result

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_trade(sleeve_id: str, t: NormalizedTrade) -> Trade:
        """Map a normalized trade into a persisted ``Trade`` row.

        ``google_sheet_row_id`` is intentionally left NULL: dedup is enforced in
        this service by ``external_id`` identity, matching the legacy pipeline
        (which deduped sheet trades on the ``(date, symbol, qty, price)`` tuple,
        not the row id column). The unique column stays available for a future
        row-id-keyed source without changing today's behavior.
        """
        return Trade(
            sleeve_id=sleeve_id,
            trade_date=t.executed_at.date(),
            symbol=t.symbol,
            action=t.action.value,
            quantity=Decimal(str(t.quantity)),
            price=Decimal(str(t.price)),
            commission=Decimal(str(t.commission)),
            notes=t.notes,
        )

    def _start_log(self, import_type: str, processed: int, duplicates: int) -> SyncLog:
        sync_log = SyncLog(
            import_type=import_type,
            status="IN_PROGRESS",
            rows_processed=processed,
            rows_success=0,
            rows_failed=duplicates,
        )
        self.db.add(sync_log)
        self.db.flush()
        return sync_log

    def _existing_keys(self, sleeve_id: Optional[str]) -> set:
        if not sleeve_id:
            return set()
        existing = self.db.query(Trade).filter(Trade.sleeve_id == sleeve_id).all()
        return {
            _trade_dedup_key(e.trade_date, e.symbol, float(e.quantity), float(e.price))
            for e in existing
        }

    def _refresh_positions(self, sleeve_ids: Iterable[str]) -> None:
        """Recalculate and persist positions for affected sleeves (best-effort)."""
        calc = PortfolioCalculationService(self.db)
        for sid in set(sleeve_ids):
            try:
                calc.persist_all_positions(sid)
            except Exception as e:  # noqa: BLE001
                self.db.rollback()
                logger.error(f"Failed to refresh positions for sleeve {sid}: {e}")

    # ------------------------------------------------------------------
    # Routing resolution (account / strategy / sleeve)
    # ------------------------------------------------------------------

    def _resolve_account(
        self, client_id, account_number, create, cache, new_accounts
    ) -> Optional[Account]:
        if account_number in cache:
            return cache[account_number]
        account = (
            self.db.query(Account)
            .filter(
                Account.client_id == client_id,
                Account.account_number == account_number,
            )
            .first()
        )
        if account is None and create:
            account = Account(
                id=str(uuid.uuid4()),
                client_id=client_id,
                account_number=account_number,
                name=f"Account {account_number}",
                description="Auto-created during import",
            )
            self.db.add(account)
            self.db.flush()
            new_accounts.add(account_number)
        elif account is None:
            new_accounts.add(account_number)  # VALIDATE: would be created
        cache[account_number] = account
        return account

    def _resolve_strategy_def(
        self, strategy_name, create, cache, new_strategies
    ) -> Optional[Strategy]:
        key = strategy_name.lower()
        if key in cache:
            return cache[key]
        strategy = (
            self.db.query(Strategy).filter(func.lower(Strategy.name) == key).first()
        )
        if strategy is None and create:
            strategy = Strategy(
                id=str(uuid.uuid4()),
                name=strategy_name,
                description="Auto-created during import",
            )
            self.db.add(strategy)
            self.db.flush()
            new_strategies.add(key)
        elif strategy is None:
            new_strategies.add(key)  # VALIDATE: would be created
        cache[key] = strategy
        return strategy

    def _resolve_sleeve(
        self,
        account,
        account_number,
        strategy_name,
        create,
        strategy_def_cache,
        sleeve_cache,
        new_strategies,
        new_sleeves,
    ) -> Optional[Sleeve]:
        key = (account_number, strategy_name.lower())
        if key in sleeve_cache:
            return sleeve_cache[key]

        strategy = self._resolve_strategy_def(
            strategy_name, create, strategy_def_cache, new_strategies
        )

        sleeve = None
        if account is not None and strategy is not None:
            sleeve = (
                self.db.query(Sleeve)
                .filter(
                    Sleeve.account_id == account.id,
                    Sleeve.strategy_id == strategy.id,
                )
                .first()
            )
        if sleeve is None and create and account is not None and strategy is not None:
            sleeve = Sleeve(
                id=str(uuid.uuid4()),
                account_id=account.id,
                strategy_id=strategy.id,
            )
            self.db.add(sleeve)
            self.db.flush()
            new_sleeves.add(key)
        elif sleeve is None:
            new_sleeves.add(key)  # would be created
        sleeve_cache[key] = sleeve
        return sleeve
