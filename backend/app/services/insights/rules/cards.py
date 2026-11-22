"""Credit cards: a payment due, an overdue card, how much of the limits is owed."""
from __future__ import annotations

from datetime import datetime
from typing import List

from app.services.account_kind import CHECKING, CREDIT_CARD
from app.services.insights.base import (
    INSIGHT, NUDGE, Finding, Rule, chip, countdown, meter, view,
)
from app.services.insights.context import Context, day, money, name_of

# A card's figures older than this are not acted on: the institution may have
# changed them since.
STALE_DAYS = 3
DUE_WITHIN_DAYS = 7


def _fresh(card, today) -> bool:
    as_of = card.get("as_of")
    if as_of is None:
        return False
    when = as_of.date() if isinstance(as_of, datetime) else as_of
    return (today - when).days <= STALE_DAYS


def _cards(ctx: Context):
    for a in ctx.of_kind(CREDIT_CARD):
        if a.get("card"):
            yield a, a["card"]


class CardOverdue(Rule):
    id = "card_overdue"

    def find(self, ctx: Context) -> List[Finding]:
        found = []
        for a, card in _cards(ctx):
            if not card.get("is_overdue") or not _fresh(card, ctx.today):
                continue
            minimum = card.get("minimum_payment")
            found.append(Finding(
                key=f"{self.id}:{a['id']}", rule=self.id, tier=NUDGE, rank=20,
                chip=chip("card"), when="as the institution reported",
                title=f"{name_of(a)} is overdue",
                detail=f"{money(a['value'] or 0)} owed" + (f", minimum {money(minimum)}." if minimum else "."),
                action=view("dashboard", f"account:{a['id']}", "See the card"),
                account_ids=[a["id"]],
            ))
        return found


class CardDueSoon(Rule):
    id = "card_due_soon"

    def find(self, ctx: Context) -> List[Finding]:
        checking = [a for a in ctx.of_kind(CHECKING)]
        found = []
        for a, card in _cards(ctx):
            due = card.get("next_payment_due_date")
            owed = -(a["value"] or 0)
            if due is None or owed <= 0 or card.get("is_overdue") or not _fresh(card, ctx.today):
                continue
            days = (due - ctx.today).days
            if not 0 <= days <= DUE_WITHIN_DAYS:
                continue
            minimum = card.get("minimum_payment")
            # What the due date asks for is the statement's balance, not what is
            # owed now (which also holds what was charged since). Said only when
            # the institution sends it; otherwise the figure is "owed now".
            statement = card.get("last_statement_balance")
            if statement is not None and statement > 0:
                line = f"{name_of(a)}: statement balance ${statement:,.2f}"
                line += f", minimum {money(minimum)}" if minimum else ""
                line += f". {money(owed)} owed now."
            else:
                line = f"{name_of(a)}: {money(owed)} owed now" + (f", minimum {money(minimum)}." if minimum else ".")
            if checking:
                line += f" The checking accounts here hold {money(sum(c['value'] or 0 for c in checking))}."
            when = "today" if days == 0 else "in 1 day" if days == 1 else f"in {days} days"
            found.append(Finding(
                key=f"{self.id}:{a['id']}:{due.isoformat()}", rule=self.id, tier=NUDGE,
                rank=30 + days, chip=chip("card"), when="as of today",
                title=f"A card payment is due {when}",
                visual=countdown(days, f"day{'s' if days != 1 else ''} · due {due:%a} {day(due)}"),
                detail=line,
                action=view("dashboard", f"account:{a['id']}", "See the card"),
                account_ids=[a["id"]] + [c["id"] for c in checking],
            ))
        return found


class CardsOwedOfLimits(Rule):
    id = "cards_owed_of_limits"

    def find(self, ctx: Context) -> List[Finding]:
        cards = [(a, c) for a, c in _cards(ctx) if (c.get("credit_limit") or 0) > 0]
        if not cards:
            return []
        owed = sum(max(-(a["value"] or 0), 0) for a, _ in cards)
        limits = sum(c["credit_limit"] for _, c in cards)
        over = sum(1 for a, c in cards if -(a["value"] or 0) > c["credit_limit"] / 2)
        n = len(cards)
        latest = max(c["as_of"].date() if isinstance(c["as_of"], datetime) else c["as_of"]
                     for _, c in cards if c.get("as_of")) if any(c.get("as_of") for _, c in cards) else None
        return [Finding(
            key=self.id, rule=self.id, tier=INSIGHT, rank=130, chip=chip("card"),
            title=f"You owe {owed / limits:.0%} of your card limits",
            visual=meter(owed, limits, f"{money(owed)} owed", f"of {money(limits)}", warn=owed / limits > 0.5),
            detail=f"{n} card{'s' if n != 1 else ''}. "
                   + ("None is past half its limit." if not over else f"{over} {'is' if over == 1 else 'are'} past half the limit."),
            foot=f"As the institutions reported on {day(latest)}" if latest else None,
            account_ids=[a["id"] for a, _ in cards],
        )]
