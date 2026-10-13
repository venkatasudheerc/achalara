"""Live prices for the securities on a screen, fetched together and briefly kept.

For showing a holding at the market's current price where the custodian's own
price is from its last refresh. Only the price comes from here: what is held
and what it cost stay the custodian's. Nothing is stored, and nothing in the
daily record or in any return reads these.

One request covers every symbol asked for. A quote is kept for a minute, so
moving between screens does not fetch again; a symbol the source does not know
is remembered for longer and left at the custodian's price.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from app.connectors.models import is_option_symbol
from app.services.webull_market_data import WebullMarketDataService

# How long a quote is served before it is fetched again.
QUOTE_TTL = timedelta(seconds=60)
# How long a symbol the source has no quote for is left alone.
UNKNOWN_TTL = timedelta(hours=1)


@dataclass(frozen=True)
class Quote:
    price: Decimal
    fetched_at: datetime  # when we asked the source, UTC
    # The last close before today, for the day's change; None when unknown.
    prev_close: Optional[Decimal] = None


_lock = threading.Lock()
_quotes: Dict[str, Quote] = {}
_unknown: Dict[str, datetime] = {}


def quotable(symbol: str) -> bool:
    """Whether the source can price it: not an option, not a name-only symbol."""
    return bool(symbol) and not symbol.startswith("~") and not is_option_symbol(symbol)


def _fetch(symbols: List[str]) -> Dict[str, object]:
    """Ask the source. The one place that reaches the network.

    Each value is ``(price, previous close)``, or the price alone.
    """
    return WebullMarketDataService().get_quotes(symbols)


def live_quotes(
    symbols: Iterable[str], now: Optional[datetime] = None
) -> Dict[str, Quote]:
    """Current prices for ``symbols``, for those the source can quote.

    A symbol missing from the result has no live price; the caller keeps
    whatever it had. Never raises: a source that is down or not configured
    gives an empty result.
    """
    now = now or datetime.now(timezone.utc)
    wanted = sorted({s for s in symbols if quotable(s)})
    with _lock:
        stale = [
            s
            for s in wanted
            if not (s in _quotes and now - _quotes[s].fetched_at < QUOTE_TTL)
            and not (s in _unknown and now - _unknown[s] < UNKNOWN_TTL)
        ]
    if stale:
        try:
            fetched = _fetch(stale)
        except Exception:  # noqa: BLE001 - a quote is a nicety, never a failure
            fetched = None
        if fetched is not None:
            with _lock:
                for symbol in stale:
                    found = fetched.get(symbol)
                    price, previous = (
                        found if isinstance(found, tuple) else (found, None)
                    )
                    if price is not None and price > 0:
                        _quotes[symbol] = Quote(
                            Decimal(str(price)),
                            now,
                            Decimal(str(previous)) if previous else None,
                        )
                        _unknown.pop(symbol, None)
                    else:
                        _unknown[symbol] = now
    with _lock:
        return {
            s: _quotes[s]
            for s in wanted
            if s in _quotes and now - _quotes[s].fetched_at < QUOTE_TTL
        }


def forget() -> None:
    """Drop everything kept. For tests."""
    with _lock:
        _quotes.clear()
        _unknown.clear()
