"""Google Sheets source, behind the connector interface.

Wraps the existing ``GoogleSheetsService`` (public CSV export, no credentials)
and the shared ``TradeValidator`` to emit ``NormalizedTrade`` objects. Sheets
are pull-by-id and not OAuth-linkable here, so the linking lifecycle methods
raise ``NotSupported`` and trades are produced via :meth:`fetch_sheet`.

No sheet row shape escapes this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Tuple

from app.connectors.base import ConnectorCapabilities
from app.connectors.models import (
    NormalizedTrade,
    NotSupported,
    TradeAction,
)
from app.services.google_sheets_sync import GoogleSheetsService
from app.services.trade_ingestion import TradeValidator

SOURCE = "sheets"


def sheet_external_id(trade_date, symbol, quantity, price) -> str:
    """Stable external id for a sheet-sourced trade.

    Encodes the same ``(date, symbol, qty, price)`` identity the legacy daily
    sync deduped on (it routed through the single-sleeve CSV path), so re-runs
    stay idempotent and behavior is unchanged.
    """
    if isinstance(trade_date, str):
        d = datetime.strptime(trade_date, "%Y-%m-%d").date().isoformat()
    else:
        d = trade_date.isoformat()
    return f"sheets:{d}:{str(symbol).upper()}:{float(quantity)}:{float(price)}"


class SheetsConnector:
    """Produces normalized trades from a public Google Sheet."""

    capabilities = ConnectorCapabilities(
        can_read_positions=False,
        can_read_transactions=True,
        can_trade=False,
        supports_realtime=False,
        supports_historical_backfill=True,
        requires_manual_refresh=False,
        data_freshness="daily",
    )

    def __init__(self, sheets_service: GoogleSheetsService | None = None):
        self._sheets = sheets_service or GoogleSheetsService()

    def fetch_sheet(
        self, sheet_id: str, range_name: str = "Sheet1"
    ) -> Tuple[List[NormalizedTrade], List[str], int]:
        """Fetch a sheet and return ``(trades, errors, row_count)``.

        ``row_count`` is the raw number of rows fetched (the legacy
        ``sheet_rows`` value). Raises ``RuntimeError`` on fetch failure, matching
        ``GoogleSheetsService``.
        """
        rows = self._sheets.fetch_sheet_data(sheet_id, range_name)
        if not rows:
            return [], [], 0

        validator = TradeValidator()
        validation = validator.validate_batch(rows)

        trades: List[NormalizedTrade] = []
        for v in validation["trades"]:
            executed_at = datetime.strptime(v.trade_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            trades.append(
                NormalizedTrade(
                    external_id=sheet_external_id(
                        v.trade_date, v.symbol, v.quantity, v.price
                    ),
                    symbol=v.symbol,
                    action=TradeAction(v.action),
                    quantity=Decimal(str(v.quantity)),
                    price=Decimal(str(v.price)),
                    executed_at=executed_at,
                    commission=Decimal(str(v.commission)),
                    source=SOURCE,
                    strategy=v.strategy,
                    account=v.account,
                    notes=v.notes,
                    raw=v.model_dump(),
                )
            )
        return trades, validation["errors"], len(rows)

    # --- non-applicable Protocol methods (not OAuth-linkable here) ---------

    def initiate_link(self, client_id: str, redirect_uri: str):
        raise NotSupported("Sheets source is not OAuth-linkable")

    def complete_link(self, callback_payload: dict):
        raise NotSupported("Sheets source is not OAuth-linkable")

    def list_connections(self, client_id: str):
        return []

    def refresh_connection(self, connection_id: str):
        raise NotSupported("Sheets source is not OAuth-linkable")

    def remove_connection(self, connection_id: str) -> None:
        raise NotSupported("Sheets source is not OAuth-linkable")

    def fetch_accounts(self, connection_id: str):
        raise NotSupported("Sheets source does not expose accounts")

    def fetch_positions(self, connection_id: str, account_ref: str):
        raise NotSupported("Sheets source cannot read positions")

    def fetch_transactions(self, connection_id, account_ref, since=None, until=None):
        raise NotSupported("Sheets is pull-by-id; use fetch_sheet(sheet_id)")

    def place_order(self, connection_id, account_ref, order):
        raise NotSupported("Sheets source cannot trade")
