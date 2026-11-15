"""Facts about what is held. No action and no advice: what is on record."""
from __future__ import annotations

from typing import List

from app.services.insights.base import INSIGHT, Finding, Rule, chip, countdown, figure, meter
from app.services.insights.context import Context, day, money
from app.services.portal_service import CONCENTRATION_SHARE

LIVE = "At live prices"
LONG_TERM_WITHIN_DAYS = 60


def _ids(ctx: Context) -> List[str]:
    return [a["id"] for a in ctx.invested]


class Concentration(Rule):
    id = "concentration"

    def find(self, ctx: Context) -> List[Finding]:
        if not ctx.invested:
            return []
        home = ctx.home
        big = [h for h in home["concentrated"] if h["share"]]
        if not big:
            return []
        top = big[0]
        nxt = next((h for h in home["top_holdings"] if h["symbol"] != top["symbol"]), None)
        total = home["total_value"]
        return [Finding(
            key=f"{self.id}:{top['symbol']}", rule=self.id, tier=INSIGHT, rank=110,
            chip=chip("investments"),
            title=f"One holding, {top['symbol']}, is {top['share']:.0%} of what you hold",
            visual=meter(top["value"], total, f"{top['symbol']} {money(top['value'])}", f"of {money(total)}"),
            detail=f"The next largest is {nxt['share']:.0%}." if nxt and nxt["share"] else "",
            foot=LIVE, account_ids=_ids(ctx),
        )] if top["share"] >= CONCENTRATION_SHARE else []


class OptionsExpiring(Rule):
    id = "options_expiring"

    def find(self, ctx: Context) -> List[Finding]:
        if not ctx.invested:
            return []
        options = ctx.home["expiring_options"]
        if not options:
            return []
        rows = []
        for o in options:
            side = "written" if o["written"] else "bought"
            gap = o["above_strike_pct"]
            rows.append({
                "label": f"{o['underlying']} {o['strike']:g} {o['kind']} · {side} · {o['contracts']:g}",
                "value": "no live price" if gap is None
                else f"{abs(gap):.1%} {'above' if gap >= 0 else 'below'} strike",
            })
        n, first = len(options), options[0]["days"]
        return [Finding(
            key=self.id, rule=self.id, tier=INSIGHT, rank=140, chip=chip("options"),
            title=f"{n} option{'s' if n != 1 else ''} expire within two weeks",
            visual=countdown(first, f"day{'s' if first != 1 else ''} to the first", rows),
            detail="How far the shares are from each strike, at live prices.",
            foot=LIVE, account_ids=_ids(ctx),
        )]


class TurningLongTerm(Rule):
    id = "turning_long_term"

    def find(self, ctx: Context) -> List[Finding]:
        soon = [
            t for t in ctx.tax["turning_long_term"]
            if (t["date"] - ctx.today).days <= LONG_TERM_WITHIN_DAYS
        ]
        if not soon:
            return []
        first = soon[0]
        days = (first["date"] - ctx.today).days
        rest = soon[1:]
        return [Finding(
            key=f"{self.id}:{first['symbol']}", rule=self.id, tier=INSIGHT, rank=150,
            chip=chip("taxable"),
            title=f"{first['symbol']} shares turn long-term in {days} day{'s' if days != 1 else ''}",
            visual=countdown(days, f"day{'s' if days != 1 else ''} · on {day(first['date'])}",
                             [{"label": t["symbol"], "value": day(t["date"])} for t in rest]),
            detail="Shares held for a year are taxed as long-term when sold."
                   + (f" {len(rest)} more pass a year within {LONG_TERM_WITHIN_DAYS} days." if rest else ""),
            foot="From your trade history",
            account_ids=[a["id"] for a in ctx.of_kind("taxable")],
        )]


class CarriedLosses(Rule):
    id = "carried_losses"

    def find(self, ctx: Context) -> List[Finding]:
        lost = ctx.tax["carried_losses"]
        if lost < 1:
            return []
        return [Finding(
            key=self.id, rule=self.id, tier=INSIGHT, rank=160, chip=chip("taxable"),
            title="Losses not yet counted for tax",
            visual=figure(money(lost)),
            detail="Wash-sale losses sitting in the cost of shares you still hold. "
                   "They count when those shares are sold.",
            foot="From your trade history",
            account_ids=[a["id"] for a in ctx.of_kind("taxable")],
        )]
