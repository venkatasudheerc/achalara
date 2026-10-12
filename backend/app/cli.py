"""Command-line tasks that have no place behind an HTTP route.

    python -m app.cli create-advisor --email you@example.com --name "Your Name"
"""
import argparse
import getpass
import sys

from app.db.database import SessionLocal
from app.services.auth_service import AuthError, AuthService


def create_advisor(email: str, name: str) -> int:
    """Create an advisor login. The password is asked for, never passed as an argument."""
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("The two passwords differ.", file=sys.stderr)
        return 1
    db = SessionLocal()
    try:
        user = AuthService(db).create_advisor(email, name, password)
    except AuthError as error:
        print(error.detail, file=sys.stderr)
        return 1
    finally:
        db.close()
    print(f"Advisor created: {user.email}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    advisor = commands.add_parser("create-advisor", help="create an advisor login")
    advisor.add_argument("--email", required=True)
    advisor.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-advisor":
        return create_advisor(args.email, args.name)
    return 2


if __name__ == "__main__":
    sys.exit(main())
