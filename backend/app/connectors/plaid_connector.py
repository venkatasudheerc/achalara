"""Plaid: the institution logins clients link themselves.

One developer account (``PLAID_CLIENT_ID``, ``PLAID_SECRET``) serves every
client; each login a client links is an Item with its own access key, which is
stored encrypted (``utils/secret_box.py``) and never logged. Plaid's API is JSON
over HTTPS: every call is a POST carrying the developer keys.

Only what Achalara uses is here: making a link token, exchanging the token Link
hands back, and reading accounts, investment holdings and transactions, bank
transactions and liabilities. Tests replace ``PlaidClient._post`` with recorded
replies; nothing here may run against Plaid in the default test run.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import httpx

from app.config import settings

_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}
# Every link asks for these. Transactions is required; Investments and
# Liabilities are asked for wherever the institution offers them.
PRODUCTS = ("transactions",)
IF_SUPPORTED = ("investments", "liabilities")
TRANSACTION_DAYS = 730  # Plaid's most
_TIMEOUT = httpx.Timeout(30.0)


class PlaidError(Exception):
    """Plaid refused a request. ``code`` is Plaid's error code (ITEM_LOGIN_REQUIRED,
    PRODUCT_NOT_READY, …); the message is Plaid's own words for a person."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


def configured() -> bool:
    """Whether linking with Plaid can be offered."""
    return bool(settings.plaid_client_id and settings.plaid_secret and settings.plaid_token_key)


class PlaidClient:
    """Plaid's API with this deployment's keys."""

    def __init__(self, env: Optional[str] = None):
        env = (env or settings.plaid_env or "sandbox").lower()
        if env not in _HOSTS:
            raise ValueError("PLAID_ENV must be sandbox or production")
        self.env = env
        self.host = _HOSTS[env]

    def _post(self, path: str, body: Dict) -> Dict:
        payload = {
            "client_id": settings.plaid_client_id,
            "secret": settings.plaid_secret,
            **body,
        }
        response = httpx.post(self.host + path, json=payload, timeout=_TIMEOUT)
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            raise PlaidError(
                data.get("error_code", "UNKNOWN"),
                data.get("display_message") or data.get("error_message") or "Plaid refused the request",
                response.status_code,
            )
        return data

    # -- linking --------------------------------------------------------------

    def link_token(
        self,
        client_user_id: str,
        redirect_uri: str = "",
        webhook: str = "",
        access_token: str = "",
    ) -> Dict:
        """A token that opens Plaid Link for one client. With ``access_token`` it
        opens Link in update mode, to repair a login that needs signing in again."""
        body: Dict = {
            "user": {"client_user_id": client_user_id},
            "client_name": "Achalara",
            "language": "en",
            "country_codes": ["US"],
        }
        if access_token:
            body["access_token"] = access_token
        else:
            body["products"] = list(PRODUCTS)
            body["required_if_supported_products"] = list(IF_SUPPORTED)
            # Plaid gives 90 days of transactions unless more is asked for, and
            # only when a login is linked; it can never be asked for later.
            body["transactions"] = {"days_requested": TRANSACTION_DAYS}
        if redirect_uri:
            body["redirect_uri"] = redirect_uri
        if webhook:
            body["webhook"] = webhook
        return self._post("/link/token/create", body)

    def exchange(self, public_token: str) -> Dict:
        """The access key and Item id for the token Link handed back."""
        return self._post("/item/public_token/exchange", {"public_token": public_token})

    def item(self, access_token: str) -> Dict:
        return self._post("/item/get", {"access_token": access_token})

    def institution(self, institution_id: str) -> Dict:
        return self._post(
            "/institutions/get_by_id",
            {"institution_id": institution_id, "country_codes": ["US"]},
        )

    def remove(self, access_token: str) -> Dict:
        return self._post("/item/remove", {"access_token": access_token})

    # -- reading --------------------------------------------------------------

    def accounts(self, access_token: str) -> Dict:
        return self._post("/accounts/get", {"access_token": access_token})

    def holdings(self, access_token: str) -> Dict:
        return self._post("/investments/holdings/get", {"access_token": access_token})

    def investment_transactions(self, access_token: str, start: date, end: date) -> Dict:
        """Every investment transaction in the window, all pages together."""
        rows: List[Dict] = []
        securities: Dict[str, Dict] = {}
        offset = 0
        while True:
            page = self._post(
                "/investments/transactions/get",
                {
                    "access_token": access_token,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "options": {"count": 500, "offset": offset},
                },
            )
            rows.extend(page.get("investment_transactions", []))
            for security in page.get("securities", []):
                securities[security["security_id"]] = security
            offset += len(page.get("investment_transactions", []))
            if not page.get("investment_transactions") or offset >= page.get("total_investment_transactions", 0):
                return {
                    "accounts": page.get("accounts", []),
                    "investment_transactions": rows,
                    "securities": list(securities.values()),
                }

    def transactions_sync(self, access_token: str, cursor: str = "") -> Dict:
        """Bank and card transactions added, changed and removed since ``cursor``,
        all pages together, with the cursor to pass next time."""
        added: List[Dict] = []
        modified: List[Dict] = []
        removed: List[Dict] = []
        while True:
            body: Dict = {"access_token": access_token, "count": 500}
            if cursor:
                body["cursor"] = cursor
            page = self._post("/transactions/sync", body)
            added += page.get("added", [])
            modified += page.get("modified", [])
            removed += page.get("removed", [])
            cursor = page.get("next_cursor", cursor)
            if not page.get("has_more"):
                return {"added": added, "modified": modified, "removed": removed, "next_cursor": cursor}

    def liabilities(self, access_token: str) -> Dict:
        return self._post("/liabilities/get", {"access_token": access_token})
