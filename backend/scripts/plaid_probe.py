"""A throwaway, read-only look at what Plaid returns for one investment login.

Not part of the app: nothing here is imported by ``app`` and nothing is written to
the database. It exists to decide whether Plaid could replace SnapTrade for the
brokerage accounts (see the plan in docs/HOUSEHOLD_PLAN.md, section 3).

    python scripts/plaid_probe.py sandbox          # Plaid's test bank, no browser
    python scripts/plaid_probe.py link NAME        # opens a local page to link a real login
    python scripts/plaid_probe.py fetch NAME       # saves accounts, holdings, transactions
    python scripts/plaid_probe.py remove NAME      # removes the login from Plaid

NAME is a short label for one login (``mine``, ``wife``); each is kept apart.

Settings come from backend/.env: PLAID_CLIENT_ID, PLAID_SECRET_SANDBOX,
PLAID_SECRET_PRODUCTION, PLAID_ENV (sandbox | production), PLAID_REDIRECT_URI.
The access token is kept outside the repository (~/.achalara-plaid/, readable by
you only). Raw responses go to docs/plaid-probe/<env>/, which git never sees.
"""
import json
import os
import sys
import time
import webbrowser
from collections import Counter
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import plaid
from plaid.api import plaid_api
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.investments_transactions_get_request import (
    InvestmentsTransactionsGetRequest,
)
from plaid.model.investments_transactions_get_request_options import (
    InvestmentsTransactionsGetRequestOptions,
)
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import (
    SandboxPublicTokenCreateRequest,
)

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
TOKEN_DIR = Path.home() / ".achalara-plaid"
PORT = 8765
# Plaid's sandbox brokerage with investment data ("Houndstooth Bank").
SANDBOX_INSTITUTION = "ins_109508"


def read_env() -> dict:
    values = {}
    for line in (BACKEND / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


ENV = read_env()
PLAID_ENV = os.environ.get("PLAID_ENV", ENV.get("PLAID_ENV", "sandbox"))
LABEL = "sandbox-bank"
OUT_DIR = TOKEN_FILE = None


def use_label(label: str) -> None:
    global LABEL, OUT_DIR, TOKEN_FILE
    if not label.replace("-", "").replace("_", "").isalnum():
        sys.exit("NAME may only hold letters, digits, - and _")
    LABEL = label
    OUT_DIR = REPO / "docs" / "plaid-probe" / PLAID_ENV / label
    TOKEN_FILE = TOKEN_DIR / f"{PLAID_ENV}-{label}.json"


def client() -> plaid_api.PlaidApi:
    secret = ENV.get(f"PLAID_SECRET_{PLAID_ENV.upper()}", "")
    if not ENV.get("PLAID_CLIENT_ID") or not secret:
        sys.exit(f"PLAID_CLIENT_ID or PLAID_SECRET_{PLAID_ENV.upper()} is empty")
    host = plaid.Environment.Production if PLAID_ENV == "production" else plaid.Environment.Sandbox
    configuration = plaid.Configuration(
        host=host, api_key={"clientId": ENV["PLAID_CLIENT_ID"], "secret": secret}
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def save_token(access_token: str, item_id: str) -> None:
    TOKEN_DIR.mkdir(mode=0o700, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"access_token": access_token, "item_id": item_id}))
    TOKEN_FILE.chmod(0o600)
    print(f"Linked. Token kept in {TOKEN_FILE} (only you can read it).")


def load_token() -> str:
    if not TOKEN_FILE.exists():
        sys.exit(f"No linked login '{LABEL}' in {PLAID_ENV}; run 'sandbox' or 'link' first")
    return json.loads(TOKEN_FILE.read_text())["access_token"]


def write(name: str, payload) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, default=str))


def call(fn, request, attempts: int = 12):
    """Call Plaid, waiting while a new login's data is still being prepared."""
    for attempt in range(attempts):
        try:
            return fn(request).to_dict()
        except plaid.ApiException as exc:
            body = json.loads(exc.body or "{}")
            if body.get("error_code") == "PRODUCT_NOT_READY" and attempt < attempts - 1:
                print("  Plaid is still preparing the data; waiting 10 seconds")
                time.sleep(10)
                continue
            print(f"  Plaid refused: {body.get('error_code')}: {body.get('error_message')}")
            return {"error": body}


# --- linking --------------------------------------------------------------------


def cmd_sandbox() -> None:
    api = client()
    if PLAID_ENV != "sandbox":
        sys.exit("'sandbox' only works with PLAID_ENV=sandbox")
    created = api.sandbox_public_token_create(
        SandboxPublicTokenCreateRequest(
            institution_id=SANDBOX_INSTITUTION, initial_products=[Products("investments")]
        )
    )
    exchanged = api.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=created.public_token)
    )
    save_token(exchanged.access_token, exchanged.item_id)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Link a login to Plaid</title>
<style>body{font:17px system-ui,sans-serif;max-width:560px;margin:80px auto;padding:0 16px}
button{font:inherit;padding:12px 20px;border-radius:8px;border:0;background:#2450D6;color:#fff;cursor:pointer}</style>
</head><body>
<h1>Achalara: Plaid test</h1>
<p id="msg">Opening Plaid. If nothing appears, press the button.</p>
<button id="go" type="button">Open Plaid</button>
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
<script>
var config = {
  token: %(token)s,
  onSuccess: function (publicToken, metadata) {
    document.getElementById('msg').textContent = 'Saving the link...';
    fetch('/exchange', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({public_token: publicToken, institution: metadata.institution})})
      .then(function (r) { return r.text(); })
      .then(function (t) { document.getElementById('msg').textContent = t; });
  },
  onExit: function (err) {
    document.getElementById('msg').textContent = err ? ('Stopped: ' + (err.error_code || '') + ' ' + (err.display_message || err.error_message || '')) : 'Closed without linking.';
  }
};
if (%(oauth)s) { config.receivedRedirectUri = window.location.href; }
var handler = Plaid.create(config);
document.getElementById('go').onclick = function () { handler.open(); };
handler.open();
</script></body></html>"""


def cmd_link(consent: bool = False) -> None:
    """Link a login; with ``consent``, ask the linked login for bank transactions too
    (Plaid's update mode: same link, same Trial place, one more permission)."""
    api = client()
    # On a desktop browser Plaid runs an OAuth sign-in in a pop-up, so no redirect
    # address is needed; Production refuses one that is not https.
    redirect_uri = os.environ.get("PLAID_REDIRECT_URI", ENV.get("PLAID_REDIRECT_URI")) or None
    common = dict(
        client_name="Achalara",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id="achalara-probe"),
    )
    if consent:
        request = LinkTokenCreateRequest(
            access_token=load_token(), additional_consented_products=[Products("transactions")], **common
        )
    else:
        request = LinkTokenCreateRequest(products=[Products("investments")], **common)
    if redirect_uri:
        request.redirect_uri = redirect_uri
    try:
        link_token = api.link_token_create(request).link_token
    except plaid.ApiException as exc:
        sys.exit(f"Plaid refused the link token: {exc.body}")

    done = {"linked": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            oauth = self.path.startswith("/plaid-oauth")
            if self.path != "/" and not oauth:
                self.send_response(404)
                self.end_headers()
                return
            body = PAGE % {"token": json.dumps(link_token), "oauth": "true" if oauth else "false"}
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_POST(self):
            if self.path != "/exchange":
                self.send_response(404)
                self.end_headers()
                return
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if not consent:  # update mode keeps the same access token
                exchanged = api.item_public_token_exchange(
                    ItemPublicTokenExchangeRequest(public_token=data["public_token"])
                )
                save_token(exchanged.access_token, exchanged.item_id)
            name = (data.get("institution") or {}).get("name", "the institution")
            message = f"Linked {name}. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(message.encode())
            done["linked"] = True

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.timeout = 1
    url = f"http://localhost:{PORT}/"
    print(f"Open {url} if the browser does not open by itself. Ctrl-C to stop.")
    webbrowser.open(url)
    try:
        while not done["linked"]:
            server.handle_request()
    except KeyboardInterrupt:
        print("Stopped without linking.")
    finally:
        server.server_close()


# --- reading --------------------------------------------------------------------


def cmd_fetch() -> None:
    api = client()
    token = load_token()

    print("Accounts")
    accounts = call(api.accounts_get, AccountsGetRequest(access_token=token))
    write("accounts.json", accounts)
    for account in accounts.get("accounts", []):
        print(f"  {account['name']} ··{account.get('mask')} {account['type']}/{account.get('subtype')}")

    print("Holdings")
    holdings = call(api.investments_holdings_get, InvestmentsHoldingsGetRequest(access_token=token))
    write("holdings.json", holdings)
    held = holdings.get("holdings", [])
    with_lots = sum(1 for h in held if h.get("tax_lots"))
    with_cost = sum(1 for h in held if h.get("cost_basis") is not None)
    kinds = Counter(s.get("type") for s in holdings.get("securities", []))
    print(f"  {len(held)} holdings; {with_cost} with a cost basis, {with_lots} with tax lots")
    print(f"  security types: {dict(kinds)}")

    print("Investment transactions (the most Plaid allows: 24 months)")
    end = date.today()
    start = end - timedelta(days=730)
    rows, offset, total = [], 0, None
    first = None
    while total is None or offset < total:
        page = call(
            api.investments_transactions_get,
            InvestmentsTransactionsGetRequest(
                access_token=token,
                start_date=start,
                end_date=end,
                options=InvestmentsTransactionsGetRequestOptions(count=500, offset=offset),
            ),
        )
        if "error" in page:
            break
        if first is None:
            first = page
        else:
            seen = {s["security_id"] for s in first["securities"]}
            first["securities"] += [s for s in page["securities"] if s["security_id"] not in seen]
        rows += page["investment_transactions"]
        total = page["total_investment_transactions"]
        offset = len(rows)
    if first is not None:
        first = dict(first, investment_transactions=rows)
        write("investment_transactions.json", first)
    if rows:
        dates = sorted(str(r["date"]) for r in rows)
        print(f"  {len(rows)} transactions, {dates[0]} to {dates[-1]}")
        kinds = Counter(f"{r['type']}/{r['subtype']}" for r in rows)
        for kind, count in kinds.most_common():
            print(f"    {count:5d}  {kind}")
    print(f"Raw responses saved in {OUT_DIR}")


def cmd_remove() -> None:
    api = client()
    api.item_remove(ItemRemoveRequest(access_token=load_token()))
    TOKEN_FILE.unlink()
    print("Removed the login from Plaid and deleted the local token.")


def cmd_bank() -> None:
    """Bank-style activity (Plaid's Transactions product) for the login's accounts."""
    from plaid.model.transactions_sync_request import TransactionsSyncRequest
    api = client()
    token = load_token()
    added, cursor = [], None
    while True:
        request = TransactionsSyncRequest(access_token=token, count=500)
        if cursor:
            request.cursor = cursor
        page = call(api.transactions_sync, request)
        if "error" in page:
            return
        added += page["added"]
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    write("bank_transactions.json", {"added": added})
    print(f"  {len(added)} bank transactions")
    for t in sorted(added, key=lambda t: str(t["date"]))[-8:]:
        print(f"    {t['date']} {t['account_id'][:6]} {t['amount']:>10} {t.get('name', '')[:40]}")


COMMANDS = {"sandbox": cmd_sandbox, "link": cmd_link, "fetch": cmd_fetch, "remove": cmd_remove, "bank": cmd_bank,
            "consent": lambda: cmd_link(consent=True)}

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in COMMANDS or len(sys.argv) != (2 if command == "sandbox" else 3):
        sys.exit(__doc__)
    if TOKEN_FILE is None:
        use_label(sys.argv[2] if command != "sandbox" else "sandbox-bank")
    print(f"Plaid environment: {PLAID_ENV}, login: {LABEL}")
    COMMANDS[sys.argv[1]]()
