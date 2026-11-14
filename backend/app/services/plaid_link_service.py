"""A client links an institution login through Plaid, and says which of its
accounts are which.

1. ``start``: a link token opens Plaid Link for the client.
2. ``finish``: the token Link hands back becomes the login's access key (stored
   encrypted); the login's accounts are read, and for each one a proposal is
   made: the same as an account already here, one to choose, or a new one.
3. ``confirm``: the person's choice for each account. A new or plainly linked
   account gets its first pull: balances, transactions, holdings and the day's
   record.

Matching never rests on the last four digits alone. An account is proposed as
the same as one already here only when exactly one of the client's own or
shared accounts agrees on institution and last four *and* on its holdings
(symbol by symbol) or its balance to the cent. Anything less certain is left
for the person to choose, and nothing is linked until they confirm.

Two feeds never write to one account: linking one that another link already
feeds is refused.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors import plaid_reader
from app.connectors.plaid_connector import PlaidClient, PlaidError, configured
from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from app.models.perf import DailyHolding, DailyValuation
from app.models.sleeve import Sleeve
from app.services.account_kind import KINDS, OWED, kind_from_plaid
from app.services.auth_service import AuthService
from app.services.connection_service import ConnectionService
from app.services.daily_capture_service import DailyCaptureService
from app.services.performance_build_service import last_market_day
from app.utils.secret_box import open_sealed, seal

SOURCE = "plaid"
# How far back the first pull reads investment transactions (Plaid's limit is
# 24 months; an institution may give less).
HISTORY_DAYS = 730
# Share counts within this of each other agree.
_AGREE = Decimal("0.01")

SAME, CHOOSE, NEW = "same", "choose", "new"


class PlaidLinkError(Exception):
    """A request that cannot be met, with the status a route should answer."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _words(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _last_fours(text: str) -> set:
    """Last four digits of every run of four or more digits in ``text``."""
    return {run[-4:] for run in re.findall(r"\d{4,}", text or "")}


class PlaidLinkService:
    def __init__(self, db: Session, client: Optional[PlaidClient] = None):
        self.db = db
        self.client = client or PlaidClient()
        self.connections = ConnectionService(db, connector=object())

    # ------------------------------------------------------------------
    # The plan's limit
    # ------------------------------------------------------------------

    def logins_used(self) -> int:
        """Plaid logins ever linked, across every client: a removed one keeps its place."""
        return (
            self.db.query(func.count(BrokerageConnection.id))
            .filter(BrokerageConnection.source == SOURCE)
            .scalar()
        )

    def logins_left(self) -> int:
        return max(settings.plaid_max_logins - self.logins_used(), 0)

    # ------------------------------------------------------------------
    # 1. Start
    # ------------------------------------------------------------------

    def start(self, client_id: str) -> Dict:
        if not configured():
            raise PlaidLinkError(503, "Linking with Plaid is not set up on this server.")
        if self.logins_left() <= 0:
            raise PlaidLinkError(
                409,
                "Every Plaid login the plan allows is in use. Ask your Achalara contact "
                "to add more before linking another.",
            )
        try:
            token = self.client.link_token(client_id, redirect_uri=settings.plaid_redirect_uri)
        except PlaidError as error:
            raise PlaidLinkError(502, error.message)
        return {
            "link_token": token["link_token"],
            "expiration": token.get("expiration"),
            "logins_left": self.logins_left(),
        }

    # ------------------------------------------------------------------
    # 2. Finish
    # ------------------------------------------------------------------

    def finish(self, client_id: str, public_token: str) -> Dict:
        if not configured():
            raise PlaidLinkError(503, "Linking with Plaid is not set up on this server.")
        if self.logins_left() <= 0:
            raise PlaidLinkError(409, "Every Plaid login the plan allows is in use.")
        try:
            exchanged = self.client.exchange(public_token)
            access_token, item_id = exchanged["access_token"], exchanged["item_id"]
            item = self.client.item(access_token).get("item", {})
            institution = ""
            if item.get("institution_id"):
                institution = (
                    self.client.institution(item["institution_id"])
                    .get("institution", {})
                    .get("name", "")
                )
            accounts = self.client.accounts(access_token).get("accounts", [])
        except PlaidError as error:
            raise PlaidLinkError(502, error.message)

        connection = (
            self.db.query(BrokerageConnection)
            .filter(
                BrokerageConnection.source == SOURCE,
                BrokerageConnection.external_connection_id == item_id,
            )
            .first()
        )
        if connection is None:
            connection = BrokerageConnection(
                client_id=client_id,
                source=SOURCE,
                external_user_id=client_id,
                external_connection_id=item_id,
            )
            self.db.add(connection)
        connection.institution = institution
        connection.status = "active"
        connection.access_token_enc = seal(access_token)
        connection.products = ",".join(
            item.get("products", []) or item.get("billed_products", [])
        ) or None
        expires = item.get("consent_expiration_time")
        connection.consent_expires_at = (
            datetime.fromisoformat(expires.replace("Z", "+00:00")) if expires else None
        )
        self.db.flush()
        for account in accounts:
            self._upsert_link(connection, account)
        self.db.commit()
        return self.found(client_id, connection.id)

    def _upsert_link(self, connection: BrokerageConnection, account: Dict) -> BrokerageAccount:
        link = (
            self.db.query(BrokerageAccount)
            .filter(
                BrokerageAccount.connection_id == connection.id,
                BrokerageAccount.external_account_ref == account["account_id"],
            )
            .first()
        )
        if link is None:
            link = BrokerageAccount(
                connection_id=connection.id,
                external_account_ref=account["account_id"],
                status="unmapped",
            )
            self.db.add(link)
        link.name = account.get("official_name") or account.get("name") or "Account"
        link.mask = (account.get("mask") or "")[-4:] or None
        link.number_last4 = link.mask
        link.persistent_account_id = account.get("persistent_account_id")
        link.plaid_type = account.get("type")
        link.plaid_subtype = account.get("subtype")
        # No account_fingerprint: it needs the full number, which Plaid does not
        # give for investment accounts. Matching goes by evidence instead.
        return link

    # ------------------------------------------------------------------
    # Proposals
    # ------------------------------------------------------------------

    def _connection(self, client_id: str, connection_id: str) -> BrokerageConnection:
        connection = self.db.get(BrokerageConnection, connection_id)
        if connection is None or connection.source != SOURCE or connection.client_id != client_id:
            raise PlaidLinkError(404, "Login not found")
        return connection

    def _access_token(self, connection: BrokerageConnection) -> str:
        return open_sealed(connection.access_token_enc or "")

    def found(self, client_id: str, connection_id: str) -> Dict:
        """The login's accounts, each with what is proposed for it."""
        connection = self._connection(client_id, connection_id)
        token = self._access_token(connection)
        try:
            accounts = {a["account_id"]: a for a in self.client.accounts(token).get("accounts", [])}
        except PlaidError as error:
            raise PlaidLinkError(502, error.message)
        holdings = self._plaid_holdings(token, accounts)
        candidates = self._candidates(client_id)
        links = (
            self.db.query(BrokerageAccount)
            .filter(BrokerageAccount.connection_id == connection.id)
            .order_by(BrokerageAccount.name)
            .all()
        )
        rows = []
        for link in links:
            plaid = accounts.get(link.external_account_ref, {})
            rows.append(self._proposal(connection, link, plaid, holdings.get(link.external_account_ref), candidates))
        return {
            "connection_id": connection.id,
            "institution": connection.institution,
            "logins_left": self.logins_left(),
            "accounts": rows,
        }

    def _plaid_holdings(self, token: str, accounts: Dict[str, Dict]) -> Dict[str, Dict[str, Decimal]]:
        """Each investment account's holdings by symbol (cash and options aside)."""
        if not any(a.get("type") == "investment" for a in accounts.values()):
            return {}
        try:
            reply = self.client.holdings(token)
        except PlaidError:
            return {}
        securities = {s["security_id"]: s for s in reply.get("securities", [])}
        out: Dict[str, Dict[str, Decimal]] = {}
        for h in reply.get("holdings", []):
            security = securities.get(h["security_id"], {})
            symbol = security.get("ticker_symbol")
            if not symbol or security.get("type") in ("cash", "derivative"):
                continue
            held = out.setdefault(h["account_id"], {})
            held[symbol] = held.get(symbol, Decimal(0)) + Decimal(str(h.get("quantity") or 0))
        return out

    def _candidates(self, client_id: str) -> List[Dict]:
        """The client's own and shared accounts, with what each can be told by."""
        out = []
        for account, shared in AuthService(self.db).accounts_for_client(client_id):
            links = (
                self.db.query(BrokerageAccount)
                .filter(BrokerageAccount.account_id == account.id)
                .all()
            )
            fours = set()
            institutions = set()
            if account.last_four:
                fours.add(account.last_four)
            fours |= _last_fours(account.name)
            if account.institution:
                institutions.add(_words(account.institution))
            for link in links:
                if link.mask:
                    fours.add(link.mask)
                fours |= _last_fours(link.name)
                if link.connection and link.connection.institution:
                    institutions.add(_words(link.connection.institution))
            out.append(
                {
                    "account": account,
                    "shared": shared,
                    "fours": fours,
                    "institutions": institutions,
                    "links": links,
                    "holdings": self._recorded_holdings(account.id),
                    "total": self._recorded_total(account.id),
                }
            )
        return out

    def _recorded_holdings(self, account_id: str) -> Optional[Dict[str, Decimal]]:
        last = (
            self.db.query(func.max(DailyHolding.as_of_date))
            .filter(DailyHolding.account_id == account_id)
            .scalar()
        )
        if last is None:
            return None
        held: Dict[str, Decimal] = {}
        for symbol, quantity in self.db.query(DailyHolding.symbol, DailyHolding.quantity).filter(
            DailyHolding.account_id == account_id, DailyHolding.as_of_date == last
        ):
            held[symbol] = held.get(symbol, Decimal(0)) + Decimal(str(quantity))
        return held

    def _recorded_total(self, account_id: str) -> Optional[Decimal]:
        row = (
            self.db.query(DailyValuation.total_value)
            .filter(
                DailyValuation.account_id == account_id,
                DailyValuation.sleeve_id.is_(None),
                DailyValuation.basis == "observed",
            )
            .order_by(DailyValuation.as_of_date.desc())
            .first()
        )
        return Decimal(str(row[0])) if row else None

    @staticmethod
    def _same_holdings(ours: Optional[Dict[str, Decimal]], theirs: Optional[Dict[str, Decimal]]) -> Optional[bool]:
        """Whether two lists of holdings agree, symbol by symbol; None when either
        is missing or empty (no evidence either way)."""
        if not ours or not theirs:
            return None
        symbols = set(ours) | set(theirs)
        return all(abs(ours.get(s, Decimal(0)) - theirs.get(s, Decimal(0))) <= _AGREE for s in symbols)

    def _proposal(
        self,
        connection: BrokerageConnection,
        link: BrokerageAccount,
        plaid: Dict,
        holdings: Optional[Dict[str, Decimal]],
        candidates: List[Dict],
    ) -> Dict:
        kind = kind_from_plaid(link.plaid_type, link.plaid_subtype, link.name)
        owed = kind in OWED
        balance = (plaid.get("balances") or {}).get("current")
        institution = _words(connection.institution)

        considered = []
        for c in candidates:
            account = c["account"]
            # The same Plaid account linked before (a relink): it is this one.
            relinked = any(
                (l.persistent_account_id and l.persistent_account_id == link.persistent_account_id)
                or (l.id != link.id and l.connection and l.connection.source == SOURCE
                    and l.external_account_ref == link.external_account_ref)
                for l in c["links"]
            )
            four = bool(link.mask) and link.mask in c["fours"]
            same_institution = bool(institution) and any(
                institution in i or i in institution for i in c["institutions"]
            )
            same_holdings = self._same_holdings(c["holdings"], holdings)
            same_balance = (
                balance is not None and c["total"] is not None
                and abs(c["total"] - Decimal(str(balance)) * (-1 if owed else 1)) < Decimal("0.005")
            )
            if relinked or four:
                considered.append(
                    {
                        "account_id": account.id,
                        "name": account.name,
                        "last_four": account.last_four or (sorted(c["fours"])[0] if c["fours"] else None),
                        "shared": c["shared"],
                        "relinked": relinked,
                        "same_last_four": four,
                        "same_institution": same_institution,
                        "same_holdings": same_holdings,
                        "same_balance": same_balance,
                    }
                )
        strong = [
            c for c in considered
            if c["relinked"]
            or (c["same_last_four"] and c["same_institution"] and (c["same_holdings"] or c["same_balance"]))
        ]
        if link.status in ("mapped", "matched") and link.account_id:
            action, chosen = SAME, link.account_id
        elif len(strong) == 1:
            action, chosen = SAME, strong[0]["account_id"]
        elif considered:
            action, chosen = CHOOSE, None
        else:
            action, chosen = NEW, None
        return {
            "link_id": link.id,
            "name": link.name,
            "mask": link.mask,
            "plaid_type": link.plaid_type,
            "plaid_subtype": link.plaid_subtype,
            "kind": kind,
            "owed": owed,
            "balance": float(balance) if balance is not None else None,
            "status": link.status,
            "proposal": action,
            "account_id": chosen,
            "candidates": considered,
        }

    # ------------------------------------------------------------------
    # 3. Confirm
    # ------------------------------------------------------------------

    def confirm(self, client_id: str, connection_id: str, choices: List[Dict]) -> Dict:
        """Act on the person's choice for each account: ``link`` to one of the
        client's accounts, add as ``new`` (of the ``kind`` chosen), or ``skip``."""
        connection = self._connection(client_id, connection_id)
        visible = {a.id for a, _ in AuthService(self.db).accounts_for_client(client_id)}
        pulled: List[BrokerageAccount] = []
        outcome = {"linked": 0, "added": 0, "skipped": 0, "waiting": 0}
        for choice in choices:
            link = self.db.get(BrokerageAccount, choice.get("link_id"))
            if link is None or link.connection_id != connection.id:
                raise PlaidLinkError(404, "Account not found in this login")
            action = choice.get("action")
            kind = choice.get("kind") or kind_from_plaid(link.plaid_type, link.plaid_subtype, link.name)
            if kind not in KINDS:
                raise PlaidLinkError(422, f"Unknown kind {kind!r}")
            if action == "skip":
                link.status = "ignored"
                outcome["skipped"] += 1
            elif action == "link":
                account = self.db.get(Account, choice.get("account_id"))
                if account is None or account.id not in visible:
                    raise PlaidLinkError(404, "Account not found")
                if self._linked_elsewhere(account.id, link.id):
                    # Two feeds never write to one account. A second login's ids
                    # for the same transactions differ, so it would count them twice.
                    raise PlaidLinkError(409, "This account is already linked")
                self._describe(account, connection, link, kind)
                link.account_id = account.id
                link.default_sleeve_id = self._sleeve(account)
                link.status = "mapped"
                pulled.append(link)
                outcome["linked"] += 1
            elif action == "new":
                account = Account(
                    client_id=client_id,
                    name=link.name,
                    description=f"Linked through Plaid ({connection.institution or 'institution'})",
                )
                self.db.add(account)
                self.db.flush()
                self._describe(account, connection, link, kind)
                link.account_id = account.id
                link.default_sleeve_id = self._sleeve(account)
                link.status = "mapped"
                pulled.append(link)
                outcome["added"] += 1
            else:
                raise PlaidLinkError(422, "Choose link, new or skip for each account")
        self.db.commit()
        for link in pulled:
            self.first_pull(link)
        return outcome

    @staticmethod
    def _describe(account: Account, connection: BrokerageConnection, link: BrokerageAccount, kind: str) -> None:
        account.kind = kind
        if connection.institution:
            account.institution = connection.institution
        if link.mask:
            account.last_four = link.mask

    def _linked_elsewhere(self, account_id: str, link_id: str) -> bool:
        """Whether another link already feeds the account."""
        return (
            self.db.query(BrokerageAccount.id)
            .filter(
                BrokerageAccount.account_id == account_id,
                BrokerageAccount.status == "mapped",
                BrokerageAccount.id != link_id,
            )
            .first()
            is not None
        )

    def _sleeve(self, account: Account) -> str:
        sleeve = self.db.query(Sleeve).filter(Sleeve.account_id == account.id).first()
        if sleeve is None:
            sleeve = Sleeve(
                account_id=account.id, strategy_id=self.connections._default_strategy().id
            )
            self.db.add(sleeve)
            self.db.flush()
        return sleeve.id

    # ------------------------------------------------------------------
    # First pull
    # ------------------------------------------------------------------

    def first_pull(self, link: BrokerageAccount, today: Optional[date] = None) -> Dict:
        """Everything the login offers for one newly linked account: its
        transactions, then its day as the institution reports it."""
        today = today or date.today()
        connection = link.connection
        token = self._access_token(connection)
        owed = kind_from_plaid(link.plaid_type, link.plaid_subtype, link.name) in OWED
        try:
            accounts = {a["account_id"]: a for a in self.client.accounts(token).get("accounts", [])}
            plaid = accounts.get(link.external_account_ref, {})
            if link.plaid_type == "investment":
                history = self.client.investment_transactions(
                    token, today - timedelta(days=HISTORY_DAYS), today
                )
                securities = {s["security_id"]: s for s in history.get("securities", [])}
                rows = [r for r in history.get("investment_transactions", []) if r.get("account_id") == link.external_account_ref]
                batch = plaid_reader.read_investment_transactions(rows, securities)
                held = self.client.holdings(token)
                figures = plaid_reader.read_holdings(
                    plaid, held.get("holdings", []),
                    {s["security_id"]: s for s in held.get("securities", [])},
                )
            else:
                rows: List[Dict] = []
                if link.plaid_type in ("depository", "credit"):
                    synced = self.client.transactions_sync(token, connection.transactions_cursor or "")
                    rows = [r for r in synced.get("added", []) if r.get("account_id") == link.external_account_ref]
                batch = plaid_reader.read_bank_transactions(rows)
                figures = plaid_reader.read_balance(plaid, owed)
        except PlaidError as error:
            raise PlaidLinkError(502, error.message)

        link.cash_balance = figures.cash
        link.cash_balance_at = datetime.now(timezone.utc)
        self.db.commit()
        result = self.connections.ingest_batch(link, batch) if (batch.trades or batch.cash or batch.raw) else {}
        # Plaid was asked for every transaction through today.
        link.transactions_synced_through = today
        link.last_synced_at = datetime.now(timezone.utc)
        self.db.commit()
        DailyCaptureService(self.db, self.connections).record(
            link,
            figures.day or last_market_day(today),
            figures.positions,
            figures.cash,
            figures.total,
            valuation_adjustment=Decimal(0),
        )
        return result
