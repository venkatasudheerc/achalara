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
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from app.config import settings
from app.connectors.base import ConnectorCapabilities
from app.connectors.models import (
    Connection,
    ConnectionResult,
    ConnectionStatus,
    LinkSession,
    NormalizedPosition,
    NormalizedTrade,
    NotSupported,
    RawAccount,
    TradeAction,
)

logger = logging.getLogger(__name__)

SOURCE = "snaptrade"

# Activity types that represent an executed trade. Everything else SnapTrade
# reports (DIVIDEND, FEE, CONTRIBUTION, WITHDRAWAL, TRANSFER, ...) has no home
# in the Trade model yet and is skipped — see _KNOWN_NON_TRADE_TYPES.
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

# Recognized non-trade activity. Listed explicitly so an *unrecognized* type
# can be logged loudly instead of silently vanishing: dividends in particular
# affect real returns, so dropping them is a known accuracy gap, not a no-op.
#
# Vanguard spells several of these with spaces and qualifiers (observed in
# captured payloads). SPLIT, CORP ACTION (MERGER), ASSIGNMENT and EXPIRED
# change share counts too, so skipping them is a further accuracy gap.
_KNOWN_NON_TRADE_TYPES = {
    "DIVIDEND",
    "CONTRIBUTION",
    "WITHDRAWAL",
    "DEPOSIT",
    "INTEREST",
    "INTEREST CHARGE",
    "INCOME",
    "FEE",
    "WITHHOLDING",
    "TRANSFER",
    "TRANSFER (INCOMING)",
    "TRANSFER (OUTGOING)",
    "WIRE OUT",
    "SWEEP IN",
    "SWEEP OUT",
    "STOCK_DIVIDEND",
    "SPLIT",
    "CORP ACTION (MERGER)",
    "CORP ACTION (CASH IN LIEU)",
    "ASSIGNMENT",
    "EXPIRED",
}

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
        if credentials is None:
            raise NotSupported("refresh_connection requires SnapTrade credentials")
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
        if credentials is None:
            raise NotSupported("remove_connection requires SnapTrade credentials")
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
                    raw=_dict(item),
                )
            )
        return out

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

        Pages through SnapTrade's offset pagination and keeps only BUY/SELL
        activity. Rows that cannot be mapped are skipped with a warning rather
        than failing the whole sync — one malformed row should not block a
        day's trades.
        """
        creds = credentials or SnapTradeCredentials(user_id=connection_id)
        trades: List[NormalizedTrade] = []
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
                trade = self._to_trade(row, account_ref)
                if trade is not None:
                    trades.append(trade)

            offset += len(rows)
            total = _total(body)
            if not rows or (total is not None and offset >= total):
                break
            if total is None and len(rows) < _MAX_PAGE:
                break

        _disambiguate_repeats(trades)
        # SnapTrade returns newest first; ingestion reads chronologically.
        trades.sort(key=lambda t: t.executed_at)
        return trades

    def _to_trade(self, row: Any, account_ref: str) -> Optional[NormalizedTrade]:
        """Map one SnapTrade activity to a NormalizedTrade, or None to skip.

        Field paths follow the SDK's generated ``AccountUniversalActivity``
        model and were checked against a real Vanguard capture: ``trade_date``
        is date-only (midnight US/Eastern, as ``05:00Z``), ``symbol`` is null
        on cash rows and on some delisted names, and ``price`` is 0 on rows
        that move no shares.
        """
        raw_type = str(_get(row, "type") or "").upper()
        action = _TRADE_TYPES.get(raw_type)
        if action is None:
            if raw_type and raw_type not in _KNOWN_NON_TRADE_TYPES:
                logger.warning(
                    "SnapTrade activity type %r not recognized; skipping", raw_type
                )
            return None

        symbol = _symbol_ticker(_get(row, "symbol"))
        units = _decimal(_get(row, "units"))
        price = _decimal(_get(row, "price"))
        traded_at = _parse_datetime(_get(row, "trade_date"))

        # A reinvestment into a sweep fund moves cash, not shares.
        if raw_type == "REI" and not units:
            return None

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


def _disambiguate_repeats(trades: List[NormalizedTrade]) -> None:
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
