"""A credit card's limits and what is due, read from Plaid and kept per account.

Balances give the limit and the available credit; liabilities give the cash
advance limit, the payment due and the last payment. Institutions fill these
differently, so every figure may be missing and none is guessed. A refusal of
liabilities (not offered, not ready) leaves the balance-based figures in place
and never fails a refresh.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.connectors.plaid_connector import PlaidError
from app.models.card_detail import CardDetail

logger = logging.getLogger(__name__)


def _money(value) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _day(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def credit_liabilities(client, token: str) -> Dict[str, Dict]:
    """Each card's liabilities by Plaid account id; empty when Plaid will not say."""
    try:
        reply = client.liabilities(token)
    except PlaidError as error:
        logger.info("Plaid gave no card liabilities (%s)", error.code)
        return {}
    return {
        row["account_id"]: row
        for row in (reply.get("liabilities") or {}).get("credit") or []
        if row.get("account_id")
    }


def read(account: Dict, liability: Optional[Dict]) -> Dict:
    """The card's figures from Plaid's account (limit, available) and its
    liability row, each None where Plaid did not send it."""
    balances = account.get("balances") or {}
    liability = liability or {}
    return {
        "credit_limit": _money(balances.get("limit")),
        "available_credit": _money(balances.get("available")),
        "cash_advance_limit": _money(liability.get("cash_advance_limit")),
        "minimum_payment": _money(liability.get("minimum_payment_amount")),
        "next_payment_due_date": _day(liability.get("next_payment_due_date")),
        "last_payment_amount": _money(liability.get("last_payment_amount")),
        "last_payment_date": _day(liability.get("last_payment_date")),
        "last_statement_balance": _money(liability.get("last_statement_balance")),
        "is_overdue": liability.get("is_overdue")
        if isinstance(liability.get("is_overdue"), bool)
        else None,
    }


def save(db: Session, account_id: str, values: Dict) -> None:
    """Replace the account's card details with the day's figures."""
    row = db.get(CardDetail, account_id)
    if row is None:
        row = CardDetail(account_id=account_id)
        db.add(row)
    for name, value in values.items():
        setattr(row, name, value)
    row.refreshed_at = datetime.now(timezone.utc)
