"""SnapTrade brokerage aggregator, behind the connector interface.

Reads accounts, positions and transactions from any brokerage a client links
through SnapTrade's hosted Connection Portal. The SnapTrade SDK, its auth
model and its payload shapes stay sealed in this module — upstream code sees
only the normalized types.

Two things about this source shape the design:

* Transactions are cached, refreshed once a day and delayed by a day; intraday
  is unavailable. So ``supports_realtime`` is False and freshness is "daily",
  and callers should sync on SnapTrade's webhooks rather than polling.
* Credentials never reach us. The client authenticates with their brokerage on
  SnapTrade's hosted page; we only ever hold the reference it hands back.

Auth comes in two flavors. A Personal key addresses the key owner's own
accounts and needs no per-user registration; a Commercial key registers each
end user and issues a ``userSecret`` per user, which is unrecoverable once
lost. ``SnapTradeCredentials`` carries whichever applies.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from app.config import settings
from app.connectors.base import ConnectorCapabilities
from app.connectors.models import (
    ActivityBatch,
    Connection,
    ConnectionResult,
    ConnectionStatus,
    LinkSession,
    NormalizedCashActivity,
    NormalizedPosition,
    NormalizedTrade,
    NotSupported,
    RawAccount,
    RawActivity,
    TradeAction,
    is_option_symbol,
)

logger = logging.getLogger(__name__)

SOURCE = "snaptrade"

# Activity types that represent an executed trade. Money movements map through
# _CASH_TYPES; anything in neither is skipped and counted.
#
# REI (dividend reinvestment) is a real share purchase: Vanguard reports the
# shares bought in ``units`` with a per-share ``price``. Leaving it out makes
# held quantity and cost basis drift from the brokerage's. REI rows with zero
# units (a money-market sweep fund such as Cash Plus) carry no shares and are
# skipped as cash.
_TRADE_TYPES = {
    "BUY": TradeAction.BUY,
    "SELL": TradeAction.SELL,
    "REI": TradeAction.BUY,
}

# Non-trade activity that moves money, mapped onto our cash activity types.
# INCOME is fund income Vanguard reports apart from DIVIDEND; INTEREST CHARGE
# is margin interest, a cost. Cash in lieu is proceeds for a fractional share
# lost in a corporate action — real cash, but not income.
_CASH_TYPES = {
    "DIVIDEND": "DIVIDEND",
    "INTEREST": "INTEREST",
    "INCOME": "INTEREST",
    "FEE": "FEE",
    "INTEREST CHARGE": "FEE",
    "WITHHOLDING": "WITHHOLDING",
    "CONTRIBUTION": "CONTRIBUTION",
    "DEPOSIT": "CONTRIBUTION",
    "WITHDRAWAL": "WITHDRAWAL",
    "WIRE OUT": "WITHDRAWAL",
    "TRANSFER": "TRANSFER",
    "TRANSFER (INCOMING)": "TRANSFER",
    "TRANSFER (OUTGOING)": "TRANSFER",
    "CORP ACTION (CASH IN LIEU)": "OTHER",
}

# Cash that crosses the account boundary, as opposed to income earned inside it.
_EXTERNAL_CASH_TYPES = {"CONTRIBUTION", "WITHDRAWAL", "TRANSFER"}

# Activity that changes share counts without a trade. Nothing models these
# yet, so they are skipped and counted; holdings reconciliation shows the
# resulting drift.
_CORPORATE_ACTION_TYPES = {
    "SPLIT",
    "STOCK_DIVIDEND",
    "CORP ACTION (MERGER)",
}

# How an option position ends without a closing trade. The contracts leave the
# account at no price: an expiry is worthless, and an assignment's cash moves
# on the separate stock trade it triggers.
_OPTION_CLOSE_TYPES = {"ASSIGNMENT", "EXPIRED"}

# An option contract covers this many shares, and is quoted per share.
_CONTRACT_MULTIPLIER = Decimal(100)

# SnapTrade security type codes (``symbol.type.code``) and the ``kind`` a live
# holding's instrument carries, mapped onto our vocabulary.
_SECURITY_TYPES = {
    "et": "ETF",
    "etf": "ETF",
    "cs": "STOCK",
    "stock": "STOCK",
    "equity": "STOCK",
    "ad": "ADR",
    "adr": "ADR",
    "oef": "MUTUAL_FUND",
    "mutual_fund": "MUTUAL_FUND",
    "cef": "CLOSED_END_FUND",
    "ps": "PREFERRED",
}

_ETF_WORD = re.compile(r"\bETFS?\b", re.IGNORECASE)

# Cash moving between the settlement balance and its sweep fund. Internal to
# the account, so neither a trade nor a cash activity.
_SWEEP_TYPES = {"SWEEP IN", "SWEEP OUT"}

# SnapTrade caps this endpoint at 1000 rows per call.
_MAX_PAGE = 1000


@dataclass(frozen=True)
class SnapTradeCredentials:
    """Per-connection auth. ``user_secret`` is empty for Personal keys."""

    user_id: str
    user_secret: str = ""

    def as_kwargs(self) -> Dict[str, str]:
        kwargs = {"user_id": self.user_id}
        if self.user_secret:
            kwargs["user_secret"] = self.user_secret
        return kwargs


class SnapTradeConnector:
    """Reads brokerage data for accounts linked through SnapTrade."""

    capabilities = ConnectorCapabilities(
        can_read_positions=True,
        can_read_transactions=True,
        # Trading exists in the SnapTrade API but stays dormant until Grow.
        can_trade=False,
        # Transactions are day-delayed at source; nothing here is live.
        supports_realtime=False,
        supports_historical_backfill=True,
        # Webhooks drive syncing, so callers need not poll.
        requires_manual_refresh=False,
        data_freshness="daily",
    )

    def __init__(self, client: Any = None, commercial: bool = False):
        self._client = client
        self._client_id = settings.snaptrade_client_id
        self._consumer_key = settings.snaptrade_consumer_key
        # Which auth mode the SDK is built with. Personal addresses the key
        # owner's own accounts; Commercial registers end users and issues a
        # userSecret per user. They are distinct API keys, not a flag on one.
        self._commercial = commercial

    # --- configuration -----------------------------------------------------

    def is_configured(self) -> bool:
        """Whether credentials exist for live calls.

        Callers ask this instead of reaching for the vendor's key settings.
        """
        if self._client is not None:
            return True
        return bool(self._client_id and self._consumer_key)

    @property
    def client(self) -> Any:
        """The underlying SDK client, constructed on first use.

        Built lazily so importing this module never requires credentials, and
        so tests can inject a stub through the constructor.
        """
        if self._client is None:
            if not self.is_configured():
                raise NotSupported(
                    "SnapTrade is not configured; set SNAPTRADE_CLIENT_ID and "
                    "SNAPTRADE_CONSUMER_KEY"
                )
            from snaptrade_client import SnapTrade, SnapTradeAuth

            build_auth = (
                SnapTradeAuth.commercial_api_key
                if self._commercial
                else SnapTradeAuth.personal_api_key
            )
            self._client = SnapTrade(
                auth=build_auth(
                    consumer_key=self._consumer_key, client_id=self._client_id
                )
            )
        return self._client

    # --- linking lifecycle -------------------------------------------------

    def register_user(self, client_id: str) -> SnapTradeCredentials:
        """Register an Achalara client as a SnapTrade user (Commercial only).

        The returned ``user_secret`` cannot be retrieved again — persist it
        encrypted immediately or the client has to re-link from scratch.
        """
        response = self.client.authentication.register_snap_trade_user(
            body={"userId": client_id}
        )
        body = _body(response)
        secret = _get(body, "userSecret") or ""
        if not secret:
            raise NotSupported("SnapTrade did not return a userSecret on register")
        return SnapTradeCredentials(user_id=client_id, user_secret=secret)

    def initiate_link(
        self,
        client_id: str,
        redirect_uri: str,
        credentials: Optional[SnapTradeCredentials] = None,
    ) -> LinkSession:
        """Create a hosted Connection Portal session for a client.

        The returned URL expires in about five minutes, so hand it straight to
        the browser rather than storing it. ``connection_type="read"`` keeps
        this read-only: trade scopes are not requested until Grow.
        """
        creds = credentials or SnapTradeCredentials(user_id=client_id)
        response = self.client.authentication.login_snap_trade_user(
            connection_type="read",
            custom_redirect=redirect_uri or None,
            **creds.as_kwargs(),
        )
        body = _body(response)
        url = _get(body, "redirectURI") or _get(body, "redirect_uri") or ""
        if not url:
            raise NotSupported("SnapTrade did not return a Connection Portal URL")
        return LinkSession(redirect_url=url, session_ref=creds.user_id, raw=_dict(body))

    def complete_link(self, callback_payload: dict) -> ConnectionResult:
        """Not applicable: SnapTrade has no code-for-token exchange.

        The portal redirect is cosmetic; a connection becomes real when the
        ``CONNECTION_ADDED`` webhook arrives (or when it shows up in
        :meth:`list_connections`). The webhook handler owns that discovery, so
        there is nothing to exchange here.
        """
        raise NotSupported(
            "SnapTrade has no callback exchange; connections are discovered via "
            "the CONNECTION_ADDED webhook or list_connections()"
        )

    def list_connections(
        self, client_id: str, credentials: Optional[SnapTradeCredentials] = None
    ) -> List[Connection]:
        """List the brokerage connections a client has authorized."""
        creds = credentials or SnapTradeCredentials(user_id=client_id)
        response = self.client.connections.list_brokerage_authorizations(
            **creds.as_kwargs()
        )
        out: List[Connection] = []
        for item in _rows(_body(response)):
            out.append(
                Connection(
                    connection_id=str(_get(item, "id") or ""),
                    institution=_institution(item),
                    status=(
                        "active" if _get(item, "disabled") is False else "disconnected"
                    ),
                    raw=_dict(item),
                )
            )
        return out

    def refresh_connection(
        self, connection_id: str, credentials: Optional[SnapTradeCredentials] = None
    ) -> ConnectionStatus:
        """Ask SnapTrade to re-pull holdings for a connection now.

        Only meaningful on Daily plans, and may be billed per call, so this is
        a user-initiated action rather than something to loop over.
        """
        credentials = credentials or _default_credentials()
        response = self.client.connections.refresh_brokerage_authorization(
            authorization_id=connection_id, **credentials.as_kwargs()
        )
        body = _body(response)
        return ConnectionStatus(
            connection_id=connection_id,
            status="refreshing",
            raw=_dict(body),
        )

    def remove_connection(
        self, connection_id: str, credentials: Optional[SnapTradeCredentials] = None
    ) -> None:
        """Revoke a connection at SnapTrade.

        Exposing this to end users is required by SnapTrade's launch checklist.
        """
        credentials = credentials or _default_credentials()
        self.client.connections.delete_connection(
            authorization_id=connection_id, **credentials.as_kwargs()
        )

    # --- reading -----------------------------------------------------------

    def fetch_accounts(
        self, connection_id: str, credentials: Optional[SnapTradeCredentials] = None
    ) -> List[RawAccount]:
        """List every account under a client's linked logins.

        One brokerage login commonly exposes several accounts (brokerage, IRA,
        joint), each of which maps to its own Achalara ``Account``.
        """
        creds = credentials or SnapTradeCredentials(user_id=connection_id)
        response = self.client.account_information.list_user_accounts(
            **creds.as_kwargs()
        )
        out: List[RawAccount] = []
        for item in _rows(_body(response)):
            out.append(
                RawAccount(
                    external_ref=str(_get(item, "id") or ""),
                    name=str(_get(item, "name") or _get(item, "number") or "Account"),
                    account_number=_opt_str(_get(item, "number")),
                    institution=_institution(item),
                    connection_ref=_opt_str(_get(item, "brokerage_authorization")),
                    initial_sync_completed=_initial_sync_completed(item),
                    transactions_synced_through=_synced_through(item),
                    raw=_dict(item),
                )
            )
        return out

    def fetch_cash_balance(
        self,
        connection_id: str,
        account_ref: str,
        credentials: Optional[SnapTradeCredentials] = None,
    ) -> Optional[Decimal]:
        """Cash the account holds now, or None if the source does not say.

        Sums the balance across currencies as reported; accounts here are
        single-currency, and a multi-currency one would need FX to do better.
        """
        creds = credentials or SnapTradeCredentials(user_id=connection_id)
        response = self.client.account_information.get_user_account_balance(
            account_id=account_ref, **creds.as_kwargs()
        )
        total = None
        for item in _rows(_body(response)):
            cash = _decimal(_get(item, "cash"))
            if cash is not None:
                total = (total or Decimal(0)) + cash
        return total

    def fetch_positions(
        self,
        connection_id: str,
        account_ref: str,
        credentials: Optional[SnapTradeCredentials] = None,
    ) -> List[NormalizedPosition]:
        """Current holdings for one account.

        The live API returns ``{"results": [...]}`` with the security under
        ``instrument`` and a per-unit ``cost_basis`` — not the SDK model's
        ``symbol`` / ``average_purchase_price``. Both shapes are read, live
        first. ``cost_basis`` is absent for lots bought since SnapTrade's last
        transaction sync; those report an ``avg_cost`` of 0 until it catches up.
        """
        creds = credentials or SnapTradeCredentials(user_id=connection_id)
        response = self.client.account_information.get_all_account_positions(
            account_id=account_ref, **creds.as_kwargs()
        )
        as_of = datetime.now(timezone.utc)
        out: List[NormalizedPosition] = []
        for item in _rows(_body(response)):
            instrument = _get(item, "instrument")
            symbol = _symbol_ticker(
                instrument if instrument is not None else _get(item, "symbol")
            )
            units = _decimal(_get(item, "units"))
            if units is None:
                units = _decimal(_get(item, "fractional_units"))
            if not symbol or units is None:
                logger.warning(
                    "Skipping SnapTrade position: incomplete (symbol=%r units=%r)",
                    symbol,
                    _get(item, "units"),
                )
                continue
            cost = _get(item, "cost_basis")
            if cost is None:
                cost = _get(item, "average_purchase_price")
            out.append(
                NormalizedPosition(
                    symbol=symbol,
                    quantity=units,
                    avg_cost=_decimal(cost) or Decimal("0"),
                    currency=_currency_code(_get(item, "currency")),
                    market_price=_decimal(_get(item, "price")),
                    as_of=as_of,
                    raw=_dict(item),
                )
            )
        return out

    def fetch_transactions(
        self,
        connection_id: str,
        account_ref: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        credentials: Optional[SnapTradeCredentials] = None,
    ) -> List[NormalizedTrade]:
        """Executed trades for one account, oldest first.

        The trade half of :meth:`fetch_activities`, for callers that only want
        the interface's transactions.
        """
        return self.fetch_activities(
            connection_id, account_ref, since, until, credentials
        ).trades

    def fetch_activities(
        self,
        connection_id: str,
        account_ref: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        credentials: Optional[SnapTradeCredentials] = None,
    ) -> ActivityBatch:
        """Trades and cash activity for one account, oldest first.

        Pages through SnapTrade's offset pagination. Rows that cannot be mapped
        are skipped and tallied by reason rather than failing the whole sync —
        one malformed row should not block a day's trades.
        """
        creds = credentials or SnapTradeCredentials(user_id=connection_id)
        batch = ActivityBatch()
        offset = 0
        while True:
            response = self.client.account_information.get_account_activities(
                account_id=account_ref,
                start_date=_as_date(since),
                end_date=_as_date(until),
                offset=offset,
                limit=_MAX_PAGE,
                **creds.as_kwargs(),
            )
            body = _body(response)
            rows = _rows(body)
            for row in rows:
                self._classify(row, account_ref, batch)

            offset += len(rows)
            total = _total(body)
            if not rows or (total is not None and offset >= total):
                break
            if total is None and len(rows) < _MAX_PAGE:
                break

        return self._finish(batch)

    def parse_activities(self, rows: List[Any], account_ref: str) -> ActivityBatch:
        """Read activity rows that were fetched earlier and kept verbatim.

        The same mapping as :meth:`fetch_activities`, minus the network call,
        so stored rows can be re-read when the mapping rules change. The
        returned ``raw`` entries line up one-to-one with ``rows``.
        """
        batch = ActivityBatch()
        for row in rows:
            self._classify(row, account_ref, batch)
        return self._finish(batch)

    @staticmethod
    def _finish(batch: ActivityBatch) -> ActivityBatch:
        _disambiguate_repeats(batch.trades)
        _disambiguate_repeats(batch.cash)
        # SnapTrade returns newest first; ingestion reads chronologically.
        batch.trades.sort(key=lambda t: t.executed_at)
        batch.cash.sort(key=lambda c: c.occurred_at)
        return batch

    def _classify(self, row: Any, account_ref: str, batch: ActivityBatch) -> None:
        """Route one activity into the batch as a trade, cash, or a skip.

        Whatever happens to it, the row is also kept verbatim in ``batch.raw``.
        """
        outcome = self._outcome(row, account_ref, batch)
        if outcome.startswith("skipped:"):
            reason = outcome.split(":", 1)[1]
            batch.skipped[reason] = batch.skipped.get(reason, 0) + 1
        occurred = _parse_datetime(_get(row, "trade_date"))
        batch.raw.append(
            RawActivity(
                source_id=str(_get(row, "id") or ""),
                type=str(_get(row, "type") or ""),
                occurred_on=occurred.date() if occurred else None,
                symbol=_symbol_ticker(_get(row, "symbol")) or None,
                outcome=outcome,
                cash_amount=(
                    Decimal(0)
                    if outcome == "skipped:sweep"
                    else _decimal(_get(row, "amount")) or Decimal(0)
                ),
                is_external_flow=_CASH_TYPES.get(str(_get(row, "type") or "").upper())
                in _EXTERNAL_CASH_TYPES,
                payload=_jsonable(row),
            )
        )

    def _outcome(self, row: Any, account_ref: str, batch: ActivityBatch) -> str:
        """Add the row to the batch if it maps, and say what became of it."""
        raw_type = str(_get(row, "type") or "").upper()

        if raw_type in _TRADE_TYPES:
            # A reinvestment into a sweep fund moves cash, not shares.
            if raw_type == "REI" and not _decimal(_get(row, "units")):
                return "skipped:sweep"
            if _is_option(row):
                trade = self._to_option_trade(row, account_ref)
                if trade is None:
                    return "skipped:incomplete"
                batch.trades.append(trade)
                return "trade"
            trade = self._to_trade(row, account_ref)
            if trade is None:
                return "skipped:incomplete"
            batch.trades.append(trade)
            how = _security_type(row)[1]
            batch.security_type_sources[how] = (
                batch.security_type_sources.get(how, 0) + 1
            )
            return "trade"
        if raw_type in _CASH_TYPES:
            activity = self._to_cash(row, account_ref, _CASH_TYPES[raw_type])
            if activity is None:
                return "skipped:incomplete"
            batch.cash.append(activity)
            return "cash"
        if raw_type in _OPTION_CLOSE_TYPES:
            trade = self._to_option_trade(row, account_ref) if _is_option(row) else None
            if trade is None:
                return "skipped:corporate_action"
            batch.trades.append(trade)
            return "trade"
        if raw_type in _CORPORATE_ACTION_TYPES:
            return "skipped:corporate_action"
        if raw_type in _SWEEP_TYPES:
            return "skipped:sweep"
        logger.warning("SnapTrade activity type %r not recognized; skipping", raw_type)
        return "skipped:unrecognized"

    def _to_cash(
        self, row: Any, account_ref: str, cash_type: str
    ) -> Optional[NormalizedCashActivity]:
        """Map one non-trade activity to a cash activity, or None to skip."""
        amount = _decimal(_get(row, "amount"))
        occurred_at = _parse_datetime(_get(row, "trade_date"))
        if not amount or occurred_at is None:
            logger.warning(
                "Skipping SnapTrade cash activity %s: incomplete "
                "(amount=%r trade_date=%r)",
                _get(row, "id"),
                _get(row, "amount"),
                _get(row, "trade_date"),
            )
            return None
        symbol = _symbol_ticker(_get(row, "symbol")) or None
        return NormalizedCashActivity(
            external_id=(
                f"{SOURCE}:{account_ref}:{occurred_at.date().isoformat()}:cash:"
                f"{cash_type}:{symbol or '-'}:{_normalize_number(amount)}"
            ),
            type=cash_type,
            amount=amount,
            occurred_at=occurred_at,
            symbol=symbol,
            security_type=_security_type(row)[0] if symbol else None,
            currency=_currency_code(_get(row, "currency")),
            source=SOURCE,
            notes=str(_get(row, "description") or ""),
            raw=_dict(row),
        )

    def _to_option_trade(self, row: Any, account_ref: str) -> Optional[NormalizedTrade]:
        """Map an option activity to a trade counted in contracts.

        Options are quoted per share but trade in contracts of 100, so the
        quantity is the contract count and the price is per contract (quote x
        100). Vanguard folds the commission into ``amount`` and reports ``fee``
        as zero, so the commission is recovered as the gap between the quoted
        value and the cash that actually moved.

        An expiry or assignment has no price: it is recorded as a closing trade
        at zero, bought back if the row adds contracts (a written option going
        away) and sold if it removes them.
        """
        raw_type = str(_get(row, "type") or "").upper()
        symbol = _symbol_ticker(_get(row, "symbol"))
        units = _decimal(_get(row, "units"))
        traded_at = _parse_datetime(_get(row, "trade_date"))
        if not symbol or not units or traded_at is None:
            logger.warning(
                "Skipping SnapTrade option activity %s: incomplete "
                "(symbol=%r units=%r trade_date=%r)",
                _get(row, "id"),
                symbol,
                units,
                _get(row, "trade_date"),
            )
            return None

        contracts = abs(units)
        notes = str(_get(row, "description") or "")
        if raw_type in _OPTION_CLOSE_TYPES:
            action = TradeAction.BUY if units > 0 else TradeAction.SELL
            price = Decimal(0)
            commission = Decimal(0)
            notes = f"{raw_type.capitalize()}: {notes}".rstrip(": ")
        else:
            action = _TRADE_TYPES[raw_type]
            quote = _decimal(_get(row, "price"))
            if quote is None or quote <= 0:
                logger.warning(
                    "Skipping SnapTrade option activity %s: no price", _get(row, "id")
                )
                return None
            price = quote * _CONTRACT_MULTIPLIER
            commission = _decimal(_get(row, "fee")) or Decimal(0)
            amount = _decimal(_get(row, "amount"))
            if amount is not None and not commission:
                commission = abs(abs(amount) - contracts * price)

        return NormalizedTrade(
            external_id=snaptrade_external_id(
                account_ref, traded_at.date(), symbol, contracts, price, action
            ),
            symbol=symbol,
            action=action,
            quantity=contracts,
            price=price,
            currency=_currency_code(_get(row, "currency")),
            executed_at=traded_at,
            commission=commission,
            source=SOURCE,
            security_type="OPTION",
            notes=notes,
            raw=_dict(row),
        )

    def _to_trade(self, row: Any, account_ref: str) -> Optional[NormalizedTrade]:
        """Map one SnapTrade trade activity to a NormalizedTrade, or None to skip.

        Field paths follow the SDK's generated ``AccountUniversalActivity``
        model and were checked against a real Vanguard capture: ``trade_date``
        is date-only (midnight US/Eastern, as ``05:00Z``), ``symbol`` is null
        on some delisted names, and ``price`` is 0 on rows that move no shares.
        """
        raw_type = str(_get(row, "type") or "").upper()
        action = _TRADE_TYPES[raw_type]

        symbol = _symbol_ticker(_get(row, "symbol"))
        units = _decimal(_get(row, "units"))
        price = _decimal(_get(row, "price"))
        traded_at = _parse_datetime(_get(row, "trade_date"))

        # Granularity varies by brokerage and trade_date is nullable, so a row
        # without one cannot be placed on the performance timeline. Vanguard
        # also emits BUY/SELL rows whose symbol it cannot resolve (mostly
        # delisted or acquired names; the ticker appears only in description).
        if not symbol or not units or price is None or price <= 0 or traded_at is None:
            logger.warning(
                "Skipping SnapTrade activity %s: incomplete "
                "(symbol=%r units=%r price=%r trade_date=%r)",
                _get(row, "id"),
                symbol,
                units,
                price,
                _get(row, "trade_date"),
            )
            return None

        # SELL rows arrive with negative units; direction comes from the type.
        quantity = abs(units)
        notes = str(_get(row, "description") or "")
        if raw_type == "REI":
            notes = f"Dividend reinvestment: {notes}".rstrip(": ")

        return NormalizedTrade(
            external_id=snaptrade_external_id(
                account_ref, traded_at.date(), symbol, quantity, price, action
            ),
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            currency=_currency_code(_get(row, "currency")),
            executed_at=traded_at,
            commission=_decimal(_get(row, "fee")) or Decimal("0"),
            source=SOURCE,
            security_type=_security_type(row)[0],
            notes=notes,
            raw=_dict(row),
        )

    # --- trading (dormant until Grow) --------------------------------------

    def place_order(self, connection_id, account_ref, order):
        raise NotSupported(
            "SnapTrade trading is not enabled; capabilities.can_trade is False"
        )


def snaptrade_external_id(
    account_ref: str,
    trade_date: date,
    symbol: str,
    quantity,
    price,
    action: TradeAction = TradeAction.BUY,
    occurrence: int = 1,
) -> str:
    """Stable dedup key for a SnapTrade-sourced trade.

    Deliberately derived from trade economics rather than SnapTrade's activity
    ``id``, which the API documents as subject to change if an activity is
    reprocessed — keying on it would re-import the same trade as new.

    The account is part of the key because the same security can trade
    identically in two accounts under one login (e.g. a brokerage account and
    an IRA) and those are genuinely different trades.

    The action is part of it because Vanguard data contains same-day round
    trips at one price (buy 10,000, sell 10,000 at 21.00); without it the two
    legs collapse and one is dropped.

    ``occurrence`` separates genuinely repeated fills — identical in every
    field, distinct activity ids, which Vanguard does emit. The first keeps the
    bare key; repeats get ``:2``, ``:3``. It is stable as long as SnapTrade
    keeps reporting the same set of rows for that day. Vanguard leaves
    ``external_reference_id`` null, so it cannot serve instead.
    """
    qty = _normalize_number(quantity)
    prc = _normalize_number(price)
    key = (
        f"{SOURCE}:{account_ref}:{trade_date.isoformat()}:{symbol.upper()}:"
        f"{action.value}:{qty}:{prc}"
    )
    return key if occurrence <= 1 else f"{key}:{occurrence}"


def _default_credentials() -> SnapTradeCredentials:
    """Credentials for the configured SnapTrade user (the Personal-key owner).

    Lets callers act on a connection by its id alone, without handling a
    vendor credential type.
    """
    if not settings.snaptrade_user_id:
        raise NotSupported(
            "No SnapTrade user configured; set SNAPTRADE_USER_ID or pass credentials"
        )
    return SnapTradeCredentials(user_id=settings.snaptrade_user_id)


def _security_type(row: Any) -> tuple:
    """What kind of security an activity concerns, and how that was determined.

    Returns ``(type, method)``. Tried in order of reliability: the type code on
    the symbol, the ``kind`` a live instrument carries, then the word "ETF" in
    a description (brokerages name funds that way: "... TOTAL STOCK MARKET
    ETF"). ``(None, "none")`` when nothing says.
    """
    symbol = _get(row, "symbol")
    if symbol is not None and not isinstance(symbol, str):
        code = _get(_get(symbol, "type"), "code")
        if isinstance(code, str) and code.strip():
            return _SECURITY_TYPES.get(code.strip().lower(), "OTHER"), "type"
        kind = _get(symbol, "kind")
        if isinstance(kind, str) and kind.strip():
            return _SECURITY_TYPES.get(kind.strip().lower(), "OTHER"), "kind"
        if _ETF_WORD.search(str(_get(symbol, "description") or "")):
            return "ETF", "description"
    if _ETF_WORD.search(str(_get(row, "description") or "")):
        return "ETF", "description"
    return None, "none"


def _is_option(row: Any) -> bool:
    """Whether an activity is an option leg rather than a share trade."""
    if _get(row, "option_symbol"):
        return True
    return is_option_symbol(_symbol_ticker(_get(row, "symbol")))


def _disambiguate_repeats(trades: List[Any]) -> None:
    """Give repeated identical fills distinct keys, in place.

    Order within a set of identical rows does not matter: they are
    interchangeable, so only how many there are affects the keys produced.
    """
    seen: Dict[str, int] = {}
    for i, trade in enumerate(trades):
        count = seen.get(trade.external_id, 0) + 1
        seen[trade.external_id] = count
        if count > 1:
            trades[i] = trade.model_copy(
                update={"external_id": f"{trade.external_id}:{count}"}
            )


# ---------------------------------------------------------------------------
# Payload helpers
#
# The SDK returns objects that behave like mappings but are not dicts, and
# fields are optional throughout. These keep the defensive access in one place
# so the mapping code above stays readable.
# ---------------------------------------------------------------------------


def _body(response: Any) -> Any:
    """The parsed body of an SDK response."""
    return getattr(response, "body", response)


def _get(obj: Any, key: str) -> Any:
    """Read ``key`` from a mapping-like or attribute-style payload object."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    try:
        if key in obj:  # SDK schema objects support __contains__
            return obj[key]
    except (TypeError, KeyError):
        pass
    return getattr(obj, key, None)


def _rows(body: Any) -> List[Any]:
    """The list of records in a body that may be a bare list or paginated."""
    if body is None:
        return []
    if isinstance(body, list):
        return list(body)
    for key in ("data", "results", "activities"):
        value = _get(body, key)
        if isinstance(value, list):
            return list(value)
    try:
        return list(body)
    except TypeError:
        return []


def _total(body: Any) -> Optional[int]:
    """Total row count from a paginated body, when it reports one."""
    pagination = _get(body, "pagination")
    for source in (pagination, body):
        total = _get(source, "total")
        if total is not None:
            try:
                return int(total)
            except (TypeError, ValueError):
                continue
    return None


def _dict(obj: Any) -> dict:
    """Best-effort plain dict of a payload object, for the audit trail."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    for attr in ("to_dict", "model_dump"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                result = fn()
                if isinstance(result, dict):
                    return result
            except Exception:  # noqa: BLE001 - audit data is never load-bearing
                pass
    try:
        return dict(obj)
    except (TypeError, ValueError):
        return {"repr": repr(obj)}


def _jsonable(obj: Any, _depth: int = 0) -> Any:
    """A plain JSON-safe copy of a payload, for storing a row verbatim.

    SDK objects are mappings, sequences and scalars in disguise, and carry
    Decimals, dates and UUIDs that a JSON column cannot take as they are.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if _depth > 12:
        return str(obj)
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "items"):
        try:
            return {str(k): _jsonable(v, _depth + 1) for k, v in obj.items()}
        except Exception:  # noqa: BLE001 - audit data is never load-bearing
            return str(obj)
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_jsonable(v, _depth + 1) for v in obj]
    for probe, value in (("is_none_oapg", None), ("is_true_oapg", True)):
        check = getattr(obj, probe, None)
        if callable(check):
            try:
                if check():
                    return value
            except Exception:  # noqa: BLE001
                pass
    if callable(getattr(obj, "is_false_oapg", None)):
        return False
    return str(obj)


def _symbol_ticker(symbol: Any) -> str:
    """Extract a bare ticker from a SnapTrade symbol field.

    The SDK's generated models define two different nestings, so both are
    handled here rather than at the call sites:

    * An activity's ``symbol`` is a ``SymbolNullable`` carrying ``symbol`` and
      ``raw_symbol`` as plain strings.
    * A live position's ``instrument`` carries them flat, too. The SDK model
      instead documents a ``symbol`` that is a ``PositionSymbol`` whose own
      ``symbol`` is a ``UniversalSymbol``; that nesting is still handled.

    ``raw_symbol`` is preferred: it is the ticker as the brokerage reports it,
    whereas ``symbol`` may be SnapTrade's normalized form. Note our stored
    trades use exchange-prefixed tickers such as ``BATS:IGE`` while this
    returns the bare ticker — reconciling the two is the open symbol
    normalization item on the roadmap.
    """
    if symbol is None:
        return ""
    if isinstance(symbol, str):
        return symbol.strip().upper()

    raw = _get(symbol, "raw_symbol")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().upper()

    inner = _get(symbol, "symbol")
    if isinstance(inner, str) and inner.strip():
        return inner.strip().upper()
    # PositionSymbol.symbol is itself a UniversalSymbol; recurse once into it.
    if inner is not None:
        return _symbol_ticker(inner)
    return ""


def _institution(item: Any) -> str:
    """Brokerage name from an account or connection payload."""
    direct = _get(item, "institution_name") or _get(item, "institution")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    brokerage = _get(item, "brokerage")
    name = _get(brokerage, "name") if brokerage is not None else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


def _transaction_sync(item: Any) -> Any:
    """The ``sync_status.transactions`` block of an account payload."""
    return _get(_get(item, "sync_status"), "transactions")


def _initial_sync_completed(item: Any) -> Optional[bool]:
    """Whether SnapTrade has finished the account's first history pull.

    Until it has, the account returns no activity at all even though its
    holdings are already populated.
    """
    value = _get(_transaction_sync(item), "initial_sync_completed")
    return value if isinstance(value, bool) else None


def _synced_through(item: Any) -> Optional[date]:
    """The last date for which the account's transactions are complete."""
    parsed = _parse_datetime(_get(_transaction_sync(item), "last_successful_sync"))
    return parsed.date() if parsed else None


def _currency_code(currency: Any) -> str:
    """ISO code from a currency object, defaulting to USD."""
    if isinstance(currency, str) and currency.strip():
        return currency.strip().upper()
    code = _get(currency, "code")
    if isinstance(code, str) and code.strip():
        return code.strip().upper()
    return "USD"


def _decimal(value: Any) -> Optional[Decimal]:
    """Coerce a numeric payload field to Decimal, or None if unusable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _normalize_number(value: Any) -> str:
    """Canonical string for a number used in a dedup key.

    Normalizes so 10, 10.0 and "10.00" produce one key rather than three.
    """
    dec = _decimal(value)
    if dec is None:
        return "0"
    normalized = dec.normalize()
    # Avoid exponent notation (1E+2) for whole numbers.
    if normalized == normalized.to_integral_value():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse a SnapTrade timestamp into a tz-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_date(value: Optional[datetime]) -> Optional[date]:
    """Date part of an optional datetime, for the API's date filters."""
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def _opt_str(value: Any) -> Optional[str]:
    """Trimmed string, or None when absent or empty."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
