"""Lots: what a sale closes, and the figures a brokerage reports for it.

Offline. The rules are checked on hand-worked trades with made-up prices; the
parts that need the hierarchy (a merger across sleeves, the account's lot
method, a year-end price on file) go through the positions service.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.account import Account
from app.models.client import Client
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.services.portfolio_calculation import PortfolioCalculationService
from app.services.price_history_service import set_manual_price
from app.services.tax_lots import (
    MIN_TAX,
    carried_lots,
    is_index_option,
    is_split_option,
    match_lots,
)

D = Decimal
INDEX_PUT = "SPX271217P05000000"
STOCK_PUT = "ABC271217P00050000"


def _t(day, action, qty, price, symbol="ABC", fee=0):
    _t.count += 1
    return SimpleNamespace(
        id=f"t{_t.count}",
        trade_date=date.fromisoformat(day),
        symbol=symbol,
        action=action,
        quantity=D(str(qty)),
        price=D(str(price)),
        commission=D(str(fee)),
    )


_t.count = 0


def _match(trades, **options):
    options.setdefault("as_of", date(2030, 1, 1))
    return match_lots(trades, **options)


# -- wash sales -----------------------------------------------------------


def test_a_loss_on_shares_bought_back_within_30_days_is_carried_in_their_cost():
    result = _match(
        [
            _t("2026-01-05", "BUY", 10, 100),
            _t("2026-01-12", "SELL", 10, 90),
            _t("2026-01-20", "BUY", 10, 92),
            _t("2026-03-02", "SELL", 10, 95),
        ]
    )
    loss, later = result["closed"]

    assert (loss["cost"], loss["proceeds"]) == (D(1000), D(900))
    assert (loss["disallowed_loss"], loss["reported_gain"]) == (D(100), D(0))
    assert loss["adjustments"] == ["wash"]
    # The replacement shares cost 920 and carry the 100 that was disallowed.
    assert (later["cost"], later["reported_gain"]) == (D(1020), D(-70))
    assert later["disallowed_loss"] == D(0)


def test_what_happened_is_untouched_by_how_it_is_reported():
    result = _match(
        [
            _t("2026-01-05", "BUY", 10, 100),
            _t("2026-01-12", "SELL", 10, 90),
            _t("2026-01-20", "BUY", 10, 92),
            _t("2026-03-02", "SELL", 10, 95),
        ]
    )
    happened = [row["realized_gain"] for row in result["closed"]]

    assert happened == [D(-100), D(30)]
    # Once everything is sold the two readings add up to the same money.
    assert sum(happened) == sum(row["reported_gain"] for row in result["closed"])


def test_shares_bought_shortly_before_the_sale_also_replace_it():
    result = _match(
        [
            _t("2026-01-05", "BUY", 10, 100),
            _t("2026-01-10", "BUY", 10, 98),
            _t("2026-01-12", "SELL", 10, 90),
        ]
    )
    (loss,) = result["closed"]
    (held,) = result["open"]

    assert loss["disallowed_loss"] == D(100)
    assert (held["cost_basis"], held["tax_cost"]) == (D(980), D(1080))


def test_only_the_shares_bought_back_disallow_the_loss():
    result = _match(
        [
            _t("2026-01-05", "BUY", 10, 100),
            _t("2026-01-12", "SELL", 10, 90),
            _t("2026-01-20", "BUY", 4, 92),
        ]
    )
    (loss,) = result["closed"]

    assert (loss["disallowed_loss"], loss["reported_gain"]) == (D(40), D(-60))


def test_a_purchase_more_than_30_days_later_changes_nothing():
    result = _match(
        [
            _t("2026-01-05", "BUY", 10, 100),
            _t("2026-01-12", "SELL", 10, 90),
            _t("2026-02-12", "BUY", 10, 92),
        ]
    )

    assert result["closed"][0]["disallowed_loss"] == D(0)
    assert result["open"][0]["tax_cost"] == D(920)


def test_the_rest_of_the_same_purchase_is_not_a_replacement():
    result = _match(
        [_t("2026-01-05", "BUY", 20, 100), _t("2026-01-12", "SELL", 10, 90)]
    )

    assert result["closed"][0]["disallowed_loss"] == D(0)


def test_each_replacement_share_is_used_once():
    result = _match(
        [
            _t("2026-01-05", "BUY", 10, 100),
            _t("2026-01-06", "BUY", 10, 100),
            _t("2026-01-12", "SELL", 20, 90),
            _t("2026-01-20", "BUY", 10, 92),
        ]
    )

    assert sum(row["disallowed_loss"] for row in result["closed"]) == D(100)


def test_the_holding_time_of_the_shares_sold_carries_to_their_replacement():
    result = _match(
        [
            _t("2024-01-02", "BUY", 10, 100),
            _t("2025-02-03", "SELL", 10, 90),
            _t("2025-02-10", "BUY", 10, 92),
            _t("2025-03-10", "SELL", 10, 120),
        ]
    )
    loss, gain = result["closed"]

    assert (loss["term"], gain["term"]) == ("long", "long")
    assert gain["long_term_gain"] == D(180) and gain["short_term_gain"] == D(0)


# -- options --------------------------------------------------------------


def test_index_options_are_recognised_by_their_root():
    assert is_index_option(INDEX_PUT)
    assert not is_index_option(STOCK_PUT)
    assert not is_index_option("SPX")
    # Options on the gold and silver trusts are split 60/40 as the brokerage
    # shows them, but they are not index options and are never marked.
    assert not is_index_option("GLD270115P00350000")
    assert is_split_option("GLD270115P00350000") and is_split_option(INDEX_PUT)
    assert not is_split_option(STOCK_PUT)


def test_a_written_option_on_a_commodity_trust_that_expires_is_split_60_40():
    put = "SLV270115P00050000"
    result = _match(
        [_t("2026-01-05", "SELL", 25, 60, put), _t("2026-02-06", "BUY", 25, 0, put)]
    )
    (row,) = result["closed"]

    assert row["term"] == "mixed" and "written_option" not in row["adjustments"]
    assert (row["short_term_gain"], row["long_term_gain"]) == (D(600), D(900))


def test_an_index_options_gain_is_60_percent_long_term_however_briefly_held():
    result = _match(
        [
            _t("2026-03-02", "BUY", 1, 10000, INDEX_PUT),
            _t("2026-03-09", "SELL", 1, 15000, INDEX_PUT),
        ]
    )
    (row,) = result["closed"]

    assert row["term"] == "mixed" and row["adjustments"] == ["index_option"]
    assert (row["long_term_gain"], row["short_term_gain"]) == (D(3000), D(2000))


def test_an_index_option_open_over_a_year_end_is_marked_to_that_days_price():
    trades = [
        _t("2025-09-15", "BUY", 1, 50000, INDEX_PUT),
        _t("2026-03-10", "SELL", 1, 38000, INDEX_PUT),
    ]
    marks = {INDEX_PUT: [(date(2025, 12, 31), D("400"))]}

    result = _match(trades, marks=marks)
    (year_end,) = result["marked"]
    (sale,) = result["closed"]

    # 2025 takes the fall to 40,000; 2026 only what happened after it.
    assert year_end["closed_at"] == date(2025, 12, 31)
    assert (year_end["reported_gain"], year_end["realized_gain"]) == (D(-10000), D(0))
    assert year_end["adjustments"] == ["index_option", "mark"]
    assert (sale["cost"], sale["reported_gain"]) == (D(40000), D(-2000))
    # What happened is one loss of 12,000, on the day the contract was sold.
    assert sale["realized_gain"] == D(-12000)


def test_with_no_year_end_price_the_lot_is_left_whole_and_says_so():
    result = _match(
        [
            _t("2025-09-15", "BUY", 1, 50000, INDEX_PUT),
            _t("2026-03-10", "SELL", 1, 38000, INDEX_PUT),
        ]
    )
    (sale,) = result["closed"]

    assert result["marked"] == []
    assert sale["reported_gain"] == D(-12000)
    assert "unmarked" in sale["adjustments"]


def test_a_written_option_bought_back_is_short_term_whatever_the_time():
    result = _match(
        [
            _t("2024-01-08", "SELL", 2, 500, STOCK_PUT),
            _t("2025-06-09", "BUY", 2, 100, STOCK_PUT),
        ]
    )
    (row,) = result["closed"]

    assert row["term"] == "short" and "written_option" in row["adjustments"]
    assert (row["cost"], row["proceeds"], row["short_term_gain"]) == (
        D(200),
        D(1000),
        D(800),
    )


def test_an_option_on_a_commodity_trust_is_not_marked_at_a_year_end():
    put = "GLD270115P00350000"
    result = _match(
        [_t("2025-09-15", "BUY", 1, 5000, put), _t("2026-03-10", "SELL", 1, 3800, put)],
        marks={put: [(date(2025, 12, 31), D("40"))]},
    )
    (sale,) = result["closed"]

    assert result["marked"] == [] and "unmarked" not in sale["adjustments"]
    assert (sale["cost"], sale["reported_gain"]) == (D(5000), D(-1200))
    assert (sale["long_term_gain"], sale["short_term_gain"]) == (D(-720), D(-480))


# -- which lots a sale closes ---------------------------------------------


def _three_lots():
    return [
        _t("2024-01-02", "BUY", 10, 100),
        _t("2026-02-02", "BUY", 10, 120),
        _t("2026-02-09", "BUY", 10, 90),
        _t("2026-06-01", "SELL", 10, 110),
    ]


def test_first_in_first_out_sells_the_oldest_lot():
    (row,) = _match(_three_lots())["closed"]
    assert (row["opened_at"], row["reported_gain"]) == (date(2024, 1, 2), D(100))


def test_min_tax_sells_a_short_term_loss_before_any_gain():
    (row,) = _match(_three_lots(), method=MIN_TAX)["closed"]
    assert (row["opened_at"], row["reported_gain"]) == (date(2026, 2, 2), D(-100))


def test_min_tax_prefers_a_long_term_gain_to_a_short_term_one():
    trades = [
        _t("2024-01-02", "BUY", 10, 100),
        _t("2026-02-09", "BUY", 10, 90),
        _t("2026-06-01", "SELL", 10, 110),
    ]
    (row,) = _match(trades, method=MIN_TAX)["closed"]
    assert row["opened_at"] == date(2024, 1, 2)


def test_min_tax_takes_a_same_day_purchase_as_bought_after_the_sale():
    """The source gives days, not times; the older shares are the ones sold."""
    trades = [
        _t("2026-03-23", "BUY", 10, 100),
        _t("2026-04-13", "BUY", 10, 109),
        _t("2026-04-13", "SELL", 10, 110),
    ]
    (row,) = _match(trades, method=MIN_TAX)["closed"]
    assert row["opened_at"] == date(2026, 3, 23)


def test_replacement_shares_go_to_the_oldest_lot_sold_whatever_the_method():
    trades = [
        _t("2026-07-20", "BUY", 10, 100),
        _t("2026-07-27", "BUY", 10, 104),
        _t("2026-08-03", "SELL", 20, 98),
        _t("2026-08-10", "BUY", 10, 99),
    ]
    for method in ("FIFO", MIN_TAX):
        closed = _match(list(trades), method=method)["closed"]
        disallowed = {row["opened_at"]: row["disallowed_loss"] for row in closed}
        assert disallowed == {date(2026, 7, 20): D(20), date(2026, 7, 27): D(0)}


# -- share exchanges ------------------------------------------------------


def test_carried_lots_keep_their_cost_and_dates_over_the_new_share_count():
    lots = [
        {
            "quantity": D(60),
            "unit": D(10),
            "tax_unit": D(11),
            "opened_at": date(2025, 3, 3),
            "held_from": date(2025, 3, 3),
            "replacement": False,
        },
        {
            "quantity": D(40),
            "unit": D(20),
            "tax_unit": D(20),
            "opened_at": date(2025, 9, 1),
            "held_from": date(2025, 9, 1),
            "replacement": False,
        },
    ]

    first, second = carried_lots(lots, D(100), D(1), D(50))

    assert (first["quantity"], second["quantity"]) == (D(30), D(20))
    assert first["quantity"] * first["unit"] == D(600)
    assert first["quantity"] * first["tax_unit"] == D(660)
    assert second["quantity"] * second["unit"] == D(800)
    assert first["opened_at"] == date(2025, 3, 3)


@pytest.fixture
def account(db):
    owner = Client(name="Lot Owner", email="lots@example.com")
    db.add(owner)
    db.flush()
    account = Account(client_id=owner.id, name="Lots")
    db.add(account)
    db.commit()
    return account


def _sleeve(db, account, name) -> Sleeve:
    strategy = Strategy(name=name)
    db.add(strategy)
    db.flush()
    sleeve = Sleeve(
        account_id=account.id, strategy_id=strategy.id, accounting_method="FIFO"
    )
    db.add(sleeve)
    db.commit()
    return sleeve


def _stored(db, sleeve, day, action, qty, price, symbol="ABC", notes=None):
    db.add(
        Trade(
            sleeve_id=sleeve.id,
            trade_date=date.fromisoformat(day),
            symbol=symbol,
            action=action,
            quantity=D(str(qty)),
            price=D(str(price)),
            commission=D(0),
            notes=notes,
        )
    )
    db.commit()


def test_shares_swapped_in_a_merger_keep_their_opening_date_across_sleeves(db, account):
    """The old shares sit in one sleeve and the new ones arrive in another."""
    other, stocks = _sleeve(db, account, "Other"), _sleeve(db, account, "Stocks")
    _stored(db, other, "2024-03-04", "BUY", 100, 12, "OLD")
    _stored(db, other, "2026-01-09", "SELL", 100, 12, "OLD", "Merger: OLD CORP")
    _stored(db, stocks, "2026-01-09", "BUY", 40, 30, "NEW", "Merger: NEW CORP")
    _stored(db, stocks, "2026-02-02", "SELL", 40, 35, "NEW")

    calc = PortfolioCalculationService(db)
    gave, got = calc.calculate_positions(other.id), calc.calculate_positions(stocks.id)

    # Nothing was realised on the exchange itself.
    assert gave["closed"] == [] and gave["open"] == []
    (sale,) = got["closed"]
    assert sale["opened_at"] == date(2024, 3, 4) and sale["term"] == "long"
    assert (sale["cost"], sale["reported_gain"]) == (D(1200), D(200))


def test_a_merger_paid_in_cash_is_still_a_sale(db, account):
    sleeve = _sleeve(db, account, "Stocks")
    _stored(db, sleeve, "2025-03-03", "BUY", 10, 50, "OLD")
    _stored(db, sleeve, "2026-01-09", "SELL", 10, 60, "OLD", "Merger: OLD CORP")

    (sale,) = PortfolioCalculationService(db).calculate_positions(sleeve.id)["closed"]
    assert sale["reported_gain"] == D(100)


# -- the account's settings -----------------------------------------------


def test_the_accounts_cost_basis_method_decides_which_lot_is_sold(db, account, client):
    sleeve = _sleeve(db, account, "Stocks")
    for day, action, qty, price in [
        ("2024-01-02", "BUY", 10, 100),
        ("2026-02-02", "BUY", 10, 120),
        ("2026-06-01", "SELL", 10, 110),
    ]:
        _stored(db, sleeve, day, action, qty, price)
    calc = PortfolioCalculationService(db)
    url = f"/api/v1/clients/{account.client_id}/accounts/{account.id}"

    assert client.get(url).json()["cost_basis_method"] == "FIFO"
    assert calc.calculate_positions(sleeve.id)["closed"][0]["reported_gain"] == D(100)

    changed = client.patch(url, json={"cost_basis_method": "MIN_TAX"})

    assert changed.status_code == 200
    assert changed.json()["cost_basis_method"] == "MIN_TAX"
    assert calc.calculate_positions(sleeve.id)["closed"][0]["reported_gain"] == D(-100)
    assert client.patch(url, json={"cost_basis_method": "LIFO"}).status_code == 422


def test_a_year_end_price_entered_by_hand_marks_the_option(db, account):
    sleeve = _sleeve(db, account, "Options")
    _stored(db, sleeve, "2025-09-15", "BUY", 1, 50000, INDEX_PUT)
    _stored(db, sleeve, "2026-03-10", "SELL", 1, 38000, INDEX_PUT)
    set_manual_price(db, INDEX_PUT, date(2025, 12, 31), D("380"))
    set_manual_price(db, INDEX_PUT, date(2025, 12, 31), D("400"))  # corrected

    positions = PortfolioCalculationService(db).calculate_positions(sleeve.id)

    assert positions["marked"][0]["reported_gain"] == D(-10000)
    assert positions["closed"][0]["reported_gain"] == D(-2000)
    with pytest.raises(ValueError):
        set_manual_price(db, INDEX_PUT, date(2025, 12, 31), D(0))


def test_closed_positions_show_what_the_brokerage_reports(db, account, client):
    sleeve = _sleeve(db, account, "Stocks")
    for day, action, qty, price in [
        ("2026-01-05", "BUY", 10, 100),
        ("2026-01-12", "SELL", 10, 90),
        ("2026-01-20", "BUY", 10, 92),
    ]:
        _stored(db, sleeve, day, action, qty, price)

    body = client.get(
        f"/api/v1/clients/{account.client_id}/accounts/{account.id}"
        f"/sleeves/{sleeve.id}/positions/closed"
    ).json()
    (row,) = body["positions"]

    assert body["total_realized_gain"] == -100
    assert (body["total_reported_gain"], body["total_disallowed_loss"]) == (0, 100)
    assert (row["cost"], row["proceeds"], row["disallowed_loss"]) == (1000, 900, 100)
    assert row["term"] == "short" and row["adjustments"] == ["wash"]
