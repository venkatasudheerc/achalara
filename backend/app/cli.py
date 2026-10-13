"""Command-line tasks that have no place behind an HTTP route.

    python -m app.cli create-advisor --email you@example.com --name "Your Name"
    python -m app.cli set-price --symbol SPX271217P06000000 --date 2026-12-31 --close 312.40
    python -m app.cli load-index-history --full
    python -m app.cli load-index-file --symbol DJI --file dow.csv --source some-name
    python -m app.cli send-test-webhook --url https://example.com/api/v1/webhooks/snaptrade
"""
import argparse
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
    args = parser.parse_args(argv)
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
