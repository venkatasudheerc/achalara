"""CSV source, behind the connector interface.

Wraps the existing CSV parsing + ``TradeValidator`` and emits
``NormalizedTrade`` objects. CSV is push-based and not linkable: the linking
lifecycle methods raise ``NotSupported`` (callers branch on ``capabilities``),
and trades are produced via :meth:`parse_transactions` from uploaded bytes.

No CSV row shape escapes this module — upstream sees only normalized trades.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Tuple

from app.connectors.base import ConnectorCapabilities
from app.connectors.models import (
    NormalizedTrade,
    NotSupported,
    TradeAction,
)
from app.services.ingestion_service import csv_external_id
from app.services.trade_ingestion import TradeValidator

SOURCE = "csv"


class CSVConnector:
    """Produces normalized trades from an uploaded CSV file."""

    capabilities = ConnectorCapabilities(
        can_read_positions=False,
        can_read_transactions=True,
        can_trade=False,
        supports_realtime=False,
        supports_historical_backfill=True,
        requires_manual_refresh=True,
        data_freshness="manual",
    )

    def parse_transactions(
        self, file_content: bytes
    ) -> Tuple[List[NormalizedTrade], List[str], int]:
        """Parse CSV bytes into normalized trades, errors, and raw row count.

        Returns ``(trades, errors, row_count)`` so the caller preserves the
        legacy validation-error reporting and the raw row total. Routing hints
        (account/strategy/notes) ride along on each trade for the shared
        pipeline to resolve.
        """
        rows = self._parse_csv(file_content)
        validator = TradeValidator()
        validation = validator.validate_batch(rows)

        trades: List[NormalizedTrade] = []
        for v in validation["trades"]:
            executed_at = datetime.strptime(v.trade_date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            trades.append(
                NormalizedTrade(
                    external_id=csv_external_id(
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

    @staticmethod
    def _parse_csv(file_content: bytes) -> List[Dict]:
        try:
            content_str = file_content.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("File must be UTF-8 encoded CSV")
        try:
            reader = csv.DictReader(io.StringIO(content_str))
            if not reader.fieldnames:
                raise ValueError("CSV file is empty")
            return list(reader)
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Failed to parse CSV: {str(e)}")

    # --- non-applicable Protocol methods (not linkable) -------------------

    def initiate_link(self, client_id: str, redirect_uri: str):
        raise NotSupported("CSV source is not linkable")

    def complete_link(self, callback_payload: dict):
        raise NotSupported("CSV source is not linkable")

    def list_connections(self, client_id: str):
        return []

    def refresh_connection(self, connection_id: str):
        raise NotSupported("CSV source is not linkable")

    def remove_connection(self, connection_id: str) -> None:
        raise NotSupported("CSV source is not linkable")

    def fetch_accounts(self, connection_id: str):
        raise NotSupported("CSV source does not expose accounts")

    def fetch_positions(self, connection_id: str, account_ref: str):
        raise NotSupported("CSV source cannot read positions")

    def fetch_transactions(self, connection_id, account_ref, since=None, until=None):
        raise NotSupported("CSV is push-based; use parse_transactions(file_content)")

    def place_order(self, connection_id, account_ref, order):
        raise NotSupported("CSV source cannot trade")
