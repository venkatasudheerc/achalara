"""Cash ledger — an account's cash balance on any date.

A brokerage reports what cash an account holds now, and every activity it
sends carries the cash it moved. Walking those backwards from today's balance
gives the balance on any earlier date, with no need to know what the account
started with.

With cash known, an account can be measured as a whole: its value is
securities plus cash, a trade merely swaps one for the other, and the only
money that enters or leaves is a deposit, withdrawal or transfer. Accounts
without a reported balance (CSV, Sheets) are not tracked here and keep the
securities-only measure, where a BUY is money in and a SELL is money out.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.brokerage_connection import BrokerageAccount, BrokerageActivity
from app.models.sleeve import Sleeve


class CashLedger:
    """Cash balances and outside flows for a set of cash-tracked accounts."""

    def __init__(self, db: Session, brokerage_accounts: List[BrokerageAccount]):
        # Cash as the brokerage reports it now.
        self.reported = sum(
            (Decimal(str(a.cash_balance)) for a in brokerage_accounts), Decimal(0)
        )
        # Securities the brokerage holds that our trades do not yet show (or
        # the reverse), valued now. The reported cash has already paid for
        # them, but no stored activity records that payment.
        self.pending = sum(
            (
                Decimal(str((a.reconciliation or {}).get("holdings_adjustment", 0)))
                for a in brokerage_accounts
            ),
            Decimal(0),
        )
        # Walking back from the reported cash alone would carry that unrecorded
        # payment into every earlier date and understate them all. So the
        # unreported securities are held as if still cash: the balance then
        # matches the trades we do have, and the total is right throughout.
        self.anchor = self.reported + self.pending
        account_ids = [a.account_id for a in brokerage_accounts]
        # Trades in these sleeves swap cash for securities inside the account,
        # so they are not money in or out.
        self.sleeve_ids: Set[str] = {
            row[0]
            for row in db.query(Sleeve.id).filter(Sleeve.account_id.in_(account_ids))
        }

        self.changes: Dict[date, Decimal] = {}
        # Net deposits (+) and withdrawals (-) per day.
        self.external: Dict[date, Decimal] = {}
        rows = db.query(
            BrokerageActivity.activity_date,
            BrokerageActivity.cash_amount,
            BrokerageActivity.is_external_flow,
        ).filter(
            BrokerageActivity.brokerage_account_id.in_(
                [a.id for a in brokerage_accounts]
            ),
            BrokerageActivity.activity_date.isnot(None),
            BrokerageActivity.cash_amount.isnot(None),
        )
        for day, amount, is_external in rows:
            amount = Decimal(str(amount))
            if amount == 0:
                continue
            self.changes[day] = self.changes.get(day, Decimal(0)) + amount
            if is_external:
                self.external[day] = self.external.get(day, Decimal(0)) + amount

        # Suffix sums: everything that moved after a given date.
        self._dates = sorted(self.changes)
        self._after: List[Decimal] = [Decimal(0)] * (len(self._dates) + 1)
        for i in range(len(self._dates) - 1, -1, -1):
            self._after[i] = self._after[i + 1] + self.changes[self._dates[i]]

    @classmethod
    def for_accounts(
        cls, db: Session, account_ids: List[str]
    ) -> Optional["CashLedger"]:
        """A ledger over those of ``account_ids`` whose cash is known, or None."""
        if not account_ids:
            return None
        tracked = (
            db.query(BrokerageAccount)
            .filter(
                BrokerageAccount.account_id.in_(account_ids),
                BrokerageAccount.cash_balance.isnot(None),
            )
            .all()
        )
        return cls(db, tracked) if tracked else None

    def balance_on(self, day: date) -> Decimal:
        """Cash held at the close of ``day``, on the footing of the trades on
        file (so it includes ``pending``; see ``__init__``)."""
        return self.anchor - self._after[bisect_right(self._dates, day)]

    def change_dates(self, start: date, end: date) -> List[date]:
        """Dates within [start, end] on which the balance moved."""
        return [d for d in self._dates if start <= d <= end]
