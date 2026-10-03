"""Webull market-data source, behind the connector interface.

Wraps the existing ``WebullMarketDataService`` (price fetch) and exposes prices
and positions as normalized types. Webull here is a market-data feed, not a
linked brokerage account: it reads prices for symbols we already hold, so the
account-linking lifecycle methods raise ``NotSupported``.

The Webull name and its SDK/auth stay sealed inside this module.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from app.connectors.base import ConnectorCapabilities
from app.connectors.models import (
    NormalizedPosition,
    NotSupported,
)
from app.services.webull_market_data import WebullMarketDataService

SOURCE = "webull"


class WebullConnector:
    """Reads live prices for held symbols and returns normalized positions."""

    capabilities = ConnectorCapabilities(
        can_read_positions=True,
        can_read_transactions=False,
        can_trade=False,
        supports_realtime=True,
        supports_historical_backfill=False,
        requires_manual_refresh=True,
        data_freshness="realtime",
    )

    def __init__(self, webull_service: WebullMarketDataService | None = None):
        self._webull = webull_service or WebullMarketDataService()

    def is_configured(self) -> bool:
        """Whether this source has credentials to make live calls.

        Keeps the vendor's key configuration sealed: callers ask this instead of
        reaching for ``app_key``/``app_secret``.
        """
        return bool(self._webull.app_key and self._webull.app_secret)

    def fetch_price_series(
        self, symbol: str, weeks: int = 260
    ) -> List[Tuple[date, float]]:
        """Weekly ``(date, close)`` points for a symbol, oldest first.

        A charting timeseries — distinct from holdings, so it isn't a
        ``NormalizedPosition``. The vendor bar shape and its quirks (most-recent
        first, varied field names) stay sealed here; callers get clean points.
        """
        bars = self._webull.get_historical_bars(symbol, timespan="W", count=weeks)
        if not bars:
            return []

        points: List[Tuple[date, float]] = []
        for bar in bars:
            if not isinstance(bar, dict):
                continue
            raw_date = bar.get("date") or bar.get("time") or bar.get("timestamp")
            raw_close = bar.get("close") or bar.get("vwap") or bar.get("open")
            if raw_date is None or raw_close is None:
                continue
            try:
                if isinstance(raw_date, str):
                    bar_date = date.fromisoformat(raw_date[:10])
                else:
                    bar_date = date.fromtimestamp(int(raw_date) / 1000)
                close_val = float(raw_close)
            except (ValueError, TypeError, OSError):
                continue
            points.append((bar_date, close_val))

        points.sort(key=lambda p: p[0])
        return points

    def get_price(self, symbol: str) -> Optional[Decimal]:
        """Current price for a symbol, or None if unavailable.

        The vendor strips any exchange prefix internally; callers pass the
        stored ticker (``BATS:IGE``) and get back a price in our currency.
        """
        price = self._webull.get_current_price(symbol)
        return Decimal(str(price)) if price is not None else None

    def get_prices(self, symbols: List[str]) -> Dict[str, Decimal]:
        """Fetch prices for many symbols; symbols with no quote are omitted."""
        out: Dict[str, Decimal] = {}
        for symbol in symbols:
            price = self.get_price(symbol)
            if price is not None:
                out[symbol] = price
        return out

    def fetch_positions_for_symbols(
        self, symbols: List[str]
    ) -> List[NormalizedPosition]:
        """Return price-only normalized positions for the given symbols.

        Webull provides quotes, not holdings, so ``quantity``/``avg_cost`` are
        zero and ``market_price`` carries the live quote. Upstream merges these
        with the holdings it already tracks.
        """
        as_of = datetime.now(timezone.utc)
        positions: List[NormalizedPosition] = []
        for symbol, price in self.get_prices(symbols).items():
            positions.append(
                NormalizedPosition(
                    symbol=symbol,
                    quantity=Decimal("0"),
                    avg_cost=Decimal("0"),
                    market_price=price,
                    as_of=as_of,
                )
            )
        return positions

    # --- non-applicable Protocol methods (market-data feed, not linkable) --

    def initiate_link(self, client_id: str, redirect_uri: str):
        raise NotSupported("Webull market-data feed is not account-linkable")

    def complete_link(self, callback_payload: dict):
        raise NotSupported("Webull market-data feed is not account-linkable")

    def list_connections(self, client_id: str):
        return []

    def refresh_connection(self, connection_id: str):
        raise NotSupported("Webull market-data feed is not account-linkable")

    def remove_connection(self, connection_id: str) -> None:
        raise NotSupported("Webull market-data feed is not account-linkable")

    def fetch_accounts(self, connection_id: str):
        raise NotSupported("Webull market-data feed does not expose accounts")

    def fetch_positions(self, connection_id: str, account_ref: str):
        raise NotSupported(
            "Webull is a quote feed; use fetch_positions_for_symbols(symbols)"
        )

    def fetch_transactions(self, connection_id, account_ref, since=None, until=None):
        raise NotSupported("Webull market-data feed has no transactions")

    def place_order(self, connection_id, account_ref, order):
        raise NotSupported("Webull market-data feed cannot trade")
