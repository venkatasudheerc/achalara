"""Tests for the SnapTrade connector (Bridge B4).

No network: a stub SDK client replays canned payloads. Most are hand-built
around the mapping contract (direction, sign handling, dedup identity, skip
behavior); the ``fixtures/snaptrade`` ones are sanitized from a real Vanguard
capture, so they pin down how that brokerage actually populates the fields.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.connectors.models import NotSupported, TradeAction
from app.connectors.registry import available_sources, get_connector
from app.connectors.snaptrade_connector import (
    SnapTradeConnector,
    SnapTradeCredentials,
    snaptrade_external_id,
)

ACCOUNT = "acct-1"
CREDS = SnapTradeCredentials(user_id="client-1", user_secret="secret-1")
FIXTURES = Path(__file__).parent / "fixtures" / "snaptrade"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


def _activity(
    activity_id="act-1",
    type_="BUY",
    symbol="AAPL",
    units=10,
    price="150.25",
    trade_date="2026-03-02T14:30:00Z",
    fee="1.25",
    description="Bought 10 AAPL",
):
    """An activity row shaped like SnapTrade's UniversalActivity."""
    return {
        "id": activity_id,
        "type": type_,
        "symbol": {"symbol": symbol, "raw_symbol": symbol},
        "units": units,
        "price": price,
        "trade_date": trade_date,
        "settlement_date": "2026-03-04T00:00:00Z",
        "fee": fee,
        "currency": {"code": "USD"},
        "description": description,
    }


class _StubActivities:
    """Captures calls and replays canned pages."""

    def __init__(self, pages, positions=None):
        self.pages = pages
        self.positions = positions
        self.calls = []

    def get_account_activities(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        page = self.pages[index] if index < len(self.pages) else {"data": []}
        return type("Resp", (), {"body": page})()

    def list_user_accounts(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Resp",
            (),
            {
                "body": [
                    {
                        "id": "acct-1",
                        "name": "Brokerage Account",
                        "number": "1234",
                        "institution_name": "Vanguard",
                    },
                    {
                        "id": "acct-2",
                        "name": "Roth IRA",
                        "number": "5678",
                        "institution_name": "Vanguard",
                    },
                ]
            },
        )()

    def get_all_account_positions(self, **kwargs):
        self.calls.append(kwargs)
        if self.positions is not None:
            return type("Resp", (), {"body": self.positions})()
        return type(
            "Resp",
            (),
            {
                "body": [
                    {
                        # A Position nests one level deeper than an activity:
                        # PositionSymbol.symbol is a UniversalSymbol.
                        "symbol": {
                            "symbol": {"symbol": "VTI", "raw_symbol": "VTI"},
                            "is_quotable": True,
                        },
                        "units": "12.5",
                        "price": "240.10",
                        "average_purchase_price": "198.40",
                        "fractional_units": "0.5",
                    }
                ]
            },
        )()


class _StubClient:
    def __init__(self, pages=None, positions=None):
        shared = _StubActivities(pages or [], positions)
        self.account_information = shared
        self.connections = shared
        self.authentication = shared
        self._shared = shared


def _connector(pages=None, positions=None):
    return SnapTradeConnector(client=_StubClient(pages, positions))


# ---------------------------------------------------------------------------
# Registry and capabilities
# ---------------------------------------------------------------------------


def test_snaptrade_is_registered():
    assert "snaptrade" in available_sources()
    assert get_connector("snaptrade") is not None


def test_capabilities_are_honest_about_daily_freshness():
    caps = SnapTradeConnector.capabilities
    assert caps.can_read_transactions is True
    assert caps.can_read_positions is True
    # Transactions are day-delayed at source — nothing here is live.
    assert caps.supports_realtime is False
    assert caps.data_freshness == "daily"
    # Trading stays dormant until Grow.
    assert caps.can_trade is False


def test_trading_is_refused_while_capability_is_off():
    with pytest.raises(NotSupported):
        _connector().place_order("c", ACCOUNT, object())


def test_complete_link_is_refused_because_there_is_no_code_exchange():
    # SnapTrade signals completion by webhook, not a callback exchange.
    with pytest.raises(NotSupported):
        _connector().complete_link({"any": "payload"})


def test_unconfigured_connector_reports_it():
    connector = SnapTradeConnector()
    connector._client_id = ""
    connector._consumer_key = ""
    assert connector.is_configured() is False
    # Touching the client without credentials must fail loudly, not silently.
    with pytest.raises(NotSupported):
        _ = connector.client


# ---------------------------------------------------------------------------
# Trade mapping — the parts most likely to be wrong
# ---------------------------------------------------------------------------


def test_buy_maps_to_normalized_trade():
    connector = _connector([{"data": [_activity()], "pagination": {"total": 1}}])
    trades = connector.fetch_transactions("c", ACCOUNT, credentials=CREDS)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.symbol == "AAPL"
    assert trade.action is TradeAction.BUY
    assert trade.quantity == Decimal("10")
    assert trade.price == Decimal("150.25")
    assert trade.commission == Decimal("1.25")
    assert trade.currency == "USD"
    assert trade.source == "snaptrade"
    assert trade.executed_at == datetime(2026, 3, 2, 14, 30, tzinfo=timezone.utc)
    # Raw payload is retained for audit.
    assert trade.raw["id"] == "act-1"


def test_sell_direction_comes_from_type_not_the_sign_of_units():
    # SnapTrade reports SELL with negative units; quantity must be positive
    # and the direction must come from `type`.
    connector = _connector(
        [{"data": [_activity(type_="SELL", units=-10)], "pagination": {"total": 1}}]
    )
    trades = connector.fetch_transactions("c", ACCOUNT, credentials=CREDS)

    assert len(trades) == 1
    assert trades[0].action is TradeAction.SELL
    assert trades[0].quantity == Decimal("10")


def test_non_trade_activity_is_skipped():
    rows = [
        _activity(activity_id="a1", type_="DIVIDEND"),
        _activity(activity_id="a2", type_="CONTRIBUTION"),
        _activity(activity_id="a3", type_="FEE"),
        _activity(activity_id="a4", type_="BUY"),
    ]
    connector = _connector([{"data": rows, "pagination": {"total": len(rows)}}])
    trades = connector.fetch_transactions("c", ACCOUNT, credentials=CREDS)

    # Only the BUY becomes a trade. Dividends are a known accuracy gap.
    assert len(trades) == 1
    assert trades[0].action is TradeAction.BUY


def test_row_without_trade_date_is_skipped():
    # trade_date is nullable in the API and a trade with no date cannot be
    # placed on the performance timeline.
    connector = _connector(
        [{"data": [_activity(trade_date=None)], "pagination": {"total": 1}}]
    )
    assert connector.fetch_transactions("c", ACCOUNT, credentials=CREDS) == []


def test_row_without_price_or_symbol_is_skipped():
    rows = [
        _activity(activity_id="a1", price=None),
        _activity(activity_id="a2", symbol="", description=""),
    ]
    connector = _connector([{"data": rows, "pagination": {"total": len(rows)}}])
    assert connector.fetch_transactions("c", ACCOUNT, credentials=CREDS) == []


def test_trade_without_a_ticker_is_matched_by_the_securitys_name():
    # Vanguard sends delisted and acquired names with no symbol at all.
    def nameless(activity_id, type_, units):
        row = _activity(
            activity_id=activity_id,
            type_=type_,
            units=units,
            description="NORTHWIND   TRADING INC",
        )
        row["symbol"] = None
        return row

    page = {"data": [nameless("a1", "BUY", 40), nameless("a2", "SELL", -40)]}
    buy, sell = _connector([page]).fetch_transactions("c", ACCOUNT, credentials=CREDS)

    assert buy.symbol == sell.symbol == "~NORTHWIND TRADING INC"
    assert (buy.action, sell.action) == (TradeAction.BUY, TradeAction.SELL)


def test_trades_are_returned_oldest_first():
    # SnapTrade returns newest first; ingestion reads chronologically.
    rows = [
        _activity(activity_id="new", trade_date="2026-03-10T10:00:00Z"),
        _activity(activity_id="old", trade_date="2026-03-01T10:00:00Z"),
    ]
    connector = _connector([{"data": rows, "pagination": {"total": len(rows)}}])
    trades = connector.fetch_transactions("c", ACCOUNT, credentials=CREDS)

    assert [t.raw["id"] for t in trades] == ["old", "new"]


# ---------------------------------------------------------------------------
# Dedup identity
# ---------------------------------------------------------------------------


def test_external_id_is_stable_across_fetches():
    page = {"data": [_activity()], "pagination": {"total": 1}}
    first = _connector([page]).fetch_transactions("c", ACCOUNT, credentials=CREDS)
    second = _connector([page]).fetch_transactions("c", ACCOUNT, credentials=CREDS)
    assert first[0].external_id == second[0].external_id


def test_external_id_ignores_snaptrade_activity_id():
    # The API documents activity ids as changeable on reprocessing, so the
    # same economics must yield the same key even with a different id.
    a = _connector(
        [{"data": [_activity(activity_id="first")], "pagination": {"total": 1}}]
    ).fetch_transactions("c", ACCOUNT, credentials=CREDS)
    b = _connector(
        [{"data": [_activity(activity_id="reprocessed")], "pagination": {"total": 1}}]
    ).fetch_transactions("c", ACCOUNT, credentials=CREDS)
    assert a[0].external_id == b[0].external_id


def test_external_id_separates_accounts():
    # One login exposes several accounts; identical trades in a brokerage
    # account and an IRA are genuinely different trades.
    key_a = snaptrade_external_id(
        "acct-1", datetime(2026, 3, 2).date(), "AAPL", Decimal("10"), Decimal("150.25")
    )
    key_b = snaptrade_external_id(
        "acct-2", datetime(2026, 3, 2).date(), "AAPL", Decimal("10"), Decimal("150.25")
    )
    assert key_a != key_b


def test_external_id_separates_buy_from_sell():
    # A same-day round trip at one price is two real trades.
    args = ("acct-1", datetime(2025, 7, 28).date(), "ABC", Decimal("100"), "21")
    assert snaptrade_external_id(*args, TradeAction.BUY) != snaptrade_external_id(
        *args, TradeAction.SELL
    )


def test_external_id_normalizes_number_formatting():
    # 10, 10.0 and "10.00" are the same quantity and must not produce
    # three different dedup keys.
    base = ("acct-1", datetime(2026, 3, 2).date(), "AAPL")
    keys = {
        snaptrade_external_id(*base, q, p)
        for q, p in [
            (Decimal("10"), Decimal("150.25")),
            (Decimal("10.00"), Decimal("150.2500")),
            (10, "150.25"),
        ]
    }
    assert len(keys) == 1


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pagination_walks_all_pages():
    page_one = {
        "data": [
            _activity(activity_id=f"a{i}", trade_date="2026-03-02T10:00:00Z")
            for i in range(3)
        ],
        "pagination": {"total": 5, "offset": 0, "limit": 1000},
    }
    page_two = {
        "data": [
            _activity(activity_id=f"b{i}", trade_date="2026-03-03T10:00:00Z")
            for i in range(2)
        ],
        "pagination": {"total": 5, "offset": 3, "limit": 1000},
    }
    connector = _connector([page_one, page_two])
    trades = connector.fetch_transactions("c", ACCOUNT, credentials=CREDS)

    assert len(trades) == 5
    assert len(connector._client._shared.calls) == 2
    assert connector._client._shared.calls[1]["offset"] == 3


def test_pagination_stops_on_empty_page():
    connector = _connector([{"data": []}])
    assert connector.fetch_transactions("c", ACCOUNT, credentials=CREDS) == []
    assert len(connector._client._shared.calls) == 1


def test_date_window_is_passed_through_as_dates():
    connector = _connector([{"data": [], "pagination": {"total": 0}}])
    connector.fetch_transactions(
        "c",
        ACCOUNT,
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 2, 1, tzinfo=timezone.utc),
        credentials=CREDS,
    )
    call = connector._client._shared.calls[0]
    assert call["start_date"] == datetime(2026, 1, 1).date()
    assert call["end_date"] == datetime(2026, 2, 1).date()


def test_user_secret_is_sent_when_present():
    connector = _connector([{"data": [], "pagination": {"total": 0}}])
    connector.fetch_transactions("c", ACCOUNT, credentials=CREDS)
    assert connector._client._shared.calls[0]["user_secret"] == "secret-1"


def test_personal_flow_omits_user_secret():
    # Personal API keys have no userSecret and must not send an empty one.
    connector = _connector([{"data": [], "pagination": {"total": 0}}])
    connector.fetch_transactions(
        "c", ACCOUNT, credentials=SnapTradeCredentials(user_id="me")
    )
    assert "user_secret" not in connector._client._shared.calls[0]


# ---------------------------------------------------------------------------
# Accounts and positions
# ---------------------------------------------------------------------------


def test_fetch_accounts_returns_every_account_under_one_login():
    # One Vanguard login commonly exposes several accounts.
    accounts = _connector().fetch_accounts("c", credentials=CREDS)
    assert [a.external_ref for a in accounts] == ["acct-1", "acct-2"]
    assert accounts[0].institution == "Vanguard"
    assert accounts[1].name == "Roth IRA"
    assert accounts[0].account_number == "1234"


def test_activity_symbol_prefers_raw_symbol_over_normalized():
    # raw_symbol is the ticker as the brokerage reports it; symbol may be
    # SnapTrade's normalized form, so raw_symbol wins.
    row = _activity()
    row["symbol"] = {"symbol": "NORMALIZED", "raw_symbol": "VTSAX"}
    connector = _connector([{"data": [row], "pagination": {"total": 1}}])
    trades = connector.fetch_transactions("c", ACCOUNT, credentials=CREDS)
    assert trades[0].symbol == "VTSAX"


def test_activity_symbol_falls_back_when_raw_symbol_absent():
    # raw_symbol is optional on SymbolNullable.
    row = _activity()
    row["symbol"] = {"symbol": "VTI"}
    connector = _connector([{"data": [row], "pagination": {"total": 1}}])
    trades = connector.fetch_transactions("c", ACCOUNT, credentials=CREDS)
    assert trades[0].symbol == "VTI"


def test_fetch_positions_maps_holdings():
    positions = _connector().fetch_positions("c", ACCOUNT, credentials=CREDS)
    assert len(positions) == 1
    position = positions[0]
    # Nested symbol shapes must still resolve to a bare ticker.
    assert position.symbol == "VTI"
    assert position.quantity == Decimal("12.5")
    assert position.avg_cost == Decimal("198.40")
    assert position.market_price == Decimal("240.10")


def test_fetch_positions_reads_live_instrument_shape():
    # What the live API actually returns: rows under ``results``, the security
    # under ``instrument``, and a per-unit ``cost_basis``.
    connector = _connector(positions=_fixture("vanguard_positions.json"))
    positions = connector.fetch_positions("c", ACCOUNT, credentials=CREDS)

    assert [p.symbol for p in positions] == ["BHP", "CIBR"]
    bhp = positions[0]
    assert bhp.quantity == Decimal("12")
    assert bhp.avg_cost == Decimal("85.5375")
    assert bhp.market_price == Decimal("86.83")
    assert bhp.currency == "USD"


def test_position_without_cost_basis_is_kept_with_zero_cost():
    # Lots bought since the last transaction sync have no cost_basis yet; the
    # holding is real and must not be dropped.
    connector = _connector(positions=_fixture("vanguard_positions.json"))
    cibr = connector.fetch_positions("c", ACCOUNT, credentials=CREDS)[1]
    assert cibr.quantity == Decimal("21.001")
    assert cibr.avg_cost == Decimal("0")


# ---------------------------------------------------------------------------
# Real Vanguard payload shapes
# ---------------------------------------------------------------------------


def _vanguard_trades():
    return _connector([_fixture("vanguard_activities.json")]).fetch_transactions(
        "c", ACCOUNT, credentials=CREDS
    )


def test_vanguard_maps_buys_sells_and_share_reinvestments_only():
    trades = _vanguard_trades()
    # DIVIDEND, SWEEP IN, SPLIT and the Cash Plus REI are not trades; 8 of
    # the 12 rows are, including the BUY that came with a name but no ticker.
    assert len(trades) == 8
    assert {t.symbol for t in trades} == {
        "USO",
        "FRDM",
        "VTI",
        "INTC",
        "MU",
        "~WALGREENS BOOTS ALLIANCEINC",
    }


def test_vanguard_reinvestment_becomes_a_tagged_buy():
    rei = next(t for t in _vanguard_trades() if t.symbol == "VTI")
    assert rei.action is TradeAction.BUY
    assert rei.quantity == Decimal("0.632")
    assert rei.price == Decimal("12.5")
    assert rei.notes.startswith("Dividend reinvestment")


def test_vanguard_same_day_round_trip_keeps_both_legs():
    intc = [t for t in _vanguard_trades() if t.symbol == "INTC"]
    assert {t.action for t in intc} == {TradeAction.BUY, TradeAction.SELL}
    assert len({t.external_id for t in intc}) == 2


def test_vanguard_repeated_identical_fills_get_distinct_keys():
    # Two rows identical in every field but the activity id: two real fills.
    mu = [t for t in _vanguard_trades() if t.symbol == "MU"]
    assert len(mu) == 2
    assert len({t.external_id for t in mu}) == 2


def test_vanguard_keys_are_stable_across_fetches():
    first = {t.external_id for t in _vanguard_trades()}
    second = {t.external_id for t in _vanguard_trades()}
    assert first == second


# ---------------------------------------------------------------------------
# fetch_activities: trades, cash, and an account of what was left out
# ---------------------------------------------------------------------------


def _vanguard_batch():
    return _connector([_fixture("vanguard_activities.json")]).fetch_activities(
        "c", ACCOUNT, credentials=CREDS
    )


def test_activities_separate_cash_from_trades():
    batch = _vanguard_batch()
    assert len(batch.trades) == 8
    (dividend,) = batch.cash
    assert dividend.type == "DIVIDEND"
    assert dividend.symbol == "FRDM"
    assert dividend.amount == Decimal("8.21")
    assert dividend.external_id.startswith(f"snaptrade:{ACCOUNT}:2026-09-30:cash:")


def test_activities_tally_every_row_left_out():
    batch = _vanguard_batch()
    assert batch.skipped == {"sweep": 2, "corporate_action": 1}
    # Every fixture row is accounted for: ingested or counted as skipped.
    total = len(_fixture("vanguard_activities.json")["data"])
    assert len(batch.trades) + len(batch.cash) + sum(batch.skipped.values()) == total


def _option(
    type_, units, price, amount, symbol="ABCD270115P00020000", day="2026-04-17"
):
    row = _activity(
        activity_id=f"{type_}-{symbol}-{units}",
        type_=type_,
        symbol=symbol,
        units=units,
        price=price,
        trade_date=f"{day}T05:00:00Z",
        fee=0,
        description="PUT ABCD CORP $20 EXP 01/15/27",
    )
    row["amount"] = amount
    return row


def _options(*rows):
    return _connector([{"data": list(rows)}]).fetch_activities(
        "c", ACCOUNT, credentials=CREDS
    )


def test_option_trade_is_counted_in_contracts_at_the_per_contract_price():
    # 25 puts written at a 4.80 quote: 12,000 gross, 11,975 received.
    (trade,) = _options(_option("SELL", -25, 4.8, 11975.0)).trades

    assert trade.security_type == "OPTION"
    assert trade.action == TradeAction.SELL
    assert trade.quantity == Decimal("25")
    assert trade.price == Decimal("480.0")
    # Vanguard reports fee as 0 and nets the commission out of the amount.
    assert trade.commission == Decimal("25.0")
    assert trade.quantity * trade.price - trade.commission == Decimal("11975.0")


def test_a_stock_sale_recovers_the_fees_taken_out_of_the_amount():
    """Vanguard reports fee as 0; the regulatory fees are the gap to the cash."""
    row = {
        **_activity(type_="SELL", units=-11, price="370.00", fee=0),
        "amount": 4069.92,
    }
    (trade,) = (
        SnapTradeConnector(client=object()).parse_activities([row], ACCOUNT).trades
    )

    assert trade.commission == Decimal("0.08")
    assert trade.quantity * trade.price - trade.commission == Decimal("4069.92")


def test_a_purchase_or_an_unbelievable_gap_carries_no_recovered_fee():
    bought = {**_activity(units=10, price="150.2512", fee=0), "amount": -1502.51}
    odd = {**_activity("act-2", "SELL", units=-10, price="150", fee=0), "amount": 900}
    trades = (
        SnapTradeConnector(client=object())
        .parse_activities([bought, odd], ACCOUNT)
        .trades
    )

    assert [t.commission for t in trades] == [Decimal("0"), Decimal("0")]


def test_option_buy_recovers_commission_added_to_the_amount():
    (trade,) = _options(_option("BUY", 10, 3.5, -3510.0)).trades
    assert (trade.action, trade.price, trade.commission) == (
        TradeAction.BUY,
        Decimal("350.0"),
        Decimal("10.0"),
    )


def test_option_symbols_with_a_renumbered_root_are_recognised():
    batch = _options(
        _option("SELL", -10, 1.0, 990.0, symbol="XYZ1270115P00000500"),
        _activity(activity_id="act-2", symbol="AAPL"),
    )
    assert sorted(t.security_type or "-" for t in batch.trades) == ["-", "OPTION"]
    assert batch.skipped == {}


def test_expiry_and_assignment_close_the_contracts_at_zero():
    batch = _options(
        # Written puts expiring or being assigned: contracts come back.
        _option("EXPIRED", 20, 0.0, 0.0, day="2026-08-07"),
        _option("ASSIGNMENT", 17, 0.0, 0.0, day="2026-01-02"),
        # A bought option expiring worthless: contracts go away.
        _option("EXPIRED", -5, 0.0, 0.0, symbol="MNOP260213P00115000"),
    )

    by_qty = {t.quantity: t for t in batch.trades}
    assert by_qty[Decimal("20")].action == TradeAction.BUY
    assert by_qty[Decimal("17")].action == TradeAction.BUY
    assert by_qty[Decimal("5")].action == TradeAction.SELL
    assert {t.price for t in batch.trades} == {Decimal("0")}
    assert by_qty[Decimal("17")].notes.startswith("Assignment: ")
    assert batch.skipped == {}


def test_expiry_of_something_that_is_not_an_option_is_still_skipped():
    row = _activity(type_="EXPIRED", symbol="XYZ.RT", units=10, price=0)
    assert _options(row).skipped == {"corporate_action": 1}


def test_stored_rows_parse_the_same_as_fetched_ones():
    payload = _fixture("vanguard_activities.json")
    fetched = _connector([payload]).fetch_activities("c", ACCOUNT, credentials=CREDS)
    parsed = _connector().parse_activities(payload["data"], ACCOUNT)

    assert [t.external_id for t in parsed.trades] == [
        t.external_id for t in fetched.trades
    ]
    assert [c.external_id for c in parsed.cash] == [c.external_id for c in fetched.cash]
    assert parsed.skipped == fetched.skipped
    # One raw entry per input row, in input order.
    assert [r.source_id for r in parsed.raw] == [r["id"] for r in payload["data"]]


def test_cash_types_map_onto_ours_and_keep_the_source_sign():
    def cash(type_, amount, activity_id):
        row = _activity(activity_id=activity_id, type_=type_, units=0, price=0)
        row["amount"] = amount
        row["symbol"] = None
        return row

    page = {
        "data": [
            cash("FEE", -25.0, "a"),
            cash("WIRE OUT", -1000.0, "b"),
            cash("TRANSFER (INCOMING)", 5000.0, "c"),
            cash("INTEREST", 0.0, "d"),
        ]
    }
    batch = _connector([page]).fetch_activities("c", ACCOUNT, credentials=CREDS)
    assert sorted((c.type, c.amount) for c in batch.cash) == [
        ("FEE", Decimal("-25.0")),
        ("TRANSFER", Decimal("5000.0")),
        ("WITHDRAWAL", Decimal("-1000.0")),
    ]
    # A zero-amount row moves no money.
    assert batch.skipped == {"incomplete": 1}


def test_repeated_identical_cash_rows_get_distinct_keys():
    row = _activity(type_="DIVIDEND", units=0, price=0)
    row["amount"] = 4.0
    batch = _connector([{"data": [row, dict(row, id="act-2")]}]).fetch_activities(
        "c", ACCOUNT, credentials=CREDS
    )
    first, second = batch.cash
    assert first.external_id != second.external_id


def test_accounts_carry_the_sources_sync_status():
    class _WithStatus(_StubActivities):
        def list_user_accounts(self, **kwargs):
            return type(
                "Resp",
                (),
                {
                    "body": [
                        {
                            "id": "acct-1",
                            "name": "Brokerage",
                            "brokerage_authorization": "auth-1",
                            "sync_status": {
                                "transactions": {
                                    "initial_sync_completed": False,
                                    "last_successful_sync": "2026-09-30",
                                }
                            },
                        }
                    ]
                },
            )()

    stub = _StubClient()
    stub.account_information = _WithStatus([])
    (account,) = SnapTradeConnector(client=stub).fetch_accounts("c", credentials=CREDS)
    assert account.connection_ref == "auth-1"
    assert account.initial_sync_completed is False
    assert account.transactions_synced_through.isoformat() == "2026-09-30"


# ---------------------------------------------------------------------------
# Security type and verbatim rows
# ---------------------------------------------------------------------------


def _typed(symbol_extra=None, description="ACME CORP", **kwargs):
    row = _activity(description=description, **kwargs)
    row["symbol"].update(symbol_extra or {})
    return row


def _one_trade(row):
    batch = _connector([{"data": [row]}]).fetch_activities(
        "c", ACCOUNT, credentials=CREDS
    )
    return batch.trades[0], batch.security_type_sources


def test_security_type_comes_from_the_symbols_type_code():
    trade, sources = _one_trade(_typed({"type": {"code": "et", "description": "ETF"}}))
    assert trade.security_type == "ETF"
    assert sources == {"type": 1}
    assert _one_trade(_typed({"type": {"code": "cs"}}))[0].security_type == "STOCK"
    assert _one_trade(_typed({"type": {"code": "ad"}}))[0].security_type == "ADR"
    # A code we have no name for is still a known, non-ETF security.
    assert _one_trade(_typed({"type": {"code": "wt"}}))[0].security_type == "OTHER"


def test_security_type_falls_back_to_instrument_kind():
    trade, sources = _one_trade(_typed({"kind": "etf"}))
    assert trade.security_type == "ETF"
    assert sources == {"kind": 1}


def test_security_type_falls_back_to_the_word_etf_in_a_description():
    trade, sources = _one_trade(_typed(description="VANGUARD TOTAL STOCK MARKET ETF"))
    assert trade.security_type == "ETF"
    assert sources == {"description": 1}
    # Only as a whole word: a ticker or name merely containing the letters is not one.
    assert _one_trade(_typed(description="NETFLIX INC"))[0].security_type is None


def test_security_type_is_none_when_nothing_says():
    trade, sources = _one_trade(_typed())
    assert trade.security_type is None
    assert sources == {"none": 1}


def test_every_fetched_row_is_kept_verbatim_with_its_outcome():
    payload = _fixture("vanguard_activities.json")
    batch = _connector([payload]).fetch_activities("c", ACCOUNT, credentials=CREDS)

    assert len(batch.raw) == len(payload["data"])
    outcomes = {}
    for raw in batch.raw:
        outcomes[raw.outcome] = outcomes.get(raw.outcome, 0) + 1
    assert outcomes == {
        "trade": 8,
        "cash": 1,
        "skipped:sweep": 2,
        "skipped:corporate_action": 1,
    }
    split = next(r for r in batch.raw if r.type == "SPLIT")
    assert split.symbol == "NVDA"
    # The stored payload is the source row, untouched.
    original = next(r for r in payload["data"] if r["type"] == "SPLIT")
    assert split.payload == original
    assert json.loads(json.dumps(split.payload)) == original


# ---------------------------------------------------------------------------
# Mergers
# ---------------------------------------------------------------------------


def _merger(activity_id, description, units, amount=0, symbol=None):
    row = _activity(
        activity_id=activity_id,
        type_="CORP ACTION (MERGER)",
        symbol=symbol or "X",
        units=units,
        price="0",
        fee="0",
        description=description,
    )
    row["amount"] = amount
    if symbol is None:
        row["symbol"] = None
    return row


def _merger_batch(*rows):
    return _connector([{"data": list(rows)}]).fetch_activities(
        "c", ACCOUNT, credentials=CREDS
    )


def test_a_cash_merger_is_a_sale_at_the_cash_paid_per_share():
    # The same nameless security as its ordinary trades, so the two match up.
    batch = _merger_batch(_merger("m1", "NORTHWIND TRADING INC", -40, amount=3800))

    (sale,) = batch.trades
    assert sale.symbol == "~NORTHWIND TRADING INC"
    assert (sale.action, sale.quantity, sale.price) == (
        TradeAction.SELL,
        Decimal("40"),
        Decimal("95"),
    )
    assert sale.notes.startswith("Merger: ")
    assert batch.raw[0].outcome == "trade"


def test_the_change_marker_in_a_merger_rows_name_is_ignored():
    """Vanguard writes CHG into the fixed-width name of the security changed."""
    batch = _merger_batch(
        _merger(
            "m1", "ALDERWOOD            CHGPHARMACEUTICALS INC", -30, amount="768.00"
        ),
        _merger("m2", "FAIRVIEW REAL ESTATE CHGINC", -150),
    )

    assert {t.symbol for t in batch.trades} == {
        "~ALDERWOOD PHARMACEUTICALS INC",
        "~FAIRVIEW REAL ESTATE INC",
    }


def test_shares_exchanged_for_shares_are_legs_without_a_price():
    batch = _merger_batch(
        _merger("m1", "FAIRVIEW REAL ESTATE CHGINC", -150),
        _merger("m2", "HARBOUR INC             CL A", 215, symbol="HRBR"),
    )

    legs = {t.symbol: t for t in batch.trades}
    assert (legs["~FAIRVIEW REAL ESTATE INC"].action, legs["HRBR"].action) == (
        TradeAction.SELL,
        TradeAction.BUY,
    )
    assert {t.price for t in batch.trades} == {Decimal("0")}  # cost is carried later


def test_a_change_of_ticker_is_not_a_sale_and_a_purchase():
    """The same shares of the same symbol leaving and arriving on one day."""
    batch = _merger_batch(
        _merger("m1", "RIVERTON GOLD INC", 25, symbol="RVG"),
        _merger("m2", "RIVERTON GOLD INC    CHG", -25, symbol="RVG"),
        _merger("m3", "TALLOW GOLD CORP", 12, symbol="TLGDF"),
    )

    (received,) = batch.trades  # only the shares that really arrived
    assert (received.symbol, received.action, received.price) == (
        "TLGDF",
        TradeAction.BUY,
        Decimal("0"),
    )
    assert [r.outcome for r in batch.raw] == [
        "skipped:corporate_action",
        "skipped:corporate_action",
        "trade",
    ]
    assert batch.skipped == {"corporate_action": 2}


def test_a_funds_capital_gain_distribution_is_income():
    row = _activity(
        activity_id="g1", type_="CAPITAL GAIN (LT)", symbol="ABCX", units=0, price="0"
    )
    row["amount"] = 12.5

    batch = _connector([{"data": [row]}]).fetch_activities(
        "c", ACCOUNT, credentials=CREDS
    )

    (cash,) = batch.cash
    assert (cash.type, cash.amount) == ("DIVIDEND", Decimal("12.5"))
