"""Do two Plaid logins that see the same account describe its trades the same way?

When a person links their own login for an account another person's login already
feeds, a feed switch would only be safe if a trade carries the same id through both
logins (or can be matched by what it was). This reads, and changes nothing: for each
account the new login shares that an existing feed already covers, it asks Plaid for
the new login's recent investment trades and says how many match what is stored by
id, how many only by what they were (day, symbol, side, quantity, price), and how
many match neither.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.connectors import plaid_reader
from app.connectors.plaid_connector import PlaidClient, PlaidError
from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services.plaid_link_service import PlaidLinkService

CENT = Decimal("0.01")


def _key(day, symbol, action, quantity, price) -> tuple:
    return (day, symbol, str(action).upper(), round(float(abs(quantity)), 4), round(float(price), 2))


def compare(
    db: Session, connection: BrokerageConnection, days: int = 90,
    client: Optional[PlaidClient] = None, today: Optional[date] = None,
) -> List[Dict]:
    """One row per account the new login shares that an existing feed covers."""
    today = today or date.today()
    service = PlaidLinkService(db, client)
    found = service.found(connection.client_id, connection.id)
    token = service._access_token(connection)
    reader = service.client
    start = today - timedelta(days=days)
    report: List[Dict] = []
    investment = None
    for row in found["accounts"]:
        if not row.get("fed_by") or row.get("plaid_type") != "investment":
            continue
        link = db.get(BrokerageAccount, row["link_id"])
        feed = (
            db.query(BrokerageAccount)
            .filter(BrokerageAccount.account_id == row["account_id"], BrokerageAccount.status == "mapped")
            .first()
        )
        if feed is None:
            continue
        try:
            if investment is None:
                investment = reader.investment_transactions(token, start, today)
        except PlaidError as error:
            report.append({"name": row["name"], "mask": row["mask"], "error": error.message})
            continue
        securities = {s["security_id"]: s for s in investment.get("securities", [])}
        mine = [
            t for t in investment.get("investment_transactions", [])
            if t.get("account_id") == link.external_account_ref
        ]
        trades = plaid_reader.read_investment_transactions(mine, securities).trades
        stored = (
            db.query(Trade).join(Sleeve, Sleeve.id == Trade.sleeve_id)
            .filter(Sleeve.account_id == row["account_id"], Trade.trade_date >= start)
            .all()
        )
        stored_ids = {t.external_id for t in stored if t.external_id}
        stored_keys = {
            _key(t.trade_date, t.symbol, t.action, t.quantity, t.price) for t in stored
        }
        by_id = by_what = neither = 0
        for t in trades:
            if t.external_id in stored_ids:
                by_id += 1
            elif _key(t.executed_at.date(), t.symbol, t.action.value if hasattr(t.action, "value") else t.action,
                      t.quantity, t.price) in stored_keys:
                by_what += 1
            else:
                neither += 1
        report.append({
            "name": row["name"], "mask": row["mask"], "fed_by": row["fed_by"],
            "days": days, "new_login_trades": len(trades), "stored_trades": len(stored),
            "same_id": by_id, "same_trade_other_id": by_what, "not_on_file": neither,
        })
    return report  # nothing was written, so nothing is committed
