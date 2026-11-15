"""Runs the rules and applies the checks every finding goes through.

The checks are here, once, so no rule can forget them:

- a finding built on an account whose record is **incomplete** is dropped (a
  gap would read as a gain or a loss that never happened), except the rules
  that are about such a gap or a stopped login;
- a rule that fails never takes the rest down: it is logged and skipped;
- most pressing first, and a must-do (``must``) before anything else.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence

from app.services.insights.base import INSIGHT, NUDGE, Finding
from app.services.insights.context import Context
from app.services import market_pattern_copy
from app.services.insights.registry import RULES

logger = logging.getLogger(__name__)


class InsightService:
    def __init__(
        self,
        portal,
        narrowed: Callable[[Sequence[str]], object],
        today: Optional[date] = None,
        rules=None,
        market: Optional[Callable[[], Optional[Dict]]] = None,
    ):
        if market is None and getattr(portal, "db", None) is not None:
            db = portal.db
            market = lambda: market_pattern_copy.latest(db, today)  # noqa: E731
        self.ctx = Context(portal, narrowed, today, market)
        self.rules = RULES if rules is None else rules

    def findings(self) -> List[Finding]:
        held_back = {a["id"] for a in self.ctx.incomplete()}
        found: List[Finding] = []
        for rule in self.rules:
            try:
                produced = rule.find(self.ctx)
            except Exception:  # one rule's trouble must not blank the Dashboard
                logger.exception("Insight rule %s failed", rule.id)
                continue
            for finding in produced:
                if not rule.allow_incomplete and held_back.intersection(finding.account_ids):
                    continue
                found.append(finding)
        found.sort(key=lambda f: (not f.must, f.rank, f.key))
        return found

    def respond(self) -> Dict:
        found = self.findings()
        return {
            "nudges": [asdict(f) for f in found if f.tier == NUDGE],
            "insights": [asdict(f) for f in found if f.tier == INSIGHT],
        }
