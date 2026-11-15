"""A login that stopped sharing, a record with a gap, a consent running out,
accounts a login shares that were never added."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from app.services.insights.base import (
    NUDGE, Finding, Rule, chip, repair_login, update_from_file, view,
)
from app.services.insights.context import Context, day, first_name, name_of


class LoginNeedsSignIn(Rule):
    """An institution has stopped sharing: only the login's owner can fix it,
    so for anyone else it is something to know, not a must-do."""

    id = "login_needs_sign_in"
    allow_incomplete = True

    def find(self, ctx: Context) -> List[Finding]:
        found = []
        for login in ctx.connections:
            if login["state"] != "needs_sign_in" or not login["accounts"]:
                continue
            names = ", ".join(name_of(a) for a in login["accounts"])
            since = login["disabled_at"]
            stayed = f"stay as they were on {day(since)}" if since else "stay as they were"
            institution = login["institution"] or "Your institution"
            own = login["own"]
            who = first_name(login["owner_name"])
            found.append(Finding(
                key=f"{self.id}:{login['id']}", rule=self.id, tier=NUDGE, rank=10 if own else 45,
                chip=chip("connection"), must=own,
                title=f"{institution} has stopped sharing "
                      f"{len(login['accounts'])} account{'s' if len(login['accounts']) != 1 else ''}",
                detail=f"{names} {stayed} until "
                       + ("you sign in again." if own else f"{who} signs in to it."),
                when=f"since {day(since)}" if since else None,
                action=repair_login(login["id"]) if own else None,
                account_ids=[a["id"] for a in login["accounts"]],
            ))
        return found


class RecordIncomplete(Rule):
    """An account whose history is missing a transaction. Figures over time are
    held back for it; the owner is told how to repair it."""

    id = "record_incomplete"
    allow_incomplete = True

    def find(self, ctx: Context) -> List[Finding]:
        found = []
        for account in ctx.incomplete():
            health = account["health"]
            start = health.get("download_from")
            own = not account["shared"]
            if own:
                fix = (
                    f"Download its activity from {day(start)} to today, then use Update from a file."
                    if start else "Download all of its activity, then use Update from a file."
                )
            else:
                fix = f"{first_name(account['owner_name'])} can repair it."
            found.append(Finding(
                key=f"{self.id}:{account['id']}", rule=self.id, tier=NUDGE, rank=11,
                chip=chip("record"), must=own,
                title=f"{name_of(account)}'s record is missing a transaction",
                detail=f"{' '.join(health['reasons'])} {fix} "
                       "Figures over time are held back until then.",
                action=update_from_file(account["id"]) if own else None,
                account_ids=[account["id"]],
            ))
        return found


class ConsentEnding(Rule):
    """A login's consent runs out soon (the connection state says within 30 days)."""

    id = "consent_ending"
    allow_incomplete = True

    def find(self, ctx: Context) -> List[Finding]:
        found = []
        for login in ctx.connections:
            ends = login["consent_expires_at"]
            if login["state"] != "consent_ending" or not login["own"] or ends is None:
                continue
            days = max((ends - datetime.now(timezone.utc)).days, 0)
            institution = login["institution"] or "Your institution"
            found.append(Finding(
                key=f"{self.id}:{login['id']}", rule=self.id, tier=NUDGE, rank=40,
                chip=chip("connection"),
                title=f"{institution} will stop sharing on {day(ends)}",
                detail="Signing in again before then keeps its accounts updating.",
                when=f"in {days} day{'s' if days != 1 else ''}",
                action=repair_login(login["id"], "Renew sharing"),
                account_ids=[a["id"] for a in login["accounts"]],
            ))
        return found


class AccountsWaiting(Rule):
    """A login shares accounts the viewer has not added or left out yet."""

    id = "accounts_waiting"
    allow_incomplete = True

    def find(self, ctx: Context) -> List[Finding]:
        found = []
        for login in ctx.connections:
            n = login["waiting_accounts"]
            if not n or not login["own"]:
                continue
            institution = login["institution"] or "Your institution"
            found.append(Finding(
                key=f"{self.id}:{login['id']}", rule=self.id, tier=NUDGE, rank=50,
                chip=chip("connection"),
                title=f"{institution} has {n} account{'s' if n != 1 else ''} not added yet",
                detail="It came with your login. Nothing is added until you say so.",
                action=view("connections", None, "Review"),
            ))
        return found
