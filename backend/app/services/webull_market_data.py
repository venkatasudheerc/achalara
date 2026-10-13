"""
Webull API Market Data Fetcher
Fetches real-time quotes and historical bars using HMAC-SHA1 authentication
"""
from decimal import Decimal
from typing import Optional, Dict, List
import time
import http.client
import json
import hashlib
import hmac
import base64
import uuid
import urllib.parse
from datetime import datetime, timezone
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class WebullMarketDataService:
    """Fetch market data from Webull API"""

    # API endpoints and configuration
    MARKET_HOST = "api.webull.com"
    TRADE_HOST = "api.webull.com"

    def __init__(self):
        """Initialize Webull API wrapper"""
        self.app_key = settings.webull_app_key
        self.app_secret = settings.webull_app_secret
        self.rate_limit_delay = 0.2  # 200ms between requests (300 req/min max)
        self.last_request_time = 0

        if not self.app_key or not self.app_secret:
            logger.warning("Webull API credentials not configured")

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """
        Strip an exchange prefix before calling Webull.

        Google Finance uses ``EXCHANGE:TICKER`` (e.g. ``BATS:IGE``, ``NASDAQ:AAPL``),
        but Webull expects the bare ticker. The exchange-prefixed form is kept on the
        stored trade/position; only the outbound API request is normalized.
        """
        if symbol and ":" in symbol:
            symbol = symbol.split(":")[-1]
        return (symbol or "").strip().upper()

    def _rate_limit(self):
        """Apply rate limiting (300 requests/minute = 200ms per request)"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()

    def _generate_signature(
        self,
        host: str,
        path: str,
        query_params: dict,
        body_string: Optional[str],
        timestamp: str,
        nonce: str,
    ) -> str:
        """Generate HMAC-SHA1 signature for Webull API authentication"""
        signing_headers = {
            "x-app-key": self.app_key,
            "x-timestamp": timestamp,
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": nonce,
            "host": host,
        }

        all_params = {**query_params, **signing_headers}
        str1 = "&".join(f"{k}={all_params[k]}" for k in sorted(all_params))

        if body_string:
            str2 = hashlib.md5(body_string.encode("utf-8")).hexdigest().upper()
            str3 = f"{path}&{str1}&{str2}"
        else:
            str3 = f"{path}&{str1}"

        encoded_string = urllib.parse.quote(str3, safe="")
        signing_key = f"{self.app_secret}&"

        signature = base64.b64encode(
            hmac.new(
                signing_key.encode("utf-8"),
                encoded_string.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")

        return signature

    def _build_headers(
        self,
        host: str,
        path: str,
        query_params: Optional[dict] = None,
        body_string: Optional[str] = None,
    ) -> dict:
        """Build HTTP headers with Webull API authentication"""
        query_params = query_params or {}
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = uuid.uuid4().hex
        signature = self._generate_signature(
            host, path, query_params, body_string, timestamp, nonce
        )

        return {
            "Accept": "application/json",
            "x-app-key": self.app_key,
            "x-timestamp": timestamp,
            "x-signature": signature,
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": nonce,
            "x-version": "v2",
        }

    def _get_snapshot(self, symbol: str) -> Optional[dict]:
        """
        Get snapshot (current market data) for a symbol

        Args:
            symbol: Stock symbol

        Returns:
            Raw API response dict or None if failed
        """
        try:
            path = "/openapi/market-data/stock/snapshot"
            query_params = {
                "symbols": self._normalize_symbol(symbol),
                "category": "US_STOCK",
                "extend_hour_required": "false",
                "overnight_required": "false",
            }

            headers = self._build_headers(
                self.MARKET_HOST, path, query_params=query_params
            )
            query_string = urllib.parse.urlencode(query_params)
            full_path = f"{path}?{query_string}"

            conn = http.client.HTTPSConnection(self.MARKET_HOST, timeout=10)
            conn.request("GET", full_path, None, headers)
            res = conn.getresponse()
            data = json.loads(res.read().decode("utf-8"))

            return data
        except Exception as e:
            logger.error(f"Failed to get snapshot for {symbol}: {e}")
            return None

    def _get_historical_bars(
        self, symbol: str, timespan: str = "D", count: int = 30
    ) -> Optional[list]:
        """
        Get historical bars (OHLCV data) for a symbol

        Args:
            symbol: Stock symbol
            timespan: Timeframe - M1, M5, M15, M30, M60, M120, M240, D, W, M, Y
            count: Number of bars to fetch (max 1200 for most, 1650 for M1)

        Returns:
            List of bar data dicts or None if failed
        """
        try:
            path = "/openapi/market-data/stock/bars"
            query_params = {
                "symbol": self._normalize_symbol(symbol),
                "category": "US_STOCK",
                "timespan": timespan,
                "count": str(count),
                "real_time_required": "true",
            }

            headers = self._build_headers(
                self.MARKET_HOST, path, query_params=query_params
            )
            full_path = f"{path}?{urllib.parse.urlencode(query_params)}"

            conn = http.client.HTTPSConnection(self.MARKET_HOST, timeout=10)
            conn.request("GET", full_path, None, headers)
            res = conn.getresponse()
            data = json.loads(res.read().decode("utf-8"))

            return data
        except Exception as e:
            logger.error(f"Failed to get historical bars for {symbol}: {e}")
            return None

    # Symbols per snapshot request. 50 is known to be accepted.
    QUOTE_BATCH = 50

    def get_quotes(self, symbols: List[str]) -> Dict[str, tuple]:
        """Current prices for many symbols, in as few requests as possible.

        Each is ``(price, previous close)``; the previous close is None when
        the source gives none.

        The source rejects a whole request when it does not know one of the
        symbols, and names the ones at fault. Those are dropped and the rest
        asked for again, so one unlisted security cannot blank the others.
        Symbols without a quote are simply absent from the result.
        """
        if not self.app_key or not self.app_secret:
            return {}
        wanted = sorted({self._normalize_symbol(s) for s in symbols if s})
        prices: Dict[str, tuple] = {}
        for start in range(0, len(wanted), self.QUOTE_BATCH):
            batch = wanted[start : start + self.QUOTE_BATCH]
            # Each retry removes at least one symbol, so this ends.
            for _ in range(len(batch)):
                if not batch:
                    break
                self._rate_limit()
                data = self._get_snapshots(batch)
                if isinstance(data, list):
                    for item in data:
                        try:
                            price = Decimal(str(item["price"]))
                        except (KeyError, TypeError, ArithmeticError):
                            continue
                        try:
                            previous = Decimal(str(item["pre_close"]))
                        except (KeyError, TypeError, ArithmeticError):
                            previous = None
                        prices[item["symbol"]] = (price, previous)
                    break
                rejected = self._rejected_symbols(data)
                if not rejected:
                    break  # some other failure: leave this batch unpriced
                batch = [s for s in batch if s not in rejected]
        return prices

    @staticmethod
    def _rejected_symbols(data) -> set:
        """The symbols an INVALID_SYMBOL reply names, e.g. ``... [ABC, XYZ].``"""
        if not isinstance(data, dict) or data.get("error_code") != "INVALID_SYMBOL":
            return set()
        message = str(data.get("message") or "")
        start, end = message.find("["), message.find("]")
        if start == -1 or end <= start:
            return set()
        return {
            part.strip() for part in message[start + 1 : end].split(",") if part.strip()
        }

    def _get_snapshots(self, symbols: List[str]):
        """One snapshot request for several symbols; the decoded reply, or None."""
        try:
            path = "/openapi/market-data/stock/snapshot"
            query_params = {
                "symbols": ",".join(symbols),
                "category": "US_STOCK",
                "extend_hour_required": "false",
                "overnight_required": "false",
            }
            headers = self._build_headers(
                self.MARKET_HOST, path, query_params=query_params
            )
            conn = http.client.HTTPSConnection(self.MARKET_HOST, timeout=10)
            conn.request(
                "GET", f"{path}?{urllib.parse.urlencode(query_params)}", None, headers
            )
            return json.loads(conn.getresponse().read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Failed to get snapshots for {len(symbols)} symbols: {e}")
            return None

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for a symbol

        Args:
            symbol: Stock symbol (e.g., "AAPL")

        Returns:
            Current price or None if failed
        """
        try:
            self._rate_limit()

            logger.debug(f"Fetching current price for {symbol}")

            # Fetch snapshot from Webull API
            data = self._get_snapshot(symbol=symbol)

            if data:
                price = self._parse_price(data)

                if price:
                    logger.debug(f"  {symbol}: ${price:.2f}")
                    return float(price)

            logger.warning(f"No price data for {symbol}")
            return None

        except Exception as e:
            logger.error(f"Failed to fetch price for {symbol}: {e}")
            return None

    def get_weekly_low(self, symbol: str, weeks: int = 2) -> Optional[float]:
        """
        Get the lowest price from the previous week

        Args:
            symbol: Stock symbol
            weeks: Number of bars to fetch (2 = current week + previous week)

        Returns:
            Previous week's low price or None if failed
        """
        try:
            self._rate_limit()

            logger.debug(f"Fetching weekly low for {symbol}")

            # Fetch 2 weeks: current week + previous week
            data = self._get_historical_bars(
                symbol=symbol, timespan="W", count=weeks  # Weekly
            )

            # Data is returned as a list, most recent first
            if isinstance(data, list) and len(data) >= 2:
                # data[0] = current/latest week
                # data[1] = previous week (what we need)
                prev_week_bar = data[1]

                if isinstance(prev_week_bar, dict) and "low" in prev_week_bar:
                    try:
                        prev_week_low = float(prev_week_bar["low"])
                        logger.debug(
                            f"  {symbol}: Previous week low = ${prev_week_low:.2f}"
                        )
                        return prev_week_low
                    except (ValueError, TypeError):
                        pass

                logger.warning(f"No low data in previous week bar for {symbol}")
                return None

            logger.warning(f"Insufficient historical data for {symbol} (need 2+ weeks)")
            return None

        except Exception as e:
            logger.error(f"Failed to fetch weekly low for {symbol}: {e}")
            return None

    def get_historical_bars(
        self, symbol: str, timespan: str = "W", count: int = 52
    ) -> Optional[List[Dict]]:
        """
        Get historical bars (OHLCV data)

        Args:
            symbol: Stock symbol
            timespan: "M1", "M5", "M15", "M30", "M60", "D", "W", "M", "Y"
            count: Number of bars to fetch

        Returns:
            List of bar data or None if failed
        """
        try:
            self._rate_limit()

            logger.debug(f"Fetching {count} {timespan} bars for {symbol}")

            data = self._get_historical_bars(
                symbol=symbol, timespan=timespan, count=count
            )

            # API returns list directly
            if isinstance(data, list):
                logger.debug(f"  {symbol}: Got {len(data)} bars")
                return data

            return None

        except Exception as e:
            logger.error(f"Failed to fetch bars for {symbol}: {e}")
            return None

    def get_market_data(self, symbol: str) -> Optional[Dict]:
        """
        Get comprehensive market data for a symbol

        Args:
            symbol: Stock symbol

        Returns:
            Dict with current_price and weekly_low or None
        """
        try:
            current_price = self.get_current_price(symbol)
            weekly_low = self.get_weekly_low(symbol)

            if current_price is not None and weekly_low is not None:
                return {
                    "symbol": symbol,
                    "current_price": current_price,
                    "weekly_low": weekly_low,
                    "timestamp": datetime.now().isoformat(),
                }

            return None

        except Exception as e:
            logger.error(f"Failed to get market data for {symbol}: {e}")
            return None

    def _parse_price(self, data) -> Optional[float]:
        """
        Parse price from Webull API response
        Handles multiple response formats
        """
        try:
            # Handle list response (array of snapshot objects)
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                if isinstance(item, dict) and "price" in item:
                    return float(item["price"])

            # Handle dict responses
            if isinstance(data, dict):
                # Try common response structures
                if (
                    "data" in data
                    and isinstance(data["data"], list)
                    and len(data["data"]) > 0
                ):
                    item = data["data"][0]
                    if isinstance(item, dict):
                        if "price" in item:
                            return float(item["price"])
                        elif "quote" in item and "last" in item["quote"]:
                            return float(item["quote"]["last"])
                elif "data" in data and isinstance(data["data"], dict):
                    if "quote" in data["data"] and "last" in data["data"]["quote"]:
                        return float(data["data"]["quote"]["last"])
                elif "last" in data:
                    return float(data.get("last"))
                elif "price" in data:
                    return float(data["price"])

            return None
        except Exception as e:
            logger.debug(f"Price parsing error: {e}")
            return None
