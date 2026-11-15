"""Bring the LOCAL database up to date from Plaid, for comparison with production.

An experiment, not part of the app. It reads the Plaid responses saved by
plaid_probe.py (docs/plaid-probe/production/<login>/), turns each account's
activity after its last SnapTrade day into the app's trades and cash rows, and
hands them to the same steps a SnapTrade sync uses (routing to strategies,
duplicate checks, corporate actions, the daily rebuild). Every row it writes is
marked as Plaid's: trades and cash rows carry an external id starting "plaid:",
and the raw rows are stored with source ids starting "plaid:".

    python scripts/plaid_backfill.py [login]          # dry run: what would be written
    python scripts/plaid_backfill.py [login] --apply  # write it

Rules (from the comparison of 2026-11-08, docs/plaid-probe/REPORT.md):
- Plaid dates a trade by its settlement; a buy or sell is moved back one weekday.
  Reinvestments, assignments and expiries keep Plaid's date.
- Option contracts are read from Plaid's option fields, or from their names
  ("Put Nike Inc Class B $33 Exp 10/09/26"); the company becomes a ticker through
  Plaid's own securities and the option trades already on file. One that cannot
  be read is skipped and counted.
- Rows are read as the SnapTrade rows were: sweeps and money-market reinvestments
  skipped; "Transfer (incoming/outgoing)", "Funds Received" and "Withdrawal" are
  money in and out of the account.
"""
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.connectors.models import (  # noqa: E402
    ActivityBatch,
    NormalizedPosition,
    NormalizedCashActivity,
    NormalizedTrade,
    RawActivity,
)
from app.db.database import SessionLocal  # noqa: E402
from app.models.brokerage_connection import BrokerageAccount  # noqa: E402
from app.models.sleeve import Sleeve  # noqa: E402
from app.models.trade import Trade  # noqa: E402
from app.services.connection_service import ConnectionService  # noqa: E402
from app.services.daily_capture_service import DailyCaptureService  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SWEEP_FUNDS = {"VMFXX"}
SECURITY_TYPES = {"equity": "STOCK", "etf": "ETF", "mutual fund": "MUTUAL_FUND", "derivative": "OPTION"}
OPTION_NAME = re.compile(r"^(Put|Call) (.+?) \$([\d.]+) Exp (\d\d)/(\d\d)/(\d\d)", re.I)


def previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def words(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower())


class Reader:
    def __init__(self, db, securities):
        self.sec = securities
        # Company name -> ticker, from Plaid's own stocks and funds ...
        self.tickers = {
            words(s["name"]): s["ticker_symbol"]
            for s in securities.values()
            if s.get("ticker_symbol") and s.get("type") in ("equity", "etf") and s.get("name")
        }
        # ... and from option trades already on file ("PUT NIKE INC CLASS B $33 ..." -> NKE).
        for symbol, notes in db.query(Trade.symbol, Trade.notes).filter(Trade.security_type == "OPTION"):
            m = OPTION_NAME.match(re.sub(r"\s+", " ", re.sub(r"^(Assignment|Expired): ", "", notes or "")))
            root = re.match(r"^([A-Z.]+?)\d{6}[CP]\d{8}$", symbol or "")
            if m and root:
                self.tickers.setdefault(words(m.group(2)), root.group(1))

    def ticker_for(self, company: str):
        key = words(company)
        if key in self.tickers:
            return self.tickers[key]
        for name, ticker in self.tickers.items():
            if name.startswith(key) or key.startswith(name):
                return ticker
        return None

    def option_symbol(self, s):
        oc = s.get("option_contract")
        if oc and oc.get("underlying_security_ticker"):
            ticker, kind = oc["underlying_security_ticker"], oc["contract_type"][0].upper()
            strike = Decimal(str(oc["strike_price"]))
            y, mo, d = str(oc["expiration_date"])[:10].split("-")
            stamp = y[2:] + mo + d
        else:
            m = OPTION_NAME.match(s.get("name") or "")
            if not m:
                return None
            ticker = self.ticker_for(m.group(2))
            if not ticker:
                return None
            kind, strike = m.group(1)[0].upper(), Decimal(m.group(3))
            stamp = m.group(6) + m.group(4) + m.group(5)
        return f"{ticker.replace('.', ' ') if ' ' in ticker else ticker}{stamp}{kind}{int(strike * 1000):08d}"


def read_account(reader, rows, cutoff, account_ref):
    """The batch for one account: rows dated after ``cutoff``, as the SnapTrade rows were read."""
    trades, cash, raw, skipped = [], [], [], Counter()
    for t in sorted(rows, key=lambda r: str(r["date"])):
        s = reader.sec.get(t["security_id"], {})
        kind, sub, name = t["type"], t["subtype"], t.get("name") or ""
        ticker = s.get("ticker_symbol")
        posted = date.fromisoformat(str(t["date"])[:10])
        holder = -Decimal(str(t["amount"]))  # Plaid: positive is money out of the account
        option = s.get("type") == "derivative"
        reinvest = name.startswith("Reinvestment")
        day = previous_weekday(posted) if kind in ("buy", "sell") and not reinvest else posted
        if day <= cutoff:
            continue
        ext = f"plaid:{t['investment_transaction_id']}"
        outcome, external = "skipped:unrecognized", False

        if kind in ("buy", "sell") and (ticker in SWEEP_FUNDS or (reinvest and s.get("type") == "cash")):
            outcome = "skipped:sweep"
        elif kind in ("buy", "sell") or (kind == "transfer" and sub in ("assignment", "expire")):
            qty = abs(Decimal(str(t["quantity"])))
            symbol = reader.option_symbol(s) if option else ticker
            if not symbol or qty == 0:
                outcome = "skipped:unreadable"
            else:
                if kind == "transfer":
                    action = "BUY" if Decimal(str(t["quantity"])) > 0 else "SELL"
                    price, notes = Decimal(0), f"{'Assignment' if sub == 'assignment' else 'Expired'}: {s.get('name', '')}"
                else:
                    action = "BUY" if kind == "buy" else "SELL"
                    price = Decimal(str(t["price"])) * (100 if option else 1)
                    notes = f"Dividend reinvestment: {s.get('name', '')}" if reinvest else s.get("name", "")
                trades.append(NormalizedTrade(
                    external_id=ext, symbol=symbol, action=action, quantity=qty, price=price,
                    executed_at=at(day), commission=Decimal(str(t.get("fees") or 0)), source="plaid",
                    security_type=SECURITY_TYPES.get(s.get("type"), "OTHER"), notes=notes, raw=t,
                ))
                outcome = "trade"
        else:
            cash_type = None
            if name.startswith(("Sweep in", "Sweep out")):
                outcome = "skipped:sweep"
            elif name.startswith("Transfer ("):
                cash_type, external = "TRANSFER", True
            elif name.startswith("Funds Received"):
                cash_type, external = "CONTRIBUTION", True
            elif name.startswith("Withdrawal") and kind == "cash":
                cash_type, external = "WITHDRAWAL", True
            elif sub == "dividend":
                cash_type = "DIVIDEND"
            elif sub == "interest" and kind == "cash":
                cash_type = "INTEREST"
            elif name.startswith("Interest charge"):
                cash_type = "MARGIN_INTEREST"
            elif name.startswith("Withholding"):
                cash_type = "WITHHOLDING"
            elif kind == "fee":
                cash_type = "FEE"
            elif "Cash in Lieu" in name:
                cash_type = "OTHER"
            if cash_type:
                cash.append(NormalizedCashActivity(
                    external_id=ext, type=cash_type, amount=holder, occurred_at=at(day),
                    symbol=None if ticker in (None, "CUR:USD") else ticker, source="plaid", notes=name, raw=t,
                ))
                outcome = "cash"
        if outcome.startswith("skipped"):
            skipped[outcome.split(":")[1]] += 1
        raw.append(RawActivity(
            source_id=ext, type=f"PLAID {kind}/{sub}".upper(), occurred_on=day, symbol=ticker,
            outcome=outcome, cash_amount=holder if outcome == "cash" else Decimal(0),
            is_external_flow=external, payload=t,
        ))
    # Vanguard moves cash within the account as a "Transfer (incoming)" and a
    # "Transfer (outgoing)" of the same amount on the same day: no money arrives or
    # leaves, so the pair is neither activity nor a flow.
    internal = set()
    for c in cash:
        if c.type != "TRANSFER" or c.external_id in internal or c.amount <= 0:
            continue
        twin = next((o for o in cash if o.type == "TRANSFER" and o.external_id not in internal
                     and o.occurred_at == c.occurred_at and o.amount == -c.amount), None)
        if twin is not None:
            internal |= {c.external_id, twin.external_id}
    if internal:
        cash = [c for c in cash if c.external_id not in internal]
        for r in raw:
            if r.source_id in internal:
                r.outcome, r.cash_amount, r.is_external_flow = "skipped:internal", Decimal(0), False
        skipped["internal"] += len(internal)
    return ActivityBatch(trades=trades, cash=cash, raw=raw, skipped=dict(skipped), security_type_sources={})


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    folder = REPO / "docs" / "plaid-probe" / "production" / (args[0] if args else "mine")
    accounts = json.load(open(folder / "accounts.json"))["accounts"]
    holdings = json.load(open(folder / "holdings.json"))
    activity = json.load(open(folder / "investment_transactions.json"))
    securities = {s["security_id"]: s for s in holdings["securities"] + activity["securities"]}

    db = SessionLocal()
    reader = Reader(db, securities)
    service = ConnectionService(db, connector=object())
    links = db.query(BrokerageAccount).filter(BrokerageAccount.account_id.isnot(None)).all()

    for plaid in accounts:
        ba = next((b for b in links if b.name.rstrip().endswith(plaid["mask"]) or (b.account and (b.account.account_number or "").endswith(plaid["mask"]))), None)
        label = f"{plaid['subtype']} ··{plaid['mask']}"
        if ba is None or not ba.default_sleeve_id:
            print(f"{label}: not in Achalara, left alone")
            continue
        cutoff = ba.transactions_synced_through or date.min
        rows = [t for t in activity["investment_transactions"] if t["account_id"] == plaid["account_id"]]
        batch = read_account(reader, rows, cutoff, plaid["account_id"])
        held = [h for h in holdings["holdings"] if h["account_id"] == plaid["account_id"]]
        # Cash: the cash holding where Plaid lists one (the sweep fund); otherwise the
        # account's total less what it holds (a bank-style account, or cash borrowed).
        listed = [Decimal(str(h.get("institution_value") or 0)) for h in held if securities[h["security_id"]].get("type") == "cash"]
        others = sum(Decimal(str(h.get("institution_value") or 0)) for h in held if securities[h["security_id"]].get("type") != "cash")
        total = Decimal(str(plaid["balances"].get("current") or 0))
        # A listed cash holding of zero is no figure at all (a margin account lists one).
        cash_now = sum(listed) if any(listed) else total - others
        print(f"{label}: after {cutoff}: {len(batch.trades)} trades, {len(batch.cash)} cash rows, skipped {batch.skipped}; Plaid's cash now {cash_now:,.2f}")
        if not apply:
            continue
        result = {"imported": 0, "duplicates": 0, "cash_imported": 0}
        service._store_raw(ba, batch.raw)
        service._ingest(ba, batch, result)
        ba.cash_balance = cash_now
        ba.cash_balance_at = datetime.now(timezone.utc)
        last = max((r.occurred_on for r in batch.raw if r.occurred_on), default=None)
        if last:
            ba.transactions_synced_through = last
        db.commit()
        service._after_trades_changed(ba)
        print(f"   written: {result['imported']} trades ({result['duplicates']} already on file), {result['cash_imported']} cash rows; daily record rebuilt")
        if "--capture" in sys.argv:
            capture_today(db, service, ba, plaid, held, securities, cash_now)
    if not apply:
        print("\nDry run. Add --apply to write.")


class _PlaidFeed:
    """Plaid's figures for one account, in the shape the daily capture reads."""

    def __init__(self, positions, cash):
        self.positions, self.cash = positions, cash

    def fetch_positions(self, user_id, ref):
        return self.positions

    def fetch_cash_balance(self, user_id, ref):
        return self.cash


def capture_today(db, service, ba, plaid, held, securities, cash_now):
    """Record the day Plaid's holdings are priced at as an observed day, as the
    SnapTrade capture does: holdings (options left out, as SnapTrade's feed leaves
    them), cash, and the account's total; options are what the total holds beyond."""
    # Vanguard's holding prices reach Plaid a day late (the previous close, though
    # dated today), and the balance is worked from them. The security's own
    # close_price is the custodian's figure for its date, so each holding is valued
    # at that where Plaid has one, and the total moves by the same amount.
    positions, priced_at, moved = [], [], Decimal(0)
    for h in held:
        s = securities[h["security_id"]]
        if s.get("type") == "cash":
            continue
        qty = Decimal(str(h["quantity"]))
        price = Decimal(str(h["institution_price"]))
        if s.get("close_price") is not None and s.get("close_price_as_of"):
            close = Decimal(str(s["close_price"]))
            value = Decimal(str(h["institution_value"]))
            per_unit = value / (qty * price) if qty and price else Decimal(1)  # 100 for an option
            moved += (qty * close * per_unit).quantize(Decimal("0.01")) - value
            price = close
            if s.get("type") != "derivative":
                priced_at.append(str(s["close_price_as_of"])[:10])
        if s.get("type") == "derivative" or not s.get("ticker_symbol"):
            continue
        cost = Decimal(str(h["cost_basis"])) / qty if h.get("cost_basis") is not None and qty else Decimal(0)
        positions.append(NormalizedPosition(
            symbol=s["ticker_symbol"], quantity=qty, avg_cost=cost, market_price=price,
            security_type=SECURITY_TYPES.get(s.get("type"), "OTHER"),
        ))
    day = date.fromisoformat(max(priced_at)) if priced_at else None
    total = Decimal(str(plaid["balances"].get("current") or 0)) + moved
    service.connector = _PlaidFeed(positions, cash_now)
    service._remote_account = lambda user_id, ref: type("Remote", (), {"total_value": total})()
    captured = DailyCaptureService(db, service).capture(ba.id, as_of=day)
    print(f"   observed {captured['as_of_date']}: total {captured['total_value']:,.2f}, cash {captured['cash_value']:,.2f}, {captured['holdings']} holdings")


if __name__ == "__main__" and "--bank" not in sys.argv:
    main()


BANK_TYPES = {"Withdrawal": ("WITHDRAWAL", True), "Funds Received": ("CONTRIBUTION", True),
              "Interest": ("INTEREST", False), "Transfer (incoming)": ("TRANSFER", True),
              "Transfer (outgoing)": ("TRANSFER", True)}


def bank(login="mine"):
    """Bank-style accounts (Cash Plus): Plaid's Transactions rows after the last SnapTrade day,
    read as the SnapTrade rows were. Sweeps and the reinvestment of interest are skipped."""
    folder = REPO / "docs" / "plaid-probe" / "production" / login
    accounts = json.load(open(folder / "accounts.json"))["accounts"]
    rows = json.load(open(folder / "bank_transactions.json"))["added"]
    db = SessionLocal()
    service = ConnectionService(db, connector=object())
    links = db.query(BrokerageAccount).filter(BrokerageAccount.account_id.isnot(None)).all()
    for plaid in accounts:
        mine = [t for t in rows if t["account_id"] == plaid["account_id"] and not t.get("pending")]
        if not mine:
            continue
        ba = next((b for b in links if b.name.rstrip().endswith(plaid["mask"])), None)
        if ba is None:
            continue
        cutoff = ba.transactions_synced_through or date.min
        cash, raw, skipped = [], [], Counter()
        for t in sorted(mine, key=lambda t: str(t["date"])):
            day = date.fromisoformat(str(t["date"])[:10])
            if day <= cutoff:
                continue
            ext = f"plaid:{t['transaction_id']}"
            name = t.get("name") or ""
            kind = BANK_TYPES.get(name)
            amount = -Decimal(str(t["amount"]))  # Plaid: positive is money out
            if kind:
                cash.append(NormalizedCashActivity(external_id=ext, type=kind[0], amount=amount,
                                                   occurred_at=at(day), source="plaid", notes=name, raw=t))
            else:
                skipped["sweep" if name.startswith(("Sweep", "Reinvestment")) else "unrecognized"] += 1
            raw.append(RawActivity(source_id=ext, type=f"PLAID BANK {name}".upper(), occurred_on=day,
                                   outcome="cash" if kind else "skipped:sweep", cash_amount=amount if kind else Decimal(0),
                                   is_external_flow=bool(kind and kind[1]), payload=t))
        batch = ActivityBatch(trades=[], cash=cash, raw=raw, skipped=dict(skipped), security_type_sources={})
        result = {"imported": 0, "duplicates": 0, "cash_imported": 0}
        service._store_raw(ba, batch.raw)
        service._ingest(ba, batch, result)
        last = max((r.occurred_on for r in raw), default=None)
        if last:
            ba.transactions_synced_through = last
        db.commit()
        service._after_trades_changed(ba)
        print(f"{plaid['subtype']} ··{plaid['mask']}: after {cutoff}: {result['cash_imported']} cash rows written, skipped {dict(skipped)}")


if __name__ == "__main__" and "--bank" in sys.argv:
    bank()
