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


def test_when_even_the_first_record_differs_the_download_starts_weeks_before(db, account):
    from datetime import date
    from decimal import Decimal as D

    from app.models.perf import DailyHolding
    from app.services.account_import_service import AccountImportService

    acct = db.get(Account, account.account_id)
    db.add(DailyHolding(account_id=acct.id, as_of_date=date(2026, 10, 9), symbol="AAA",
                        quantity=D(4), price=D(50), market_value=D(200)))
    db.commit()
    check = AccountImportService(db).holdings_check(acct)
    assert check["last_agreed"] is None and check["first_differed"] == date(2026, 10, 9)
    assert check["download_from"] == date(2026, 9, 11)


def test_the_check_can_be_asked_for_before_any_upload(client, db, account):
    acct = db.get(Account, account.account_id)
    advisor = client.get(f"{_base(account, db)}/check")
    assert advisor.status_code == 200 and advisor.json() is None  # nothing recorded yet
    _as_client(acct.client_id)
    own = client.get(f"/api/v1/portal/accounts/{acct.id}/imports/check")
    assert own.status_code == 200
