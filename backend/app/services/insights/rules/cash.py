"""Cash: how much of what the accounts hold is sitting in cash."""
from __future__ import annotations

from typing import List

from app.services.insights.base import NUDGE, Finding, Rule, chip, split, view
from app.services.insights.context import CASH_LIKE, Context, day, money

# Cash above this share of what the accounts in view hold is worth a mention
# (Sai, 2026-11-15: a share, not a dollar amount), and a few dollars never is.
CASH_SHARE = 0.10
MIN_CASH = 1000


def cash_over_share(ctx: Context):
    """``(cash, assets)`` when cash is above ``CASH_SHARE`` of what the accounts
    in view hold, else None. The one test, for the nudge and the market tile."""
    assets, cash = ctx.assets, ctx.cash
    if assets <= 0 or cash < MIN_CASH or cash / assets <= CASH_SHARE:
        return None
    return cash, assets


class IdleCash(Rule):
    id = "idle_cash"

    def find(self, ctx: Context) -> List[Finding]:
        over = cash_over_share(ctx)
        if over is None:
            return []
        cash, assets = over
        banks = sum(a["value"] or 0 for a in ctx.of_kind(*CASH_LIKE))
        at_brokers = cash - banks
        parts = [
            {"label": "Checking, savings and cash accounts", "value": banks},
            {"label": "Cash at brokerages", "value": at_brokers},
            {"label": "Invested", "value": assets - cash},
        ]
        latest = max((a["as_of"] for a in ctx.accounts if a.get("as_of")), default=None)
        holders = ctx.of_kind(*CASH_LIKE) + [a for a in ctx.invested if (a["cash"] or 0) > 0]
        return [Finding(
            key=self.id, rule=self.id, tier=NUDGE, rank=60, chip=chip("cash"),
            when=f"as of {day(latest)}" if latest else None,
            title=f"{money(cash)} is in cash: {cash / assets:.0%} of what you own",
            visual=split([p for p in parts if p["value"] > 0]),
            detail=f"Held in {len(holders)} account{'s' if len(holders) != 1 else ''}.",
            action=view("accounts", None, "See accounts"),
            # The share is measured against every asset, so each must be reliable.
            account_ids=[a["id"] for a in ctx.accounts if not a["owed"]],
        )]
