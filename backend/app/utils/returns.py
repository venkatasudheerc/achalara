"""Returns from daily closes: periods, seasonality and excess over a benchmark.

Pure functions, no database, shared by the app's portfolio figures and market
data, so both cut weeks and months the same way: ISO weeks (Monday to Sunday)
and calendar months, quarters and years. A period's return runs from the last
close before it to its own last close.
"""
from dataclasses import dataclass
from datetime import date
from statistics import mean, median, pstdev
from typing import Dict, Hashable, Iterable, List, Optional, Sequence, Tuple

GRAINS = ("day", "week", "month", "quarter", "year")
Close = Tuple[date, float]


def period_key(day: date, grain: str):
    """Which day, ISO week, month, quarter or year ``day`` belongs to."""
    if grain == "day":
        return day
    if grain == "week":
        iso = day.isocalendar()
        return (iso[0], iso[1])
    if grain == "month":
        return (day.year, day.month)
    if grain == "quarter":
        return (day.year, (day.month - 1) // 3 + 1)
    if grain == "year":
        return (day.year,)
    raise ValueError(f"grain must be one of {', '.join(GRAINS)}")


@dataclass(frozen=True)
class PeriodReturn:
    key: Hashable
    start: date  # first trading day in the period
    end: date  # last trading day in the period
    ret: float
    partial: bool  # the period has not ended yet


def period_returns(
    closes: Sequence[Close], grain: str, as_of: Optional[date] = None
) -> List[PeriodReturn]:
    """Each period's return, oldest first. The first period has no close before
    it and is left out; the period containing ``as_of`` is marked partial."""
    groups: List[List[Close]] = []
    current = None
    for day, close in sorted(closes):
        key = period_key(day, grain)
        if key != current:
            groups.append([])
            current = key
        groups[-1].append((day, close))
    running = period_key(as_of, grain) if as_of else None
    out = []
    for before, group in zip(groups, groups[1:]):
        previous, last = before[-1][1], group[-1][1]
        if not previous:
            continue
        key = period_key(group[0][0], grain)
        out.append(
            PeriodReturn(
                key, group[0][0], group[-1][0], last / previous - 1, key == running
            )
        )
    return out


@dataclass(frozen=True)
class DayReturn:
    day: date
    ret: float
    weekday: int  # 1 Monday … 5 Friday (ISO)
    trading_day_of_month: int  # 1 for the month's first trading day
    trading_days_left: int  # 0 on the month's last trading day on file


def day_returns(closes: Sequence[Close]) -> List[DayReturn]:
    """Each day's return from the previous close, with its place in its month.
    ``trading_days_left`` counts only days on file, so it is exact for months
    that have ended."""
    ordered = sorted(closes)
    by_month: Dict[Tuple[int, int], List[date]] = {}
    for day, _ in ordered:
        by_month.setdefault((day.year, day.month), []).append(day)
    out = []
    for (_, previous), (day, close) in zip(ordered, ordered[1:]):
        if not previous:
            continue
        month = by_month[(day.year, day.month)]
        place = month.index(day)
        out.append(
            DayReturn(
                day,
                close / previous - 1,
                day.isoweekday(),
                place + 1,
                len(month) - place - 1,
            )
        )
    return out


def turn_of_month(row: DayReturn) -> Optional[str]:
    """The last trading day and first three are the turn of the month. The first
    three are checked first: in a month still running, the latest day on file is
    not yet its last."""
    if row.trading_day_of_month <= 3:
        return f"day {row.trading_day_of_month}"
    if row.trading_days_left == 0:
        return "last day"
    return None


def summarise(values: Iterable[float]) -> Optional[Dict]:
    """Count, mean, median, share up, spread, best and worst of some returns."""
    values = list(values)
    if not values:
        return None
    return {
        "count": len(values),
        "mean": mean(values),
        "median": median(values),
        "share_up": sum(1 for v in values if v > 0) / len(values),
        "stdev": pstdev(values) if len(values) > 1 else 0.0,
        "best": max(values),
        "worst": min(values),
    }


def seasonality(rows: Iterable[Tuple[Hashable, float]]) -> Dict[Hashable, Dict]:
    """``(bucket, return)`` pairs summarised per bucket, in bucket order."""
    buckets: Dict[Hashable, List[float]] = {}
    for bucket, value in rows:
        buckets.setdefault(bucket, []).append(value)
    return {bucket: summarise(buckets[bucket]) for bucket in sorted(buckets, key=str)}


def excess(
    returns: Dict[Hashable, float], benchmark: Dict[Hashable, float]
) -> Dict[Hashable, float]:
    """Period by period, where both have a return."""
    return {
        key: ret - benchmark[key] for key, ret in returns.items() if key in benchmark
    }


def compound(returns: Iterable[float]) -> float:
    total = 1.0
    for ret in returns:
        total *= 1 + ret
    return total - 1
