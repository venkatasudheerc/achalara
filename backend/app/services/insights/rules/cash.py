"""Cash: how much of what the accounts hold is sitting in cash."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import List, Optional, Tuple

from app.models.perf import DailyValuation
from app.services.account_kind import INVESTED
from app.services.insights.base import NUDGE, Finding, Rule, chip, split, view
from app.services.insights.context import CASH_LIKE, Context, day, money, name_of
from app.services.insights.market_facts import rose_sentence

# Cash above this share of what the accounts in view hold is worth a mention
# (Sai, 2026-11-15: a share, not a dollar amount), and a few dollars never is.
CASH_SHARE = 0.10
MIN_CASH = 1000
# How far back the cash share is looked at, and how long it must have lasted to be said.
HISTORY_DAYS = 400
MIN_WEEKS = 2


def cash_over_share(ctx: Context):
    """``(cash, assets)`` when cash is above ``CASH_SHARE`` of what the accounts
    in view hold, else None. The one test, for the nudge and the market tile."""
    assets, cash = ctx.assets, ctx.cash
    if assets <= 0 or cash < MIN_CASH or cash / assets <= CASH_SHARE:
        return None
    return cash, assets


def cash_over_since(ctx: Context) -> Optional[Tuple[date, bool]]:
    """When cash last rose above ``CASH_SHARE`` of what the accounts in view hold
    and stayed there until now: ``(that day, whether it goes back past what is
    looked at)``, or None when it cannot be told (no daily record, or the daily
    record says it is not above). Read from the daily record, never guessed."""
    db = getattr(ctx.portal, "db", None)
    accounts = [a for a in ctx.accounts if not a["owed"]]
    if db is None or not accounts:
        return None
    kinds = {a["id"]: a["kind"] for a in accounts}
    by_day = defaultdict(dict)
    for account_id, on, cash, total in (
        db.query(DailyValuation.account_id, DailyValuation.as_of_date, DailyValuation.cash_value, DailyValuation.total_value)
        .filter(
            DailyValuation.account_id.in_(list(kinds)),
            DailyValuation.sleeve_id.is_(None),
            DailyValuation.as_of_date >= ctx.today - timedelta(days=HISTORY_DAYS),
        )
        .order_by(DailyValuation.as_of_date)
    ):
        total = float(total or 0)
        # A cash account's cash is its whole value, whether or not the row says so.
        held = float(cash) if cash is not None else (total if kinds[account_id] in CASH_LIKE else 0.0)
        by_day[on][account_id] = (held, total)
    # Each account's last known figure is carried on; a day counts once every account has begun.
    last: dict = {}
    shares: List[Tuple[date, float]] = []
    for on in sorted(by_day):
        last.update(by_day[on])
        if len(last) < len(kinds):
            continue
        total = sum(t for _, t in last.values())
        shares.append((on, sum(c for c, _ in last.values()) / total if total > 0 else 0.0))
    since: Optional[date] = None
    for on, share in reversed(shares):
        if share <= CASH_SHARE:
            break
        since = on
    if since is None:
        return None
    return since, since == shares[0][0]


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
        detail = f"Held in {len(holders)} account{'s' if len(holders) != 1 else ''}."
        if len(holders) > 1:
            biggest = max(holders, key=lambda a: (a["value"] if a["kind"] in CASH_LIKE else a["cash"]) or 0)
            detail += f" Most of it in {name_of(biggest)}."
        run = cash_over_since(ctx)
        if run:
            since, from_start = run
            days = (ctx.today - since).days
            if days >= 365:
                detail += " It has been over a tenth of what you own for more than a year."
            elif days >= MIN_WEEKS * 7 and from_start:
                # The daily record begins here, so it may have been longer.
                detail += f" It has been over a tenth of what you own for at least {days // 7} weeks."
            elif days >= MIN_WEEKS * 7:
                detail += f" It has been over a tenth of what you own since {day(since)}."
        record = rose_sentence(ctx)
        if record:
            detail += f" {record} That is what happened, not what will."
        # Where the cash is: the one account holding it, else the list of accounts.
        if len(holders) == 1 and holders[0]["kind"] in INVESTED:
            action = view("holdings", f"account:{holders[0]['id']}", "See holdings")
        elif len(holders) == 1:
            action = None  # a lone cash account has nothing more to open
        else:
            action = view("accounts", None, "See accounts")
        return [Finding(
            key=self.id, rule=self.id, tier=NUDGE, rank=60, chip=chip("cash"),
            when=f"as of {day(latest)}" if latest else None,
            title=f"{money(cash)} is in cash: {cash / assets:.0%} of what you own",
            visual=split([p for p in parts if p["value"] > 0]),
            detail=detail,
            action=action,
            # The share is measured against every asset, so each must be reliable.
            account_ids=[a["id"] for a in ctx.accounts if not a["owed"]],
        )]
