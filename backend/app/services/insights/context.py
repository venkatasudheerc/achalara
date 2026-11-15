"""What every rule reads, built once per request and read lazily.

A rule that needs no holdings never pays for them: ``home`` and the tax facts
are worked out on first use.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Dict, List, Optional, Sequence

from app.services.account_kind import CASH, CHECKING, INVESTED, SAVINGS, TAXABLE

CASH_LIKE = (CASH, CHECKING, SAVINGS)


class Context:
    def __init__(
        self,
        portal,
        narrowed: Callable[[Sequence[str]], object],
        today: Optional[date] = None,
        market: Optional[Callable[[], Optional[Dict]]] = None,
    ):
        self.portal = portal
        self._market_loader = market
        self._narrowed = narrowed
        self.today = today or date.today()
        self.accounts: List[Dict] = portal.accounts()
        self._connections: Optional[List[Dict]] = None
        self._home: Optional[Dict] = None
        self._tax: Optional[Dict] = None
        self._market: Optional[Dict] = None
        self._market_read = False

    # -- who and what is in view ---------------------------------------

    def of_kind(self, *kinds: str) -> List[Dict]:
        return [a for a in self.accounts if a["kind"] in kinds]

    @property
    def invested(self) -> List[Dict]:
        return self.of_kind(*INVESTED)

    @property
    def assets(self) -> float:
        return sum(a["value"] or 0 for a in self.accounts if not a["owed"])

    @property
    def owed(self) -> float:
        return -sum(a["value"] or 0 for a in self.accounts if a["owed"])

    @property
    def cash(self) -> float:
        """Cash held: in cash-like accounts, and as the custodian last reported
        it inside an invested one (a cash account's cash is its value, not both)."""
        total = 0.0
        for a in self.accounts:
            if a["kind"] in CASH_LIKE:
                total += a["value"] or 0
            elif a["kind"] in INVESTED:
                total += a["cash"] or 0
        return total

    def incomplete(self) -> List[Dict]:
        return [a for a in self.accounts if (a.get("health") or {}).get("state") == "incomplete"]

    # -- read on first use -----------------------------------------------

    @property
    def connections(self) -> List[Dict]:
        if self._connections is None:
            self._connections = self.portal.connections()["connections"]
        return self._connections

    @property
    def home(self) -> Dict:
        if self._home is None:
            self._home = self.portal.home()
        return self._home

    @property
    def market(self) -> Optional[Dict]:
        """The app's copy of the S&P 500's record for this week and month, when
        there is a fresh one. Market data itself is never read here."""
        if not self._market_read:
            self._market = self._market_loader() if self._market_loader else None
            self._market_read = True
        return self._market

    @property
    def tax(self) -> Dict:
        """Wash-sale losses and shares turning long-term, for taxable accounts
        only: a retirement account's lots are not taxed when sold."""
        if self._tax is None:
            ids = [a["id"] for a in self.of_kind(TAXABLE)]
            self._tax = (
                self._narrowed(ids).tax_facts(self.today)
                if ids
                else {"carried_losses": 0.0, "turning_long_term": []}
            )
        return self._tax


def name_of(account: Dict) -> str:
    """How a screen names an account: its own name and the last four."""
    base = account.get("display_name") or account["name"]
    last = account.get("number_last4")
    return f"{base} ··{last}" if last else base


def first_name(full: Optional[str]) -> str:
    return (full or "Someone").split()[0]


def money(n: float) -> str:
    return f"${abs(round(n)):,.0f}"


def day(d: date) -> str:
    return f"{d.day} {d:%b}"
