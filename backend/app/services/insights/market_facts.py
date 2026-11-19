"""What the S&P 500 did in past years, in one plain sentence.

Shared by the cash nudge and the market tile so they never say different things.
It states what happened, never what will: no advice and no forecast.
"""
from __future__ import annotations

import calendar
from typing import Dict, Optional

from app.services.insights.context import Context

# Fewer ended periods than this is not a record worth showing.
MIN_YEARS = 10


def fresh_patterns(ctx: Context) -> Optional[Dict]:
    """The week's and the month's record, each only when the app's copy was made
    for this week or month (a stale copy is not used), or None."""
    market = ctx.market
    if not market:
        return None
    today = ctx.today
    return {
        "market": market,
        "week": market["week"] if market["week_key"] == list(today.isocalendar()[:2]) else None,
        "month": market["month"] if market["month_key"] == [today.year, today.month] else None,
    }


def rose_sentence(ctx: Context) -> Optional[str]:
    """"The S&P 500 rose in 15 of the last 20 Novembers.", else the week's, else None."""
    found = fresh_patterns(ctx)
    if not found:
        return None
    month, week = found["month"], found["week"]
    if month and len(month["years"]) >= MIN_YEARS:
        up = sum(1 for y in month["years"] if y["up"])
        return f"The S&P 500 rose in {up} of the last {len(month['years'])} {calendar.month_name[ctx.today.month]}s."
    if week and len(week["years"]) >= MIN_YEARS:
        up = sum(1 for y in week["years"] if y["up"])
        return f"The S&P 500 rose in {up} of the last {len(week['years'])} years in this week."
    return None
