"""Command-line tasks that have no place behind an HTTP route.

    python -m app.cli create-advisor --email you@example.com --name "Your Name"
    python -m app.cli set-price --symbol SPX271217P06000000 --date 2026-12-31 --close 312.40
    python -m app.cli load-index-history --full
    python -m app.cli load-index-file --symbol DJI --file dow.csv --source some-name
    python -m app.cli md-index-membership
    python -m app.cli send-test-webhook --url https://example.com/api/v1/webhooks/snaptrade
"""
import argparse
from typing import Optional
import base64
import getpass
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from app.config import settings
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


def create_advisor(email: str, name: str) -> int:
    """Create an advisor login. The password is asked for, never passed as an argument."""
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
        created = AuthService(db).create_advisor(email, name, password).email
    except AuthError as error:
        print(error.detail, file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"Advisor created: {created}")
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


def send_test_webhook(url: str) -> int:
    """Post a harmless, properly signed event to our own webhook address.

    Proves the address is reachable from outside and that the signature check
    passes with the configured key. The event type is one the app ignores.
    """
    if not settings.snaptrade_consumer_key:
        print("SNAPTRADE_CONSUMER_KEY is not set.", file=sys.stderr)
        return 1
    event = {
        "eventType": "ACHALARA_TEST",
        "webhookId": str(uuid.uuid4()),
        "eventTimestamp": datetime.now(timezone.utc).isoformat(),
    }
    content = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
    digest = hmac.new(
        settings.snaptrade_consumer_key.encode(), content, hashlib.sha256
    ).digest()
    request = urllib.request.Request(
        url,
        data=json.dumps(event).encode(),
        headers={
            "Content-Type": "application/json",
            "Signature": base64.b64encode(digest).decode(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            print(f"{response.status} {response.read().decode()[:200]}")
            return 0
    except urllib.error.HTTPError as error:
        print(f"Refused: {error.code} {error.read().decode()[:200]}", file=sys.stderr)
    except OSError as error:
        print(f"Could not reach {url}: {error}", file=sys.stderr)
    return 1


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


def md_identifiers() -> int:
    """Fill in Webull ids, SEC companies and FIGIs now."""
    from app.md.database import MdSession
    from app.md.identifiers import run_identifiers

    db = MdSession()
    try:
        print(run_identifiers(db, date.today()))
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


def md_index_levels() -> int:
    """Fetch index levels now: in full for an index without any."""
    from app.md.database import MdSession
    from app.md.levels import run_index_levels

    db = MdSession()
    try:
        print(run_index_levels(db))
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    advisor = commands.add_parser("create-advisor", help="create an advisor login")
    advisor.add_argument("--email", required=True)
    advisor.add_argument("--name", required=True)
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
    webhook = commands.add_parser(
        "send-test-webhook", help="post a signed test event to our webhook address"
    )
    webhook.add_argument(
        "--url", required=True, help="https://<domain>/api/v1/webhooks/snaptrade"
    )
    commands.add_parser(
        "md-index-membership",
        help="market data: fetch index holdings now and update membership",
    )
    commands.add_parser(
        "md-identifiers", help="market data: Webull ids, SEC companies, FIGIs now"
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
    commands.add_parser(
        "md-index-levels", help="market data: index levels now (in full the first time)"
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
    args = parser.parse_args(argv)
    if args.command == "md-daily-closes":
        return md_daily_closes()
    if args.command == "md-adjusted-history":
        return md_adjusted_history()
    if args.command == "md-index-levels":
        return md_index_levels()
    if args.command == "md-refresh-returns":
        return md_refresh_returns()
    if args.command == "md-track-fund":
        return md_track_fund(args.symbol, args.group, args.remove)
    if args.command == "md-identifiers":
        return md_identifiers()
    if args.command == "md-classification":
        return md_classification(args.refresh)
    if args.command == "md-set-sector":
        return md_set_sector(args.symbol, args.sector, args.industry)
    if args.command == "md-index-membership":
        return md_index_membership()
    if args.command == "send-test-webhook":
        return send_test_webhook(args.url)
    if args.command == "create-advisor":
        return create_advisor(args.email, args.name)
    if args.command == "set-price":
        return set_price(args.symbol, args.date, args.close)
    if args.command == "load-index-file":
        return load_index_file(args.symbol, args.file, args.source, args.replace)
    if args.command == "load-index-history":
        return load_index_history(args.symbol, args.full)
    return 2


if __name__ == "__main__":
    sys.exit(main())
