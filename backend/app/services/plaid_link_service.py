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
from app.models.client import Client
from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from app.models.perf import DailyHolding, DailyValuation
from app.services import card_details
from app.services.account_kind import KINDS, OWED, kind_from_plaid
from app.services import sleeve_routing
from app.services.sharing_service import SharingService
from app.services.auth_service import AuthService
from app.services.connection_service import ConnectionService
from app.services.daily_capture_service import DailyCaptureService
from app.services.performance_build_service import last_market_day
from app.utils.secret_box import SecretBoxError, open_sealed, seal

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
    # Repair: signing in again to a login Plaid has stopped reading
    # ------------------------------------------------------------------

    def repair_start(
        self, client_id: str, connection_id: str, select_accounts: bool = False
    ) -> Dict:
        """A token that opens Plaid Link in update mode for one of the client's
        logins: they sign in again to the same login, so no new place on the
        plan is used and its history carries on."""
        if not configured():
            raise PlaidLinkError(503, "Linking with Plaid is not set up on this server.")
        connection = self._connection(client_id, connection_id)
        try:
            token = self.client.link_token(
                client_id,
                redirect_uri=settings.plaid_redirect_uri,
                access_token=self._access_token(connection),
                select_accounts=select_accounts,
            )
        except PlaidError as error:
            raise PlaidLinkError(502, error.message)
        return {
            "link_token": token["link_token"],
            "expiration": token.get("expiration"),
            "logins_left": self.logins_left(),
        }

    # A login refreshed this recently is not asked again: Plaid updates
    # investment accounts about once a day, and each call is counted.
    REFRESH_AFTER = timedelta(minutes=10)

    def refresh_mine(
        self, client_id: str, today: Optional[date] = None, now: Optional[datetime] = None
    ) -> Dict:
        """The refresh now, for the client's own logins only (never a spouse's
        or a shared one). A login checked in the last few minutes, or one that
        needs signing in again, is left as it is. It records the day before
        only where the morning job would (``records_a_day``): later, a balance
        is not where that day ended."""
        from app.services.plaid_refresh_service import PlaidRefreshService, records_a_day

        now = now or datetime.now(timezone.utc)
        record = records_a_day(now)
        outcome = {"refreshed": 0, "up_to_date": 0, "needs_sign_in": 0, "failed": 0}
        logins = (
            self.db.query(BrokerageConnection)
            .filter(BrokerageConnection.client_id == client_id, BrokerageConnection.source == SOURCE)
            .all()
        )
        refresher = PlaidRefreshService(self.db, self.client)
        for login in logins:
            if login.status != "active":
                outcome["needs_sign_in"] += 1
                continue
            checked = login.status_checked_at
            if checked is not None and checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            if checked is not None and now - checked < self.REFRESH_AFTER:
                outcome["up_to_date"] += 1
                continue
            try:
                result = refresher.refresh(login, today, record)
            except Exception:  # noqa: BLE001 - one login never stops the rest
                self.db.rollback()
                outcome["failed"] += 1
                continue
            outcome["needs_sign_in" if result == "needs signing in" else "refreshed"] += 1
        return {**outcome, "at": now}

    def repaired(self, client_id: str, connection_id: str, today: Optional[date] = None) -> Dict:
        """After the client signed in again: ask Plaid whether the login reads
        once more, and if so mark it active and bring its accounts up to date."""
        from app.services.plaid_refresh_service import (
            NEEDS_SIGN_IN,
            PlaidRefreshService,
            records_a_day,
        )

        connection = self._connection(client_id, connection_id)
        now = datetime.now(timezone.utc)
        try:
            item = self.client.item(self._access_token(connection)).get("item") or {}
        except PlaidError as error:
            raise PlaidLinkError(502, error.message)
        problem = (item.get("error") or {}).get("error_code")
        connection.status_checked_at = now
        if problem in NEEDS_SIGN_IN:
            self.db.commit()
            return {"status": "needs signing in"}
        connection.status = "active"
        connection.disabled_at = None
        if item.get("consent_expiration_time"):
            connection.consent_expires_at = item["consent_expiration_time"]
        self.db.commit()
        try:
            PlaidRefreshService(self.db, self.client).refresh(
                connection, today, records_a_day()
            )
        except Exception:  # noqa: BLE001 - the morning refresh tries again
            self.db.rollback()
        return {"status": "active"}

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

    def discover(self, client_id: str, connection_id: str) -> Dict:
        """Ask Plaid what the login shares now, and keep a row for each account
        not seen before (left unmapped, for the client to choose). Accounts
        already known, mapped or not, are never touched. Returns what ``found``
        does, so the client can choose at once."""
        self.discover_new(client_id, connection_id)
        self.db.commit()
        return self.found(client_id, connection_id)

    def discover_new(self, client_id: str, connection_id: str) -> int:
        """How many accounts Plaid shares that had no row here; their rows are
        added (not committed). Raises when the login cannot be read."""
        from app.services.plaid_refresh_service import NEEDS_SIGN_IN

        connection = self._connection(client_id, connection_id)
        try:
            token = self._access_token(connection)
        except SecretBoxError:
            raise PlaidLinkError(
                503,
                "The saved sign-in for this login cannot be opened on this server. "
                "Ask the person who runs Achalara; signing in again may be needed.",
            )
        try:
            shared = self.client.accounts(token).get("accounts", [])
        except PlaidError as error:
            if error.code in NEEDS_SIGN_IN:
                raise PlaidLinkError(409, "This login needs you to sign in again first.")
            raise PlaidLinkError(502, error.message)
        known = {
            ref
            for (ref,) in self.db.query(BrokerageAccount.external_account_ref).filter(
                BrokerageAccount.connection_id == connection.id
            )
        }
        added = 0
        for account in shared:
            if account["account_id"] not in known:
                self._upsert_link(connection, account)
                added += 1
        connection.status_checked_at = datetime.now(timezone.utc)
        self.db.flush()
        return added

    def discover_mine(self, client_id: str) -> Dict:
        """``discover_new`` for each of the client's own logins that Plaid still
        reads; one login that cannot be read never stops the rest."""
        outcome = {"checked": 0, "new_accounts": 0, "needs_sign_in": 0, "failed": 0}
        logins = (
            self.db.query(BrokerageConnection)
            .filter(BrokerageConnection.client_id == client_id, BrokerageConnection.source == SOURCE)
            .all()
        )
        for login in logins:
            if login.status != "active":
                outcome["needs_sign_in"] += 1
                continue
            try:
                outcome["new_accounts"] += self.discover_new(client_id, login.id)
                outcome["checked"] += 1
                self.db.commit()
            except PlaidLinkError as error:
                self.db.rollback()
                outcome["needs_sign_in" if error.status_code == 409 else "failed"] += 1
        return outcome

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
            rows.append(self._proposal(connection, link, plaid, holdings.get(link.external_account_ref), candidates, client_id))
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

    def _fed_by(self, candidate: Dict, link: BrokerageAccount, viewer_id: str) -> Optional[Dict]:
        """The login that already feeds this candidate account, if another one does."""
        for other in candidate["links"]:
            if other.status == "mapped" and other.id != link.id and other.connection is not None:
                owner = self.db.get(Client, other.connection.client_id)
                return {
                    "institution": other.connection.institution or "",
                    "owner_name": owner.name if owner else None,
                    "own": other.connection.client_id == viewer_id,
                }
        return None

    def _proposal(
        self,
        connection: BrokerageConnection,
        link: BrokerageAccount,
        plaid: Dict,
        holdings: Optional[Dict[str, Decimal]],
        candidates: List[Dict],
        viewer_id: str = "",
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
                        "fed_by": self._fed_by(c, link, viewer_id),
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
        fed_by = None
        if action == SAME and link.status not in ("mapped", "matched"):
            fed_by = next((c["fed_by"] for c in considered if c["account_id"] == chosen), None)
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
            # Set when the account this one is already gets its figures through
            # another login: it needs no second feed (two feeds never write to one account).
            "fed_by": fed_by,
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
                    raise PlaidLinkError(
                        409,
                        f"{link.name}{f' ··{link.mask}' if link.mask else ''} already gets its "
                        "figures through another login, so it is not added again. Leave it out "
                        "and add the rest.",
                    )
                self._describe(account, connection, link, kind)
                link.account_id = account.id
                link.default_sleeve_id, link.sleeve_routes = self._sleeves(account)
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
                self._ownership(account, client_id, choice)
                self._describe(account, connection, link, kind)
                link.account_id = account.id
                link.default_sleeve_id, link.sleeve_routes = self._sleeves(account)
                link.status = "mapped"
                pulled.append(link)
                outcome["added"] += 1
            else:
                raise PlaidLinkError(422, "Choose link, new or skip for each account")
        self.db.commit()
        for link in pulled:
            self.first_pull(link)
        return outcome

    def _ownership(self, account: Account, client_id: str, choice: Dict) -> None:
        """Whose a new account is, who else sees it and its cost basis, as chosen
        while linking. The person linking controls it until its owner signs in.
        Defaults: theirs, shared with nobody, first in first out."""
        sharing = SharingService(self.db, client_id)
        owners = choice.get("owner_ids") or [client_id]
        if choice.get("cost_basis"):
            account.cost_basis_method = choice["cost_basis"]
        account.linked_by_id = client_id
        self.db.flush()
        if owners != [client_id] or choice.get("held_for") or choice.get("share_with") or choice.get("share_advisor"):
            # The linker owns it as created, so the sharing rules apply to them;
            # the real owners are set last, as the linker may not control it after.
            if choice.get("held_for"):
                sharing.hold_for(account.id, choice["held_for"])
            for person_id in choice.get("share_with") or []:
                sharing.share(account.id, person_id=person_id)
            if choice.get("share_advisor"):
                sharing.share(account.id, advisor=True)
            if owners != [client_id]:
                sharing.set_owners(account.id, owners, keep_view=True)

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

    def _sleeves(self, account: Account):
        """The account's sleeves, one per strategy (Stocks, ETFs, Mutual funds,
        Options, Cash), with the default sleeve and the routes that send each
        kind of security to its own. A bank, card or loan has only Cash.
        Feed sleeves are real brokerage activity: sales take the oldest shares
        first (round-trip pairing, meant for strategy sheets, drops a sale of
        shares bought before the history and keeps every later buy open)."""
        default, routes = sleeve_routing.set_up(self.db, account)
        self.db.flush()
        return default, routes

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
        if link.plaid_type == "credit":
            liabilities = card_details.credit_liabilities(self.client, token)
            card_details.save(
                self.db, link.account_id,
                card_details.read(plaid, liabilities.get(link.external_account_ref)),
            )
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
