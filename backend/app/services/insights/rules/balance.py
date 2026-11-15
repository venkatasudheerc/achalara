"""Both sides of the balance sheet, when both are in view."""
from __future__ import annotations

from typing import List

from app.services.insights.base import INSIGHT, Finding, Rule, chip, split
from app.services.insights.context import Context, day, money

LABELS = {
    "credit_card": "Credit cards",
    "mortgage": "Mortgage",
    "car_loan": "Car loan",
    "loan": "Loans",
}


class AssetsAndOwed(Rule):
    id = "assets_and_owed"

    def find(self, ctx: Context) -> List[Finding]:
        assets, owed = ctx.assets, ctx.owed
        if assets <= 0 or owed <= 0:
            return []
        by_kind = {}
        for a in ctx.accounts:
            if a["owed"] and (a["value"] or 0) < 0:
                by_kind[a["kind"]] = by_kind.get(a["kind"], 0) - a["value"]
        parts = [{"label": LABELS.get(k, k), "value": v}
                 for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])]
        latest = max((a["as_of"] for a in ctx.accounts if a.get("as_of")), default=None)
        return [Finding(
            key=self.id, rule=self.id, tier=INSIGHT, rank=120, chip=chip("everything"),
            title=f"You owe {money(owed)}: {owed / assets:.0%} of the {money(assets)} you own",
            visual=split(parts),
            detail="Only the accounts linked here are counted.",
            foot=f"As of {day(latest)}" if latest else None,
            account_ids=[a["id"] for a in ctx.accounts],
        )]
