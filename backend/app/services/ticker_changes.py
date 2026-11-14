"""Ticker changes: recorded, proposed from the accounts' own records, and copied
from what market data saw.

A change is one row in ``perf.corporate_action`` (``RENAME``, with
``new_symbol``), read on calculation by ``corporate_actions.adjusted_trades``;
stored trades and holdings are never renamed. Three ways a row gets there:

- **Market data saw it happen** (``md.security_symbol_hist``: one security, a
  new ticker): copied each morning by ``copy_from_market_data``. Market data
  only knows changes made while it followed the security.
- **An account's own record shows it** (``proposals``): a symbol that cannot be
  worked back (it was sold or held under another ticker), no longer held, whose
  last trade comes before the first appearance of exactly one held symbol of the
  same company name (from the custodian's rows). Shown on System status for an
  admin to confirm; nothing changes until then.
- **By hand**: ``python -m app.cli add-ticker-change``.

Recording one rebuilds every account that traded or held either ticker.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Set

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.connectors.models import is_option_symbol
from app.models.brokerage_connection import BrokerageAccount, BrokerageActivity
from app.models.perf import CorporateAction, DailyHolding
from app.models.sleeve import Sleeve
from app.models.trade import Trade

logger = logging.getLogger(__name__)

_CANNOT_WORK_BACK = re.compile(r"^(?P<symbol>\S+) works back to -")


def _words(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def recorded(db: Session) -> Set[tuple]:
    """(old, new) of every ticker change on file."""
    return {
        (row.symbol, row.new_symbol)
        for row in db.query(CorporateAction).filter(CorporateAction.action_type == "RENAME")
    }


def record(db: Session, old: str, new: str, on: date, source: str) -> int:
    """Record that ``old`` trades as ``new`` from ``on``, and rebuild the accounts
    that traded or held either. Returns how many were rebuilt."""
    from app.services.performance_build_service import PerformanceBuildService

    old, new = old.strip().upper(), new.strip().upper()
    if not old or not new or old == new:
        raise ValueError("Give two different tickers.")
    row = (
        db.query(CorporateAction)
        .filter(
            CorporateAction.symbol == old,
            CorporateAction.action_type == "RENAME",
            CorporateAction.effective_date == on,
        )
        .first()
    )
    if row is None:
        row = CorporateAction(symbol=old, effective_date=on, action_type="RENAME",
                              ratio=Decimal(1), source=source)
        db.add(row)
    row.new_symbol = new
    db.commit()
    accounts = {
        account_id
        for (account_id,) in db.query(Sleeve.account_id)
        .join(Trade, Trade.sleeve_id == Sleeve.id)
        .filter(or_(Trade.symbol == old, Trade.symbol == new))
    } | {
        account_id
        for (account_id,) in db.query(DailyHolding.account_id)
        .filter(or_(DailyHolding.symbol == old, DailyHolding.symbol == new))
        .distinct()
    }
    for account_id in sorted(accounts):
        PerformanceBuildService(db).rebuild_account(account_id)
    logger.info("Ticker change %s -> %s from %s recorded (%s); %d account(s) rebuilt",
                old, new, on, source, len(accounts))
    return len(accounts)


def copy_from_market_data(db: Session) -> int:
    """Record each change market data saw that is not on file yet. Returns how many."""
    from app.md import read as md_read

    try:
        seen = md_read.ticker_changes(db)
    except md_read.MdUnavailable:
        logger.warning("Ticker changes: market data could not be read")
        return 0
    on_file = recorded(db)
    added = 0
    for change in seen:
        if (change.old, change.new) not in on_file:
            record(db, change.old, change.new, change.on, "market data")
            on_file.add((change.old, change.new))
            added += 1
    return added


def _names(db: Session, link_ids: List[str]) -> Dict[str, Set[str]]:
    """The company names the custodian's own rows give each symbol."""
    names: Dict[str, Set[str]] = defaultdict(set)
    for symbol, payload in db.query(BrokerageActivity.symbol, BrokerageActivity.payload).filter(
        BrokerageActivity.brokerage_account_id.in_(link_ids),
        BrokerageActivity.symbol.isnot(None),
    ):
        name = _words((payload or {}).get("name") if isinstance(payload, dict) else "")
        if name:
            names[symbol].add(name)
    return names


def _first_seen(db: Session, account_id: str, sleeve_ids: List[str], symbol: str) -> Optional[date]:
    from app.services.opening_position import NOT_OPENING

    days = [
        db.query(Trade.trade_date)
        .filter(Trade.sleeve_id.in_(sleeve_ids), Trade.symbol == symbol, NOT_OPENING)
        .order_by(Trade.trade_date)
        .limit(1)
        .scalar(),
        db.query(DailyHolding.as_of_date)
        .filter(DailyHolding.account_id == account_id, DailyHolding.symbol == symbol)
        .order_by(DailyHolding.as_of_date)
        .limit(1)
        .scalar(),
    ]
    return min((d for d in days if d is not None), default=None)


def proposals(db: Session) -> List[Dict]:
    """Likely ticker changes from the accounts' own records, not yet on file:
    ``old``, ``new``, ``on`` (the new ticker's first appearance), ``company`` and
    how many accounts show it. Each needs a person to confirm it."""
    from app.services.opening_position import NOT_OPENING

    on_file = {old for old, _ in recorded(db)}
    by_account: Dict[str, List[BrokerageAccount]] = defaultdict(list)
    for link in db.query(BrokerageAccount).filter(BrokerageAccount.account_id.isnot(None)):
        by_account[link.account_id].append(link)

    found: Dict[tuple, Dict] = {}
    for account_id, links in by_account.items():
        stuck = {
            match.group("symbol")
            for link in links
            for problem in (link.reconciliation or {}).get("opening_problems") or []
            for match in [_CANNOT_WORK_BACK.match(problem)]
            if match and not is_option_symbol(match.group("symbol"))
        } - on_file
        if not stuck:
            continue
        sleeve_ids = [s for (s,) in db.query(Sleeve.id).filter(Sleeve.account_id == account_id)]
        latest = (
            db.query(DailyHolding.as_of_date)
            .filter(DailyHolding.account_id == account_id)
            .order_by(DailyHolding.as_of_date.desc())
            .limit(1)
            .scalar()
        )
        held = {
            symbol
            for (symbol,) in db.query(DailyHolding.symbol).filter(
                DailyHolding.account_id == account_id, DailyHolding.as_of_date == latest
            )
            if not is_option_symbol(symbol)
        }
        names = _names(db, [link.id for link in links])
        for old in sorted(stuck - held):
            last_old = (
                db.query(Trade.trade_date)
                .filter(Trade.sleeve_id.in_(sleeve_ids), Trade.symbol == old, NOT_OPENING)
                .order_by(Trade.trade_date.desc())
                .limit(1)
                .scalar()
            )
            if last_old is None or not names.get(old):
                continue
            candidates = []
            for new in held - {old}:
                first_new = _first_seen(db, account_id, sleeve_ids, new)
                if first_new and first_new > last_old and names[old] & names.get(new, set()):
                    candidates.append((new, first_new))
            if len(candidates) != 1:
                continue  # none, or more than one company of that name: nothing guessed
            new, first_new = candidates[0]
            key = (old, new)
            entry = found.setdefault(key, {
                "old": old, "new": new, "on": first_new,
                "company": sorted(names[old] & names[new])[0].upper(), "accounts": 0,
            })
            entry["on"] = min(entry["on"], first_new)
            entry["accounts"] += 1
    return sorted(found.values(), key=lambda p: (p["old"], p["new"]))


def run_ticker_changes(db: Session) -> int:
    """The morning job: copy what market data saw."""
    return copy_from_market_data(db)
