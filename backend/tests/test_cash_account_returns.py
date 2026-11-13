"""A cash account earns only its interest: no other change in its balance is a gain."""
from datetime import date
from decimal import Decimal as D

from app.models.cash_activity import CashActivity
from app.models.perf import DailyValuation
from app.services.performance_build_service import PerformanceBuildService
from tests.test_perf import _account, _sleeve, _weekdays

MONDAY = date(2025, 3, 3)


def _observed(db, account, values):
    for day, total in zip(_weekdays(MONDAY, len(values)), values):
        db.add(
            DailyValuation(
                account_id=account.id,
                as_of_date=day,
                securities_value=D(0),
                cash_value=D(str(total)),
                total_value=D(str(total)),
                basis="observed",
            )
        )
    db.commit()


def _rows(db, account):
    return {
        r.as_of_date: r
        for r in db.query(DailyValuation).filter(
            DailyValuation.account_id == account.id, DailyValuation.sleeve_id.is_(None)
        )
    }


def test_a_deposit_recorded_late_is_still_not_a_gain(db):
    account = _account(db, name="Pat — Cash Plus Account — 12345678")
    sleeve = _sleeve(db, account)
    _observed(db, account, [1000, 1500, "1500.40", "1500.40"])
    mon, tue, wed, thu = _weekdays(MONDAY, 4)
    # The $500 reached the balance on Tuesday, but its record is dated Thursday.
    db.add_all([
        CashActivity(sleeve_id=sleeve.id, activity_date=thu, type="CONTRIBUTION",
                     amount=D("500"), external_id="c1"),
        CashActivity(sleeve_id=sleeve.id, activity_date=wed, type="INTEREST",
                     amount=D("0.40"), external_id="i1"),
    ])
    db.commit()

    PerformanceBuildService(db).rebuild_account(account.id, today=thu)
    rows = _rows(db, account)

    assert (rows[tue].flow_in, rows[tue].return_factor) == (D("500"), D(1))
    # Wednesday's only gain is the interest; Thursday's late record moves nothing.
    assert rows[wed].flow_in == 0 and rows[wed].flow_out == 0
    assert abs(rows[wed].return_factor - (1 + D("0.40") / D("1500"))) < D("1e-9")
    assert rows[thu].flow_in == 0 and rows[thu].return_factor == D(1)


def test_money_taken_out_is_not_a_loss(db):
    account = _account(db, name="Pat — Cash Plus Account — 12345678")
    _sleeve(db, account)
    _observed(db, account, [1000, 700, 700])
    mon, tue, wed = _weekdays(MONDAY, 3)

    PerformanceBuildService(db).rebuild_account(account.id, today=wed)
    rows = _rows(db, account)

    assert rows[tue].flow_out == D("300") and rows[tue].return_factor == D(1)


def test_an_investment_account_keeps_its_gains(db):
    account = _account(db, name="Pat — Brokerage Account — 12345678")
    _sleeve(db, account)
    _observed(db, account, [1000, 1100])
    mon, tue = _weekdays(MONDAY, 2)

    PerformanceBuildService(db).rebuild_account(account.id, today=tue)

    # Nothing moved in or out, so the rise is a gain, as before.
    assert _rows(db, account)[tue].return_factor == D("1.1")
