"""Yahoo's chart feed: an index's daily bars, as the app and market data both read it.

Free and unofficial. Used for index levels only (Webull serves no indices).
"""
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional

_HOST = "https://query1.finance.yahoo.com/v8/finance/chart/"
_PLACES = Decimal("0.0001")
FIELDS = ("open", "high", "low", "close", "volume")


def fetch(source_symbol: str, start: date) -> dict:
    """The source's daily series for one index from ``start``, as it answers."""
    since = datetime.combine(start, time(), tzinfo=timezone.utc)
    until = datetime.now(timezone.utc) + timedelta(days=2)
    query = urllib.parse.urlencode(
        {
            "period1": int(since.timestamp()),
            "period2": int(until.timestamp()),
            "interval": "1d",
        }
    )
    request = urllib.request.Request(
        f"{_HOST}{urllib.parse.quote(source_symbol)}?{query}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _level(value) -> Optional[Decimal]:
    if value is None or value <= 0:
        return None
    return Decimal(str(value)).quantize(_PLACES)


def bar(day: date, open_, high, low, close, volume) -> Optional[Dict]:
    """One day as it is stored, or None for a day with no close.

    A day whose open, high and low all equal its close was published as a
    close only, and keeps only the close.
    """
    values = {
        "open": _level(open_),
        "high": _level(high),
        "low": _level(low),
        "close": _level(close),
    }
    if values["close"] is None:
        return None
    close_only = (
        values["open"] is None
        or values["open"] == values["high"] == values["low"] == values["close"]
    )
    if close_only:
        values.update(open=None, high=None, low=None)
    return {"bar_date": day, **values, "volume": int(volume) if volume else None}


def parse_bars(payload: dict) -> List[Dict]:
    """The days in one answer from the source, oldest first."""
    results = (payload.get("chart") or {}).get("result") or []
    if not results:
        return []
    stamps = results[0].get("timestamp") or []
    quote = ((results[0].get("indicators") or {}).get("quote") or [{}])[0]

    def at(key: str, i: int):
        series = quote.get(key) or []
        return series[i] if i < len(series) else None

    bars = []
    for i, stamp in enumerate(stamps):
        # The stamp is the session's opening bell, the same day in UTC.
        day = (
            datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=stamp)
        ).date()
        row = bar(day, *(at(key, i) for key in FIELDS))
        if row is not None:
            bars.append(row)
    return bars
