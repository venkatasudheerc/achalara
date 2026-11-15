"""What the market has done in past years, set beside the cash the viewer holds."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Dict, List, Optional

from app.services.insights.base import INSIGHT, Finding, Rule, chip, record, view
from app.services.insights.context import Context, day
from app.services.insights.rules.cash import cash_over_share

# Fewer ended periods than this is not a record worth showing.
MIN_YEARS = 10


def _signed(n: float) -> str:
    return f"{'+' if n >= 0 else '−'}{abs(n):.1%}"


def _span(when: str, grain: str, pattern: Optional[Dict]) -> Optional[Dict]:
    if not pattern or len(pattern["years"]) < MIN_YEARS:
        return None
    n = len(pattern["years"])
    up = sum(1 for y in pattern["years"] if y["up"])
    return {
        "when": when,
        "said": f"Up in {up} of the last {n} years",
        "years": [y["up"] for y in pattern["years"]],
        "nums": f"Typical {grain} {_signed(pattern['median'])} · best {_signed(pattern['best'])}"
                f" · worst {_signed(pattern['worst'])}",
    }


def _week_when(today: date) -> str:
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)
    start = f"{monday.day}" if monday.month == friday.month else day(monday)
    return f"This week · {start} to {day(friday)}"


class CashAndMarket(Rule):
    """When cash is above a tenth of what is held, how the S&P 500 has gone in
    this week of the year and this month, in past years. Both ways: a month
    with a poor record says so as plainly. What happened, never what will."""

    id = "cash_and_market_pattern"

    def find(self, ctx: Context) -> List[Finding]:
        over = cash_over_share(ctx)
        market = ctx.market
        if over is None or not market:
            return []
        cash, assets = over
        today = ctx.today
        # The copy names the week and month it was made for: a stale one is not used.
        week = market["week"] if market["week_key"] == list(today.isocalendar()[:2]) else None
        month = market["month"] if market["month_key"] == [today.year, today.month] else None
        spans = [
            s for s in (
                _span(_week_when(today), "week", week),
                _span(f"This month · {calendar.month_name[today.month]}", "month", month),
            ) if s
        ]
        if not spans:
            return []
        lead = f"You hold {cash / assets:.0%} in cash."
        if month and len(month["years"]) >= MIN_YEARS:
            up = sum(1 for y in month["years"] if y["up"])
            n = len(month["years"])
            title = f"{lead} The S&P 500 rose in {up} of the last {n} {calendar.month_name[today.month]}s."
        else:
            up = sum(1 for y in week["years"] if y["up"])
            title = f"{lead} The S&P 500 rose in {up} of the last {len(week['years'])} years in this week."
        pattern = month or week
        latest = max((a["as_of"] for a in ctx.accounts if a.get("as_of")), default=None)
        return [Finding(
            key=self.id, rule=self.id, tier=INSIGHT, rank=100, chip=chip("markets"), wide=True,
            title=title, visual=record(spans),
            detail="Each square is one year, oldest first: green rose, clay fell. This is what "
                   "happened in past years, not what this year will do. Index level, dividends left out.",
            link=view("research", None, "See the pattern in Research"),
            foot=f"{market['name']}, {pattern['first_year']} to {pattern['last_year']}"
                 + (f" · your cash as of {day(latest)}" if latest else ""),
            account_ids=[a["id"] for a in ctx.accounts if not a["owed"]],
        )]
