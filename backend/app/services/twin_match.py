"""When one row of a feed is several rows of a custodian's file added together.

A plan reports each contribution once per source (pre-tax, employer match,
after-tax …) in its own file; the feed sends one row for the day's purchase of a
fund. The feed's quantity is rounded to three places, the file's parts are not.
So a feed row is the same transaction as the file rows that add up to it, at the
same price, on the same day or within two weekdays.
"""
from datetime import timedelta
from decimal import Decimal
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.corporate_actions import current_symbol
from app.utils.symbols import app_symbol

# The feed rounds a quantity to three places; each part may be a little off too.
QUANTITY_TOLERANCE = Decimal("0.0015")
PRICE_TOLERANCE = Decimal("0.01")
WEEKDAYS = 2
# A plan has a handful of sources; more rows than this is not one purchase.
MAX_ROWS = 6
# The nearest rows are tried; a day holds a few per fund.
MAX_CANDIDATES = 14


def read_as(symbol: str, day, changes: Optional[Dict] = None) -> str:
    """The symbol a trade of ``symbol`` on ``day`` is read under: today's, after
    any ticker change (a file's rows under an old name, the feed's under the new)."""
    if changes:
        symbol = current_symbol(symbol, day, changes)[0]
    return app_symbol(symbol)


def weekdays_apart(a, b) -> int:
    low, high = (a, b) if a <= b else (b, a)
    days, apart = low, 0
    while days < high:
        days += timedelta(days=1)
        if days.weekday() < 5:
            apart += 1
    return apart


# A candidate: (what it is, quantity, price, day).
Candidate = Tuple[Any, Decimal, Decimal, Any]


def sum_to(
    quantity: Decimal, price: Decimal, day, candidates: Sequence[Candidate]
) -> Optional[List[Any]]:
    """The fewest candidates (two or more) whose quantities add up to
    ``quantity``, each priced within a cent and within two weekdays of ``day``:
    what they are, or None. Nearest rows are preferred."""
    near = [
        c for c in candidates
        if abs(Decimal(str(c[2])) - price) <= PRICE_TOLERANCE and weekdays_apart(c[3], day) <= WEEKDAYS
    ]
    near.sort(key=lambda c: (abs((c[3] - day).days), abs(Decimal(str(c[2])) - price)))
    near = near[:MAX_CANDIDATES]
    target = Decimal(str(quantity))
    for size in range(2, min(MAX_ROWS, len(near)) + 1):
        for chosen in combinations(near, size):
            if abs(sum((Decimal(str(c[1])) for c in chosen), Decimal(0)) - target) <= QUANTITY_TOLERANCE:
                return [c[0] for c in chosen]
    return None
