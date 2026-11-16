"""Upload and import through the routes: the advisor's door and the client's.

Every account, ticker and figure here is invented.
"""
import csv
import io

import pytest

from app.api.deps import get_current_user
from app.main import app
from app.models.account import Account
from app.models.user import AccountAccess, User
from app.models.client import Client
from app.models.trade import Trade
from tests.test_vanguard_report import account  # noqa: F401 - fixture

TEMPLATE = (
    "Date,Type,Symbol,Quantity,Price,Fees,Amount\n"
    "2026-10-05,Buy,EEE,4,25,,\n"
    "2026-10-05,Dividend,FFF,,,,3.00\n"
)


def _report_xlsx(*rows):
    from openpyxl import Workbook

    book = Workbook()
    for line in (
        ("Custom report created on: 11/12/2026.",),
        (),
        ("Settlement date", "Trade date", "Symbol", "Name", "Type", "Account type",
         "Quantity", "Price", "Commission & fees**", "Amount"),
        *rows,
    ):
        book.active.append(list(line))
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _files(content, name="activity.csv"):
    return {"file": (name, content, "application/octet-stream")}


def _as_client(client_id):
    user = User(id="u-client", email="pat@example.com", name="Pat", role="client",
                client_id=client_id)
    app.dependency_overrides[get_current_user] = lambda: user


def _base(ba, db):
    acct = db.get(Account, ba.account_id)
    return f"/api/v1/clients/{acct.client_id}/accounts/{acct.id}/imports"


def test_the_advisor_previews_then_imports(client, db, account):
    base = _base(account, db)
    preview = client.post(f"{base}/preview", files=_files(TEMPLATE.encode()))
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert (body["file_kind"], body["to_add_trades"], body["to_add_cash"]) == ("template", 1, 1)
    assert db.query(Trade).count() == 0  # a preview writes nothing

    done = client.post(base, files=_files(TEMPLATE.encode()))
    assert done.status_code == 200, done.text
    assert (done.json()["added_trades"], done.json()["added_cash"]) == (1, 1)
    again = client.post(f"{base}/preview", files=_files(TEMPLATE.encode())).json()
    assert (again["to_add_trades"], again["to_add_cash"]) == (0, 0)


def test_a_vanguard_report_naming_another_account_is_refused(client, db, account):
    content = _report_xlsx(("10/6/2026", "10/5/2026", "EEE", "EEE ETF", "Buy", "MARGIN",
                            "4.0000", "$25.0000", "Free", "-$100.0000"))
    base = _base(account, db)
    wrong = client.post(f"{base}/preview",
                        files=_files(content, "customActivityReport_99990000.xlsx"))
    assert wrong.status_code == 422 and "0000" in wrong.json()["detail"]
    right = client.post(f"{base}/preview",
                        files=_files(content, "customActivityReport_12345678.xlsx"))
    assert right.status_code == 200 and right.json()["file_kind"] == "vanguard_activity"


def test_a_plaid_linked_account_knows_only_its_last_four_and_takes_its_own_file(client, db, account):
    """Plaid gives an account's last four, never its full number."""
    acct = db.get(Account, account.account_id)
    account.name, account.mask, acct.account_number = "INDIVIDUAL", "4321", None
    db.commit()
    content = _report_xlsx(("10/6/2026", "10/5/2026", "EEE", "EEE ETF", "Buy", "MARGIN",
                            "4.0000", "$25.0000", "Free", "-$100.0000"))
    base = _base(account, db)
    own = client.post(f"{base}/preview", files=_files(content, "customActivityReport_87654321.xlsx"))
    assert own.status_code == 200, own.text
    other = client.post(f"{base}/preview", files=_files(content, "customActivityReport_87650000.xlsx"))
    assert other.status_code == 422 and "0000" in other.json()["detail"]


def test_files_it_cannot_read_are_refused_with_a_reason(client, db, account):
    base = _base(account, db)
    assert client.post(f"{base}/preview", files=_files(b"%PDF", "x.pdf")).status_code == 415
    bad = client.post(f"{base}/preview", files=_files(b"Date,Type\n2026-10-05,Gift\n"))
    assert bad.status_code == 422 and "Gift" in bad.json()["detail"]


def test_a_client_imports_into_an_account_they_own(client, db, account):
    acct = db.get(Account, account.account_id)
    _as_client(acct.client_id)
    response = client.post(f"/api/v1/portal/accounts/{acct.id}/imports",
                           files=_files(TEMPLATE.encode()))
    assert response.status_code == 200, response.text
    assert response.json()["added_trades"] == 1


def test_a_client_cannot_import_into_a_shared_account_or_by_the_advisor_door(
    client, db, account
):
    acct = db.get(Account, account.account_id)
    other = Client(name="Sam Example", email="sam@example.com")
    db.add(other)
    db.flush()
    db.add(AccountAccess(client_id=other.id, account_id=acct.id))
    db.commit()
    _as_client(other.id)
    shared = client.post(f"/api/v1/portal/accounts/{acct.id}/imports",
                         files=_files(TEMPLATE.encode()))
    assert shared.status_code == 404
    advisor_door = client.post(f"{_base(account, db)}/preview", files=_files(TEMPLATE.encode()))
    assert advisor_door.status_code == 403


def test_an_advisor_previewing_a_client_can_import_as_the_client_does(client, db, account):
    acct = db.get(Account, account.account_id)
    response = client.post(
        f"/api/v1/portal/accounts/{acct.id}/imports?as_client={acct.client_id}",
        files=_files(TEMPLATE.encode()),
    )
    assert response.status_code == 200 and response.json()["added_trades"] == 1


def test_an_account_not_set_up_for_files_says_so(client, db):
    owner = Client(name="Lee Example", email="lee@example.com")
    db.add(owner)
    db.flush()
    acct = Account(client_id=owner.id, name="Hand-kept")
    db.add(acct)
    db.commit()
    response = client.post(
        f"/api/v1/clients/{owner.id}/accounts/{acct.id}/imports/preview",
        files=_files(TEMPLATE.encode()),
    )
    assert response.status_code == 409


def test_the_check_says_when_holdings_last_agreed_and_first_differed(db, account):
    """So only the dates that are missing need downloading."""
    from datetime import date
    from decimal import Decimal as D

    from app.models.perf import DailyHolding
    from app.services.account_import_service import AccountImportService
    from tests.test_vanguard_report import _on_file

    acct = db.get(Account, account.account_id)
    _on_file(db, account, date(2026, 9, 1), "AAA", "BUY", 10, 50)
    # Recorded holdings: 10 AAA on 1 and 2 Oct; on 9 Oct the custodian shows 4,
    # since a sale of 6 on 5 Oct never reached us.
    for day, qty in ((date(2026, 10, 1), 10), (date(2026, 10, 2), 10), (date(2026, 10, 9), 4),
                     (date(2026, 10, 12), 4)):
        db.add(DailyHolding(account_id=acct.id, as_of_date=day, symbol="AAA",
                            quantity=D(qty), price=D(50), market_value=D(qty * 50)))
    db.commit()

    service = AccountImportService(db)
    check = service.holdings_check(acct)
    assert (check["last_agreed"], check["first_differed"]) == (date(2026, 10, 2), date(2026, 10, 9))
    assert check["download_from"] == date(2026, 10, 2)
    assert check["differences"] == [{"symbol": "AAA", "custodian_quantity": 4.0, "our_quantity": 10.0}]

    # Once the sale is on file, they agree throughout.
    _on_file(db, account, date(2026, 10, 5), "AAA", "SELL", 6, 55, ext="sale")
    db.commit()
    check = service.holdings_check(acct)
    assert (check["last_agreed"], check["first_differed"], check["download_from"]) == (
        date(2026, 10, 12), None, None
    )
    assert check["differences"] == []


def test_when_even_the_first_record_differs_the_whole_history_is_asked_for(db, account):
    from datetime import date
    from decimal import Decimal as D

    from app.models.perf import DailyHolding
    from app.services.account_import_service import AccountImportService

    acct = db.get(Account, account.account_id)
    account.transactions_synced_through = date(2026, 10, 9)  # a feed that gives transactions
    db.add(DailyHolding(account_id=acct.id, as_of_date=date(2026, 10, 9), symbol="AAA",
                        quantity=D(4), price=D(50), market_value=D(200)))
    db.commit()
    check = AccountImportService(db).holdings_check(acct)
    assert check["last_agreed"] is None and check["first_differed"] == date(2026, 10, 9)
    # Never a guessed date: what is missing is somewhere before the first record.
    assert check["download_from"] is None
    # And not "recent trades still arriving", even the day after: history is missing.
    from app.services.account_health import account_health

    assert account_health(db, acct, date(2026, 10, 10))["state"] == "incomplete"


def test_the_check_can_be_asked_for_before_any_upload(client, db, account):
    acct = db.get(Account, account.account_id)
    advisor = client.get(f"{_base(account, db)}/check")
    assert advisor.status_code == 200 and advisor.json() is None  # nothing recorded yet
    _as_client(acct.client_id)
    own = client.get(f"/api/v1/portal/accounts/{acct.id}/imports/check")
    assert own.status_code == 200


def test_a_file_naming_a_trade_the_feed_could_not_takes_its_cash_back(client, db, account):
    """The feed kept the cash of a trade it could not name; once the file names
    that trade, its cash is counted with the file's row, once, and a later
    refresh does not put it back on the feed's row."""
    from datetime import date
    from decimal import Decimal as D

    from app.connectors.models import ActivityBatch, RawActivity
    from app.models.brokerage_connection import BrokerageActivity
    from app.services.connection_service import ON_FILE, ConnectionService

    unnamed = RawActivity(source_id="plaid:u1", type="PLAID BUY/BUY", occurred_on=date(2026, 10, 6),
                          symbol=None, outcome="skipped:unreadable", cash_amount=D("-100"),
                          is_external_flow=False, payload={"amount": 100})
    db.add(BrokerageActivity(
        brokerage_account_id=account.id, source_activity_id="plaid:u1",
        activity_date=date(2026, 10, 6), type="PLAID BUY/BUY", outcome="skipped:unreadable",
        cash_amount=D("-100"), payload={"amount": 100}))
    db.commit()
    content = _report_xlsx(("10/6/2026", "10/5/2026", "EEE", "EEE ETF", "Buy", "MARGIN",
                            "4.0000", "$25.0000", "Free", "-$100.0000"))
    done = client.post(_base(account, db), files=_files(content, "report.xlsx"))
    assert done.status_code == 200, done.text

    feed = db.query(BrokerageActivity).filter(BrokerageActivity.source_activity_id == "plaid:u1").one()
    assert (feed.outcome, feed.cash_amount) == (ON_FILE, D("0"))

    # The next refresh hands the same row back; it stays taken back.
    ConnectionService(db, connector=object()).ingest_batch(
        account, ActivityBatch(trades=[], cash=[], raw=[unnamed], skipped={}, security_type_sources={}))
    db.refresh(feed)
    assert (feed.outcome, feed.cash_amount) == (ON_FILE, D("0"))


def test_a_feed_trade_a_day_off_from_the_reports_is_the_same_trade_and_its_cash_counts_once(
    client, db, account
):
    """The report has the buy on the 5th; the feed, working back from settlement
    around a bank holiday, dates it the 6th and prices it a fraction differently.
    It is the report's trade: not added again, and its row keeps no cash."""
    from datetime import datetime, timezone
    from decimal import Decimal as D

    from app.connectors.models import ActivityBatch, NormalizedTrade, RawActivity, TradeAction
    from app.models.brokerage_connection import BrokerageActivity
    from app.services.connection_service import REPORT_TWIN, ConnectionService

    content = _report_xlsx(("10/6/2026", "10/5/2026", "EEE", "EEE ETF", "Buy", "MARGIN",
                            "4.0000", "$25.0000", "Free", "-$100.0000"))
    assert client.post(_base(account, db), files=_files(content, "report.xlsx")).status_code == 200
    before = db.query(Trade).count()

    feed = NormalizedTrade(external_id="plaid:t1", symbol="EEE", action=TradeAction.BUY,
                           quantity=D(4), price=D("25.004"),
                           executed_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
                           commission=D(0), source="plaid", security_type="ETF", notes="EEE ETF")
    raw = RawActivity(source_id="plaid:t1", type="PLAID BUY/BUY", occurred_on=feed.executed_at.date(),
                      symbol="EEE", outcome="trade", cash_amount=D("-100.02"),
                      is_external_flow=False, payload={"amount": 100.02})
    ConnectionService(db, connector=object()).ingest_batch(
        account, ActivityBatch(trades=[feed], cash=[], raw=[raw], skipped={}, security_type_sources={}))

    assert db.query(Trade).count() == before
    row = db.query(BrokerageActivity).filter(BrokerageActivity.source_activity_id == "plaid:t1").one()
    assert (row.outcome, row.cash_amount) == (REPORT_TWIN, D("0"))


def test_record_gaps_name_the_holdings_that_differ(client, db, account):  # noqa: F811
    from datetime import date
    from decimal import Decimal as D

    from app.models.perf import DailyHolding

    acct = db.get(Account, account.account_id)
    account.transactions_synced_through = date(2026, 10, 9)  # a feed that gives transactions
    db.add(DailyHolding(account_id=acct.id, as_of_date=date(2026, 10, 9), symbol="AAA",
                        quantity=D(4), price=D(50), market_value=D(200)))
    db.commit()
    got = client.get(f"/api/v1/portal/accounts/{acct.id}/record-gaps",
                     params={"as_client": acct.client_id})
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["holdings"] == [{"symbol": "AAA", "custodian_quantity": 4.0, "our_quantity": 0.0}]
    assert body["first_differed"] == "2026-10-09" and body["last_agreed"] is None
    assert body["cash"] is None
    # An account that is not in view is a 404, as everywhere in the portal.
    assert client.get("/api/v1/portal/accounts/nope/record-gaps",
                      params={"as_client": acct.client_id}).status_code == 404


TEMPLATE_THROUGH = (
    "Date,Type,Symbol,Quantity,Price,Fees,Amount\n"
    "2026-10-05,Buy,EEE,4,25,,\n"
    "2026-10-05,Deposit,,,,,100.00\n"
    "2026-11-01,Through,,,,,\n"
)


def test_a_file_says_how_far_it_is_complete():
    from datetime import date

    from app.services.account_import_service import read_upload

    kind, rows, through = read_upload("mine.csv", TEMPLATE_THROUGH.encode())
    assert kind == "template" and through == date(2026, 11, 1)
    assert [r.kind for r in rows] == ["Buy", "Funds Received"]  # a Through row is not activity
    _, _, none = read_upload("mine.csv", TEMPLATE_THROUGH.replace("2026-11-01,Through,,,,,\n", "").encode())
    assert none is None
    report = _report_xlsx(("10/5/2026", "10/5/2026", "EEE", "EEE CORP", "Buy", "MARGIN", "4", "$25.00", "Free", "-$100.00"))
    from openpyxl import load_workbook
    import io

    book = load_workbook(io.BytesIO(report))
    book.active["A2"] = "This report only includes transactions that were settled from: 01/01/2019 to 11/15/2026."
    out = io.BytesIO()
    book.save(out)
    kind, _, through = read_upload("customActivityReport_12345678.xlsx", out.getvalue())
    assert kind == "vanguard_activity" and through == date(2026, 11, 15)


def test_a_file_complete_through_a_recorded_day_lets_the_opening_be_worked_back(db, account):
    """The institution lists 10 shares on 8 Nov; the file shows 4 bought and says
    it is complete through 9 Nov, so the account opened holding 6."""
    from datetime import date
    from decimal import Decimal as D

    from app.models.perf import DailyHolding
    from app.models.trade import Trade
    from app.services.account_health import account_health
    from app.services.account_import_service import AccountImportService

    acct = db.get(Account, account.account_id)
    db.add(DailyHolding(account_id=acct.id, sleeve_id=account.default_sleeve_id, as_of_date=date(2026, 11, 8),
                        symbol="EEE", quantity=D(10), price=D(25), market_value=D(250)))
    db.commit()
    assert account.transactions_synced_through is None
    service = AccountImportService(db)
    preview = service.preview(acct, "mine.csv", TEMPLATE_THROUGH.replace("2026-11-01", "2026-11-09").encode())
    assert preview["complete_through"] == date(2026, 11, 9)
    service.apply(acct, "mine.csv", TEMPLATE_THROUGH.replace("2026-11-01", "2026-11-09").encode())
    db.refresh(account)
    assert account.transactions_synced_through == date(2026, 11, 9)
    opening = [t for t in db.query(Trade) if (t.notes or "").startswith("Opening")]
    assert [(t.symbol, t.quantity) for t in opening] == [("EEE", D(6))]
    assert service.holdings_check(acct)["differences"] == []
    assert account_health(db, acct, date(2026, 11, 10))["state"] != "incomplete"


def test_an_account_with_holdings_and_no_transactions_at_all_has_nothing_to_check(db, account):
    from datetime import date
    from decimal import Decimal as D

    from app.models.perf import DailyHolding
    from app.services.account_import_service import AccountImportService

    acct = db.get(Account, account.account_id)
    db.add(DailyHolding(account_id=acct.id, as_of_date=date(2026, 11, 8), symbol="EEE",
                        quantity=D(10), price=D(25), market_value=D(250)))
    db.commit()
    assert account.transactions_synced_through is None
    assert AccountImportService(db).holdings_check(acct) is None  # the holdings are the record


# ----------------------------------------------------------------------
# A feed's one row for several of a file's (one per source of a plan's money)
# ----------------------------------------------------------------------


def _feed_buy(db, account, ext, qty, price, day, symbol="QQQ"):
    from datetime import datetime, timezone
    from decimal import Decimal as D

    from app.connectors.models import ActivityBatch, NormalizedTrade, RawActivity, TradeAction
    from app.services.connection_service import ConnectionService

    feed = NormalizedTrade(external_id=ext, symbol=symbol, action=TradeAction.BUY, quantity=D(str(qty)),
                           price=D(str(price)), executed_at=datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
                           commission=D(0), source="plaid", security_type="MUTUAL_FUND", notes="QQQ FUND")
    raw = RawActivity(source_id=ext, type="PLAID BUY/BUY", occurred_on=day, symbol=symbol, outcome="trade",
                      cash_amount=-D(str(qty)) * D(str(price)), is_external_flow=False, payload={})
    return ConnectionService(db, connector=object()).ingest_batch(
        account, ActivityBatch(trades=[feed], cash=[], raw=[raw], skipped={}, security_type_sources={}))


def _two_source_report():
    # Pre-tax and employer match, each its own row; the feed reports them as one.
    return _report_xlsx(
        ("10/23/2026", "10/23/2026", "QQQ", "QQQ FUND", "Buy", "CASH", "1.4930", "$132.3000", "Free", "-$197.5000"),
        ("10/23/2026", "10/23/2026", "QQQ", "QQQ FUND", "Buy", "CASH", "1.1950", "$132.3000", "Free", "-$158.1000"),
    )


def test_a_feed_row_that_is_several_of_the_files_rows_is_not_counted_again(client, db, account):
    from datetime import date
    from decimal import Decimal as D

    from app.models.brokerage_connection import BrokerageActivity
    from app.services.connection_service import REPORT_TWIN

    assert client.post(_base(account, db), files=_files(_two_source_report(), "report.xlsx")).status_code == 200
    before = db.query(Trade).count()
    _feed_buy(db, account, "plaid:t9", "2.688", "132.30", date(2026, 10, 22))  # a day earlier, three places
    assert db.query(Trade).count() == before
    row = db.query(BrokerageActivity).filter(BrokerageActivity.source_activity_id == "plaid:t9").one()
    assert (row.outcome, row.cash_amount) == (REPORT_TWIN, D("0"))


def test_a_file_whose_rows_make_up_a_feed_row_already_here_adds_nothing(client, db, account):
    from datetime import date

    _feed_buy(db, account, "plaid:t9", "2.688", "132.30", date(2026, 10, 22))
    before = db.query(Trade).count()
    plan_response = client.post(_base(account, db) + "/preview", files=_files(_two_source_report(), "report.xlsx"))
    assert plan_response.status_code == 200, plan_response.text
    body = plan_response.json()
    assert (body["to_add_trades"], body["on_file_trades"]) == (0, 2)
    client.post(_base(account, db), files=_files(_two_source_report(), "report.xlsx"))
    assert db.query(Trade).filter(Trade.symbol == "QQQ").count() == 1  # the feed's row alone; the file's two are not added


def test_rows_that_do_not_add_up_to_the_feed_row_are_not_its_twin(client, db, account):
    from datetime import date

    assert client.post(_base(account, db), files=_files(_two_source_report(), "report.xlsx")).status_code == 200
    before = db.query(Trade).count()
    _feed_buy(db, account, "plaid:far", "2.700", "132.30", date(2026, 10, 22))   # not their sum
    _feed_buy(db, account, "plaid:price", "2.688", "133.50", date(2026, 10, 22))  # not their price
    _feed_buy(db, account, "plaid:late", "2.688", "132.30", date(2026, 11, 3))    # not their day
    assert db.query(Trade).count() == before + 3


def test_the_repair_finds_a_feed_row_stored_before_it_could_be_recognised(client, db, account):
    from datetime import date
    from decimal import Decimal as D

    from app.models.brokerage_connection import BrokerageActivity
    from app.services.connection_service import REPORT_TWIN
    from app.services.feed_twins import repair

    # The feed's row first, then the file: the upload recognises it, so to model the
    # old state store the feed's trade beside the file's rows directly.
    assert client.post(_base(account, db), files=_files(_two_source_report(), "report.xlsx")).status_code == 200
    db.add(Trade(sleeve_id=account.default_sleeve_id, trade_date=date(2026, 10, 22), symbol="QQQ", action="BUY",
                 quantity=D("2.688"), price=D("132.30"), commission=D(0), external_id="plaid:old", security_type="MUTUAL_FUND"))
    db.add(BrokerageActivity(brokerage_account_id=account.id, source_activity_id="plaid:old", type="PLAID BUY/BUY",
                             activity_date=date(2026, 10, 22), symbol="QQQ", outcome="trade", cash_amount=D("-355.6"),
                             is_external_flow=False, payload={}))
    db.commit()
    shown = repair(db)
    assert [(d["symbol"], d["quantity"], d["file_rows"]) for d in shown["duplicates"]] == [("QQQ", D("2.688"), 2)]
    assert db.query(Trade).filter(Trade.external_id == "plaid:old").count() == 1  # showing changes nothing
    done = repair(db, apply=True)
    assert done["rebuilt"] == 1
    assert db.query(Trade).filter(Trade.external_id == "plaid:old").count() == 0
    row = db.query(BrokerageActivity).filter(BrokerageActivity.source_activity_id == "plaid:old").one()
    assert (row.outcome, row.cash_amount) == (REPORT_TWIN, D("0"))
    assert repair(db)["duplicates"] == []  # safe to repeat


def test_summing_rows_to_a_total_prefers_the_fewest_and_respects_the_window():
    from datetime import date
    from decimal import Decimal as D

    from app.services.twin_match import sum_to

    day = date(2026, 10, 22)
    parts = [("a", D("1.493"), D("132.30"), date(2026, 10, 23)), ("b", D("1.195"), D("132.30"), date(2026, 10, 23)),
             ("c", D("2.688"), D("132.30"), date(2026, 10, 23)), ("d", D("0.5"), D("132.30"), date(2026, 10, 23))]
    assert sum_to(D("2.688"), D("132.30"), day, parts[:2] + parts[3:]) == ["a", "b"]
    assert sum_to(D("2.688"), D("132.30"), day, parts[:2] + [("x", D("9"), D("132.30"), date(2026, 10, 23))]) == ["a", "b"]
    # Too far in days, or at another price: not part of it.
    assert sum_to(D("2.688"), D("132.30"), day, [("a", D("1.493"), D("132.30"), date(2026, 10, 30)), parts[1]]) is None
    assert sum_to(D("2.688"), D("132.30"), day, [("a", D("1.493"), D("140"), date(2026, 10, 23)), parts[1]]) is None


def _renamed(db):
    """The file calls the fund QQQ; the feed, since a ticker change, "#QQQ FUND"."""
    from datetime import date
    from decimal import Decimal as D

    from app.models.perf import CorporateAction

    db.add(CorporateAction(symbol="QQQ", effective_date=date(2026, 11, 15), action_type="RENAME", ratio=D(1),
                           new_symbol="#QQQ FUND", source="manual"))
    db.commit()


def test_a_files_rows_under_an_old_ticker_are_the_feeds_row_under_the_new_one(client, db, account):
    from datetime import date
    from decimal import Decimal as D

    from app.models.brokerage_connection import BrokerageActivity
    from app.services.connection_service import REPORT_TWIN

    _renamed(db)
    assert client.post(_base(account, db), files=_files(_two_source_report(), "report.xlsx")).status_code == 200
    before = db.query(Trade).count()
    _feed_buy(db, account, "plaid:t9", "2.688", "132.30", date(2026, 10, 22), symbol="#QQQ FUND")
    assert db.query(Trade).count() == before
    row = db.query(BrokerageActivity).filter(BrokerageActivity.source_activity_id == "plaid:t9").one()
    assert (row.outcome, row.cash_amount) == (REPORT_TWIN, D("0"))


def test_the_repair_reads_a_ticker_change_too(client, db, account):
    from datetime import date
    from decimal import Decimal as D

    from app.services.feed_twins import repair

    _renamed(db)
    assert client.post(_base(account, db), files=_files(_two_source_report(), "report.xlsx")).status_code == 200
    db.add(Trade(sleeve_id=account.default_sleeve_id, trade_date=date(2026, 10, 22), symbol="#QQQ FUND", action="BUY",
                 quantity=D("2.688"), price=D("132.30"), commission=D(0), external_id="plaid:old", security_type="MUTUAL_FUND"))
    db.commit()
    assert [(d["symbol"], d["file_rows"]) for d in repair(db)["duplicates"]] == [("#QQQ FUND", 2)]


def test_a_file_under_an_old_ticker_adds_nothing_when_the_feed_has_it_under_the_new(client, db, account):
    from datetime import date

    _renamed(db)
    _feed_buy(db, account, "plaid:t9", "2.688", "132.30", date(2026, 10, 22), symbol="#QQQ FUND")
    body = client.post(_base(account, db) + "/preview", files=_files(_two_source_report(), "report.xlsx")).json()
    assert (body["to_add_trades"], body["on_file_trades"]) == (0, 2)
