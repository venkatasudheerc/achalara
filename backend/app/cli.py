"""Command-line tasks that have no place behind an HTTP route.

    python -m app.cli create-advisor --email you@example.com --name "Your Name"
    python -m app.cli set-price --symbol SPX271217P06000000 --date 2026-12-31 --close 312.40
    python -m app.cli load-index-history --full
    python -m app.cli load-index-file --symbol DJI --file dow.csv --source some-name
"""
import argparse
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
    args = parser.parse_args(argv)
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
