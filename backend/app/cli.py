"""Command-line tasks that have no place behind an HTTP route.

    python -m app.cli create-admin --email you@example.com --name "Your Name"
    python -m app.cli set-price --symbol SPX271217P06000000 --date 2026-12-31 --close 312.40
    python -m app.cli load-index-history --full
    python -m app.cli load-index-file --symbol DJI --file dow.csv --source some-name
    python -m app.cli md-index-membership
"""
import argparse
from typing import Optional
import getpass
import sys
from datetime import date
from decimal import Decimal, InvalidOperation

from app.db.database import SessionLocal
from app.services.auth_service import (
    MIN_PASSWORD_LENGTH,
    AuthError,
    AuthService,
    password_problems,
)
from app.services.index_history_service import (
    INDICES,
    IndexHistoryService,
    read_csv_bars,
)
from app.services.price_history_service import set_manual_price


def create_admin(email: str, name: str) -> int:
    """Create an admin login. The password is asked for, never passed as an argument."""
    print(
        f"Choose a password: at least {MIN_PASSWORD_LENGTH} characters, with a "
        "letter and a number, and not containing your email's name."
    )
    while True:
        password = getpass.getpass("Password: ")
        # Said at once, before asking for it a second time.
        problems = password_problems(password, email)
        if problems:
            print(" ".join(problems), file=sys.stderr)
            continue
        if password == getpass.getpass("Repeat password: "):
            break
        print("The two passwords differ. Start again.", file=sys.stderr)
    db = SessionLocal()
    try:
        # Read before the session closes; a committed row cannot be read after.
        created = AuthService(db).create_admin(email, name, password).email
    except AuthError as error:
        print(error.detail, file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"Admin created: {created}")
    return 0


def set_price(symbol: str, on: str, close: str) -> int:
    """Enter a price by hand: the year-end price an index option is marked to."""
    try:
        day, price = date.fromisoformat(on), Decimal(close)
    except (ValueError, InvalidOperation):
        print("Give the date as YYYY-MM-DD and the price as a number.", file=sys.stderr)
        return 1
    db = SessionLocal()
    try:
        row = set_manual_price(db, symbol, day, price)
        saved = f"{row.symbol} on {row.price_date}: {row.close}"
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"Price recorded for {saved} (per share, as quoted)")
    return 0


def add_ticker_change(old: str, new: str, on: str) -> int:
    """Record that ``old`` trades as ``new`` from ``on``, then rebuild the
    accounts that traded or held either, so their openings and records follow."""
    from app.services.ticker_changes import record

    try:
        day = date.fromisoformat(on)
    except ValueError:
        print("Give the date as YYYY-MM-DD.", file=sys.stderr)
        return 1
    db = SessionLocal()
    try:
        rebuilt = record(db, old, new, day, "manual")
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"{old.upper()} is read as {new.upper()} from {day}; {rebuilt} account(s) rebuilt.")
    return 0


def repair_duplicate_splits(apply: bool) -> int:
    """A split recorded twice (the same symbol within three days) makes shares
    that were never held. Shows them; with --apply removes the later copies and
    rebuilds the accounts that traded the symbol. Safe to repeat."""
    from app.services.corporate_actions import repair_duplicate_splits as repair

    db = SessionLocal()
    try:
        result = repair(db, apply)
    finally:
        db.close()
    if not result["duplicates"]:
        print("No split is recorded twice.")
        return 0
    for item in result["duplicates"]:
        keep = item["keep"]
        print(f"{item['symbol']}: keep {keep[0]} (x{keep[1]:g}); "
              + ", ".join(f"{d} (x{r:g})" for d, r in item["remove"]) + (" removed" if apply else " would be removed"))
    print(f"{result['rebuilt']} account(s) rebuilt." if apply else "Nothing changed. Add --apply to remove them and rebuild.")
    return 0


def plaid_refresh(client: Optional[str]) -> int:
    """The morning's Plaid refresh, now: every active login, or one client's.
    Safe to repeat (rows are matched by Plaid's ids; the cursor only moves
    forward). It records the day before, as the morning job does."""
    from app.models.brokerage_connection import BrokerageConnection
    from app.models.client import Client
    from app.services.plaid_refresh_service import PlaidRefreshService

    db = SessionLocal()
    try:
        logins = db.query(BrokerageConnection).filter(
            BrokerageConnection.source == "plaid", BrokerageConnection.status == "active"
        )
        if client:
            found = (
                db.query(Client)
                .filter((Client.id == client) | (Client.name.ilike(client)))
                .all()
            )
            if len(found) != 1:
                print(f"No single client is called {client!r}.", file=sys.stderr)
                return 1
            logins = logins.filter(BrokerageConnection.client_id == found[0].id)
        service = PlaidRefreshService(db)
        logins = logins.all()
        if not logins:
            print("No active Plaid login to refresh.")
            return 0
        failed = 0
        for login in logins:
            try:
                outcome = service.refresh(login)
            except Exception as error:  # one login never stops the rest
                db.rollback()
                outcome, failed = f"failed ({type(error).__name__})", failed + 1
            print(f"{login.institution or 'A login'}: {outcome}")
        return 1 if failed else 0
    finally:
        db.close()


def compare_feeds(client: str, days: int) -> int:
    """Read only: for a client's new Plaid login, whether its trades match what an
    existing feed of the same account already stored (by id, or by what they were)."""
    from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
    from app.models.client import Client
    from app.services.feed_compare import compare

    db = SessionLocal()
    try:
        found = (
            db.query(Client).filter((Client.id == client) | (Client.name.ilike(client))).all()
        )
        if len(found) != 1:
            print(f"No single client is called {client!r}.", file=sys.stderr)
            return 1
        logins = (
            db.query(BrokerageConnection)
            .join(BrokerageAccount)
            .filter(
                BrokerageConnection.client_id == found[0].id,
                BrokerageConnection.source == "plaid",
                BrokerageAccount.status == "unmapped",
            )
            .distinct()
            .all()
        )
        if not logins:
            print("No login of this client has accounts waiting to be added.")
            return 0
        for login in logins:
            print(f"{login.institution or 'A login'}:")
            for row in compare(db, login, days):
                label = f"  {row['name']} ··{row['mask'] or '?'}"
                if "error" in row:
                    print(f"{label}: Plaid said: {row['error']}")
                    continue
                print(
                    f"{label}: new login {row['new_login_trades']} trades in {row['days']} days; "
                    f"same id {row['same_id']}, same trade under another id {row['same_trade_other_id']}, "
                    f"not on file {row['not_on_file']} (stored {row['stored_trades']})"
                )
        return 0
    finally:
        db.close()


def load_index_history(symbols, full: bool) -> int:
    """Load or top up the daily bars of the market indices."""
    db = SessionLocal()
    try:
        service = IndexHistoryService(db)
        written = service.refresh(symbols or None, full=full)
        extent = service.extent()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        db.close()
    for symbol, days in written.items():
        held = extent.get(symbol)
        span = (
            f"on file {held['first']} to {held['last']}, {held['days']} days"
            if held
            else "nothing on file"
        )
        print(f"{symbol}: {days} days written; {span}")
    return 0


def load_index_file(symbol: str, path: str, source: str, replace: bool) -> int:
    """Load an index's daily bars from a downloaded file."""
    db = SessionLocal()
    try:
        bars = read_csv_bars(path)
        written = IndexHistoryService(db).load_file(symbol, bars, source, replace)
    except (OSError, KeyError, ValueError) as error:
        print(f"Could not load {path}: {error}", file=sys.stderr)
        return 1
    finally:
        db.close()
    print(
        f"{symbol.upper()}: {written} days written, {bars[0]['bar_date']} to {bars[-1]['bar_date']}"
    )
    return 0


def md_index_membership() -> int:
    """Fetch the index funds' holdings now and bring membership up to date."""
    from app.md.database import MdSession
    from app.md.membership import run_index_membership
    from app.md.seed import seed_securities
    from app.services.held_symbols import held_symbols

    app_db = SessionLocal()
    db = MdSession()
    try:
        added = seed_securities(db, held_symbols(app_db), date.today())
        print(f"Held securities added to the security master: {added}")
        print(run_index_membership(db).summary())
    finally:
        db.close()
        app_db.close()
    return 0


def md_identifiers(names_only: bool = False) -> int:
    """Fill in Webull ids, SEC companies and FIGIs now, or with ``names_only`` just the
    Webull list and the names it gives."""
    from app.md.database import MdSession
    from app.md.identifiers import run_identifiers

    db = MdSession()
    try:
        print(run_identifiers(db, date.today(), names_only=names_only))
    finally:
        db.close()
    return 0


def md_classification(refresh: bool) -> int:
    """Work out sectors and industries now."""
    from app.md.classification import run_classification
    from app.md.database import MdSession

    db = MdSession()
    try:
        print(run_classification(db, date.today(), refresh=refresh))
    finally:
        db.close()
    return 0


def md_daily_closes() -> int:
    """Capture the latest day's prices as traded, now."""
    from app.md.closes import run_daily_closes
    from app.md.database import MdSession

    db = MdSession()
    try:
        print(run_daily_closes(db))
    finally:
        db.close()
    return 0


def md_adjusted_history() -> int:
    """Fetch adjusted history now: in full for securities without it."""
    from app.md.adjusted import run_adjusted_history
    from app.md.database import MdSession

    db = MdSession()
    try:
        print(run_adjusted_history(db))
    finally:
        db.close()
    return 0


def md_index_levels(market: Optional[str] = None) -> int:
    """Fetch index levels now (one market, or each in turn): in full for an index without any."""
    from app.md.database import MdSession
    from app.md.levels import run_index_levels

    db = MdSession()
    try:
        print(run_index_levels(db, market=market))
    finally:
        db.close()
    return 0


def md_refresh_returns() -> int:
    """Refresh the stored week and month return tables now."""
    from app.md.database import MdSession
    from app.md.views import refresh_return_views

    db = MdSession()
    try:
        print(refresh_return_views(db))
    finally:
        db.close()
    return 0


def md_track_fund_list(path: str, apply: bool) -> int:
    """Check a list of funds with Webull; with ``apply``, track the ones it knows."""
    from app.md.closes import read_fund_list, track_fund_list
    from app.md.database import MdSession
    from app.md.webull import WebullClient, WebullError

    webull = WebullClient()
    if not webull.configured():
        print("Webull is not configured; nothing checked", file=sys.stderr)
        return 1
    with open(path, encoding="utf-8") as handle:
        entries = read_fund_list(handle)
    db = MdSession()
    try:
        report = track_fund_list(db, webull, entries, date.today(), apply=apply)
    except WebullError as exc:
        print(f"Webull could not be asked ({exc}); nothing added", file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"{len(entries)} in the list")
    print(f"Already tracked ({len(report['already_tracked'])}): {' '.join(report['already_tracked'])}")
    print(f"Webull lists as ETFs ({len(report['to_add'])}): {' '.join(report['to_add'])}")
    print(f"Webull does not list as ETFs, not added ({len(report['unknown'])}): {' '.join(report['unknown'])}")
    if apply:
        print(f"Added ({len(report['added'])}). Their history loads on the next adjusted-history "
              "run, or now with: python -m app.cli md-adjusted-history")
    else:
        print("Nothing changed. Run again with --apply to add them.")
    return 0


def md_track_fund(symbol: Optional[str], group: Optional[str], remove: bool) -> int:
    """Track a fund (priced each evening), stop tracking one, or list them."""
    from app.md.closes import track_fund, tracked, untrack_fund
    from app.md.database import MdSession

    db = MdSession()
    try:
        if symbol is None:
            for name, asset_group in tracked(db):
                print(f"{asset_group:15} {name}")
            return 0
        if remove:
            if untrack_fund(db, symbol, date.today()):
                print(f"{symbol} is no longer tracked; its prices stay")
                return 0
            print(f"{symbol} is not tracked", file=sys.stderr)
            return 1
        if not group:
            print("--group is needed to track a fund", file=sys.stderr)
            return 1
        track_fund(db, symbol, group.strip().lower(), date.today())
        print(f"{symbol} tracked as {group.strip().lower()}")
    finally:
        db.close()
    return 0


def md_set_sector(symbol: str, sector: Optional[str], industry: Optional[str]) -> int:
    """Set a security's sector and/or industry by hand; never overwritten by a source."""
    from app.md.classification import ClassificationService
    from app.md.database import MdSession
    from app.md.sectors import SECTORS

    codes = {code for code, _, _ in SECTORS}
    if sector and sector not in codes:
        print(f"Sector must be one of: {', '.join(sorted(codes))}", file=sys.stderr)
        return 1
    db = MdSession()
    try:
        ClassificationService(db).set_manual(
            symbol.strip().upper(), sector, industry, date.today()
        )
    except LookupError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"{symbol.upper()}: set by hand")
    return 0


def _qty(value) -> str:
    """A quantity as people write it: 100, 2.5, 0.044."""
    return format(abs(Decimal(value)).normalize(), "f")


def _brokerage_account(db, key: str):
    """A brokerage account by its id, or by the last digits of its number."""
    from app.models.brokerage_connection import BrokerageAccount

    account = db.get(BrokerageAccount, key)
    if account is not None:
        return account
    digits = "".join(ch for ch in key if ch.isdigit())
    found = [
        a
        for a in db.query(BrokerageAccount).filter(BrokerageAccount.status == "mapped")
        if digits
        and (
            a.number_last4 == digits[-4:]
            or digits in "".join(ch for ch in (a.name or "") if ch.isdigit())
        )
    ]
    if len(found) == 1:
        return found[0]
    print(
        f"{len(found) or 'No'} mapped accounts match {key!r}; give the brokerage "
        "account's id instead.",
        file=sys.stderr,
    )
    for a in found:
        print(f"  {a.id}  {a.name}", file=sys.stderr)
    return None


def import_vanguard_report(
    account_key: str,
    path: str,
    start: Optional[str],
    end: Optional[str],
    apply: bool,
) -> int:
    """Add the trades and cash rows in Vanguard's activity report that are not on
    file. Shows what it would add; nothing is written without ``apply``."""
    import re
    from pathlib import Path

    from app.services.account_import_service import AccountImportService
    from app.services.connection_service import ConnectionService
    from app.utils.symbols import app_symbol
    from app.services.vanguard_report import (
        ReportError,
        VanguardReportImport,
        read_report,
    )

    file = Path(path)
    try:
        start_day = date.fromisoformat(start) if start else None
        end_day = date.fromisoformat(end) if end else None
        rows = read_report(file)
    except (ValueError, ReportError, OSError) as error:
        print(error, file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        ba = _brokerage_account(db, account_key)
        if ba is None:
            return 1
        # Vanguard names the download after the account's number: refuse a
        # file that names a different account.
        named = re.findall(r"\d{6,}", file.name)
        account_digits = "".join(ch for ch in ba.name if ch.isdigit())
        if named and not any(n in account_digits for n in named):
            print(
                f"{file.name} names account {named[0]}, not {ba.name}.", file=sys.stderr
            )
            return 1

        importer = VanguardReportImport(db, ConnectionService(db, connector=object()))
        plan = importer.plan(ba, rows, start_day, end_day)
        print(f"{ba.name}")
        print(
            f"  report: {plan.rows} rows, trade dates {plan.first} to {plan.last}"
        )
        print(
            f"  already on file: {plan.held_trades} trades, {plan.held_cash} cash rows"
        )
        print(
            f"  set aside: {dict(plan.skipped) or 'none'}"
        )
        print(f"  to add: {len(plan.trades)} trades, {len(plan.cash)} cash rows, {len(plan.splits)} splits")
        for day, count in plan.new_days.items():
            items = [
                f"{t.action.value.lower()} {_qty(t.quantity)} {t.symbol}"
                for r, t in plan.trades
                if r.traded == day
            ] + [f"{c.type.lower()} {c.amount}" for r, c in plan.cash if r.traded == day] + [
                f"split {r.symbol} +{_qty(r.quantity)}" for r in plan.splits if r.traded == day
            ]
            print(f"    {day}: {count}  ({', '.join(items)})")
        renamed = [
            (r, o)
            for r, o in plan.loose_matches
            if app_symbol(o["symbol"]) != app_symbol(r.symbol)
        ]
        dated = len(plan.loose_matches) - len(renamed)
        if dated:
            print(
                f"  {dated} on file a trading day later (options' expiries and "
                "assignments, and the shares they delivered)"
            )
        if renamed:
            print(
                f"  {len(renamed)} on file under another spelling of the symbol "
                "(a delisted stock by name, a renamed one by its new ticker), e.g.:"
            )
            shown = {}
            for row, ours in renamed:
                shown.setdefault((row.symbol, ours["symbol"]), row)
            for (theirs, ours_symbol), row in list(shown.items())[:12]:
                print(f"    {theirs or row.name} = {ours_symbol}")
        if plan.needs_a_look:
            print("  not read (splits and mergers come from the feed; look only if a holding is off):")
            for row in plan.needs_a_look:
                print(
                    f"    line {row.line}: {row.traded} {row.kind} {row.symbol or row.name} "
                    f"{_qty(row.quantity) if row.quantity else ''} {row.amount or ''}"
                )
        if not apply:
            print("\nNothing written. Add --apply to add these rows.")
            return 0
        if not plan.trades and not plan.cash:
            print("\nNothing to add.")
            return 0
        holdings = AccountImportService(db).last_holdings(ba.account_id)
        result = importer.apply(ba, plan, holdings)
        print(
            f"\nAdded {result['imported']} trades and {result['cash_imported']} cash rows "
            f"({result['duplicates']} recognised as already on file); history rebuilt."
        )
        return 0
    finally:
        db.close()


def split_into_strategies(account_key: Optional[str], apply: bool) -> int:
    """Sort accounts linked as one sleeve into Stocks, ETFs, Mutual funds,
    Options and Cash. Shows what it would do; --apply writes. Safe to repeat."""
    from app.models.account import Account
    from app.models.brokerage_connection import BrokerageAccount
    from app.services import strategy_split

    db = SessionLocal()
    try:
        if account_key:
            one = _brokerage_account(db, account_key)
            if one is None:
                return 1
            links = [one]
        else:
            links = (
                db.query(BrokerageAccount)
                .filter(BrokerageAccount.status == "mapped", BrokerageAccount.account_id.isnot(None))
                .all()
            )
        for link in links:
            account = db.get(Account, link.account_id)
            label = f"{account.display_name or account.name}" + (
                f" ··{link.number_last4}" if link.number_last4 else ""
            )
            plan = strategy_split.plan(db, link)
            if plan.nothing_to_do:
                print(f"{label}: nothing to do")
                continue
            print(f"{label}:")
            if plan.becomes:
                print(f"  its sleeve becomes {plan.becomes}")
            for move in plan.moves:
                shown = ", ".join(move.symbols[:6]) + (" …" if len(move.symbols) > 6 else "")
                print(f"  to {move.to_strategy}: {len(move.symbols)} symbols, {move.trades} trades ({shown})")
            if plan.unnamed_cash:
                print(f"  to Cash: {plan.unnamed_cash} cash rows with no security")
            if plan.untyped:
                print(f"  no type known, stays in Stocks: {', '.join(plan.untyped)}")
            if apply:
                strategy_split.apply(db, link)
                print("  done")
        if not apply:
            print("Nothing written. Run again with --apply to split.")
        return 0
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="create an admin login")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    price = commands.add_parser(
        "set-price", help="enter a year-end price for an index option"
    )
    price.add_argument("--symbol", required=True)
    price.add_argument("--date", required=True, help="YYYY-MM-DD")
    price.add_argument("--close", required=True, help="per share, as quoted")
    indices = commands.add_parser(
        "load-index-history", help="load or top up the market indices' daily bars"
    )
    indices.add_argument(
        "--symbol", action="append", help=f"one of {', '.join(INDICES)}; repeatable"
    )
    indices.add_argument(
        "--full", action="store_true", help="reload from each index's first day"
    )
    from_file = commands.add_parser(
        "load-index-file", help="load an index's daily bars from a downloaded file"
    )
    from_file.add_argument("--symbol", required=True)
    from_file.add_argument(
        "--file", required=True, help="CSV with Date, Open, High, Low, Close, Volume"
    )
    from_file.add_argument("--source", required=True, help="where the file came from")
    from_file.add_argument(
        "--replace", action="store_true", help="remove the index's stored days first"
    )
    commands.add_parser(
        "md-index-membership",
        help="market data: fetch index holdings now and update membership",
    )
    identifiers = commands.add_parser(
        "md-identifiers", help="market data: Webull ids, SEC companies, FIGIs now"
    )
    identifiers.add_argument(
        "--names-only",
        action="store_true",
        help="only Webull's instrument list (a few requests) and the names it gives",
    )
    classify = commands.add_parser(
        "md-classification", help="market data: sectors and industries now"
    )
    classify.add_argument(
        "--refresh", action="store_true", help="also refresh older Webull profiles"
    )
    manual = commands.add_parser(
        "md-set-sector", help="market data: set a sector or industry by hand"
    )
    manual.add_argument("--symbol", required=True)
    manual.add_argument(
        "--sector", help="IT, HC, FIN, CD, CS, COM, EN, IND, MAT, RE, UT"
    )
    manual.add_argument("--industry")
    commands.add_parser(
        "md-daily-closes", help="market data: capture the latest day's prices now"
    )
    commands.add_parser(
        "md-adjusted-history",
        help="market data: adjusted daily closes now (in full where none are on file)",
    )
    levels_cmd = commands.add_parser(
        "md-index-levels", help="market data: index levels now (in full the first time)"
    )
    levels_cmd.add_argument(
        "--market", choices=["US", "IN"], help="one market's indices; both when left out"
    )
    commands.add_parser(
        "md-refresh-returns",
        help="market data: refresh the stored week and month return tables now",
    )
    fund = commands.add_parser(
        "md-track-fund",
        help="market data: track a fund, stop tracking one (--remove), or list them",
    )
    fund.add_argument("--symbol")
    fund.add_argument("--group", help="benchmark, sector, gold, … (any short word)")
    fund.add_argument("--remove", action="store_true")
    fund.add_argument(
        "--file",
        help="a list of 'SYMBOL group  # note' lines: checked with Webull; nothing changes without --apply",
    )
    fund.add_argument("--apply", action="store_true", help="with --file: track the ones Webull knows")
    rename = commands.add_parser(
        "add-ticker-change",
        help="a company now trades under a new ticker: read its earlier trades under it",
    )
    rename.add_argument("--from", dest="old", required=True)
    rename.add_argument("--to", dest="new", required=True)
    rename.add_argument("--date", required=True, help="the first day under the new ticker, YYYY-MM-DD")
    dupes = commands.add_parser(
        "repair-duplicate-splits",
        help="a split recorded twice makes shares never held: show them (--apply removes the copies and rebuilds)",
    )
    dupes.add_argument("--apply", action="store_true")
    refresh = commands.add_parser(
        "plaid-refresh",
        help="the morning's Plaid refresh, now: every active login, or one client's",
    )
    refresh.add_argument("--client", help="the client's id or name; all clients when left out")
    compare_cmd = commands.add_parser(
        "compare-feeds",
        help="read only: do a new Plaid login's trades match what another login's feed of the same account stored",
    )
    compare_cmd.add_argument("--client", required=True, help="the client's id or name")
    compare_cmd.add_argument("--days", type=int, default=90, help="how far back to compare (default 90)")
    report = commands.add_parser(
        "import-vanguard-report",
        help="add the trades and cash rows in Vanguard's activity report that are not on file",
    )
    report.add_argument(
        "--account", required=True, help="brokerage account id, or its number's last digits"
    )
    report.add_argument("--file", required=True, help="the report, downloaded as Excel")
    report.add_argument("--from", dest="start", help="first trade date to read, YYYY-MM-DD")
    report.add_argument("--to", dest="end", help="last trade date to read, YYYY-MM-DD")
    report.add_argument("--apply", action="store_true", help="write; without it, only show")
    split = commands.add_parser(
        "split-into-strategies",
        help="sort accounts linked as one sleeve into Stocks, ETFs, Mutual funds, Options and Cash",
    )
    split.add_argument("--account", help="one brokerage account (id, or its number's last digits); all when left out")
    split.add_argument("--apply", action="store_true", help="write; without it, only show")
    args = parser.parse_args(argv)
    if args.command == "split-into-strategies":
        return split_into_strategies(args.account, args.apply)
    if args.command == "repair-duplicate-splits":
        return repair_duplicate_splits(args.apply)
    if args.command == "add-ticker-change":
        return add_ticker_change(args.old, args.new, args.date)
    if args.command == "plaid-refresh":
        return plaid_refresh(args.client)
    if args.command == "compare-feeds":
        return compare_feeds(args.client, args.days)
    if args.command == "import-vanguard-report":
        return import_vanguard_report(
            args.account, args.file, args.start, args.end, args.apply
        )
    if args.command == "md-daily-closes":
        return md_daily_closes()
    if args.command == "md-adjusted-history":
        return md_adjusted_history()
    if args.command == "md-index-levels":
        return md_index_levels(args.market)
    if args.command == "md-refresh-returns":
        return md_refresh_returns()
    if args.command == "md-track-fund":
        if args.file:
            return md_track_fund_list(args.file, args.apply)
        return md_track_fund(args.symbol, args.group, args.remove)
    if args.command == "md-identifiers":
        return md_identifiers(names_only=args.names_only)
    if args.command == "md-classification":
        return md_classification(args.refresh)
    if args.command == "md-set-sector":
        return md_set_sector(args.symbol, args.sector, args.industry)
    if args.command == "md-index-membership":
        return md_index_membership()
    if args.command == "create-admin":
        return create_admin(args.email, args.name)
    if args.command == "set-price":
        return set_price(args.symbol, args.date, args.close)
    if args.command == "load-index-file":
        return load_index_file(args.symbol, args.file, args.source, args.replace)
    if args.command == "load-index-history":
        return load_index_history(args.symbol, args.full)
    return 2


if __name__ == "__main__":
    sys.exit(main())
