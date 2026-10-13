"""The advisor's system status: what it reports and what it points out."""
import json
import logging
from datetime import date, datetime, timezone

from app.config import settings
from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from app.models.client import Client
from app.models.perf import DailyValuation
from app.services import run_log
from app.services.status_service import StatusService

# A Wednesday; the last finished market day before it is Tuesday the 6th.
NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)


def _linked_account(db, synced_through=date(2026, 10, 5), connection_status="active"):
    client = Client(name="Maya Rao", email="maya-status@example.com")
    db.add(client)
    db.flush()
    account = Account(
        client_id=client.id, name="Brokerage — 12345678", account_number="12345678"
    )
    connection = BrokerageConnection(
        client_id=client.id,
        source="snaptrade",
        external_user_id="user",
        external_connection_id="conn-status",
        institution="A Brokerage",
        status=connection_status,
    )
    db.add_all([account, connection])
    db.flush()
    linked = BrokerageAccount(
        connection_id=connection.id,
        external_account_ref="ref-status",
        name="Brokerage",
        number_last4="5678",
        account_id=account.id,
        status="mapped",
        transactions_synced_through=synced_through,
        last_synced_at=datetime(2026, 10, 6, 16, 30, tzinfo=timezone.utc),
        reconciliation={"drifted": [], "skipped_rows": {"unsupported": 2}},
    )
    db.add(linked)
    db.commit()
    return account


def _observed(db, account, day):
    db.add(
        DailyValuation(
            account_id=account.id,
            as_of_date=day,
            securities_value=1000,
            total_value=1000,
            basis="observed",
        )
    )
    db.commit()


def test_status_reports_accounts_capture_and_data(db, client):
    account = _linked_account(db)
    _observed(db, account, date(2026, 10, 6))

    body = client.get("/api/v1/admin/status").json()

    assert body["database"]["ok"] is True
    assert [j["id"] for j in body["jobs"]][:4] == [
        "daily_sheets_sync",
        "brokerage_link_check",
        "daily_brokerage_sync",
        "daily_capture",
    ]
    (linked,) = body["brokerage_accounts"]
    # The full account number never appears, only its last four.
    assert (linked["name"], linked["number_last4"]) == ("Brokerage", "5678")
    assert linked["owner"] == "Maya Rao"
    assert linked["transactions_synced_through"] == "2026-10-05"
    assert linked["next_sync_allowed_at"].startswith("2026-10-07T16:30")
    assert (linked["holdings_differ"], linked["skipped_rows"]) == (0, 2)
    assert body["data"]["clients"] == 1 and body["data"]["accounts"] == 1
    assert body["backup"]["known"] is False


def test_status_points_out_what_needs_a_look(db):
    account = _linked_account(
        db, synced_through=date(2026, 9, 25), connection_status="broken"
    )
    _observed(db, account, date(2026, 10, 2))  # nothing for the 6th

    status = StatusService(db).status(now=NOW)

    assert status["capture"]["market_day"] == date(2026, 10, 6)
    assert (
        status["capture"]["missing"] == []
    )  # a broken link is not expected to capture
    # Said once for the link, not once for each account under it.
    assert (
        "The A Brokerage link stopped sharing data. "
        "Sign in to it again from the client's page."
    ) in status["attention"]
    (link,) = status["brokerage_links"]
    assert (link["institution"], link["status"], link["accounts"]) == (
        "A Brokerage",
        "broken",
        1,
    )
    assert link["client"] == "Maya Rao"
    assert "Transactions for Brokerage stop at 2026-09-25." in status["attention"]


def test_a_day_not_captured_is_pointed_out(db):
    account = _linked_account(db)
    _observed(db, account, date(2026, 10, 5))

    status = StatusService(db).status(now=NOW)

    assert status["capture"]["missing"] == ["Brokerage"]
    assert "1 of 1 accounts have no record for 2026-10-06." in status["attention"]


def test_a_job_that_logs_an_error_is_marked_failed(db):
    run_log.install()

    @run_log.tracked("daily_capture")
    def failing_job():
        logging.getLogger("app.test").error("the source did not answer")

    failing_job()
    status = StatusService(db).status(now=NOW)

    capture = next(j for j in status["jobs"] if j["id"] == "daily_capture")
    assert capture["last_ok"] is False
    assert capture["last_error"] == "the source did not answer"
    assert "Daily capture failed on its last run." in status["attention"]
    assert status["recent_log"][0]["message"] == "the source did not answer"

    @run_log.tracked("daily_capture")
    def working_job():
        return None

    working_job()
    assert "Daily capture failed on its last run." not in (
        StatusService(db).status(now=NOW)["attention"]
    )


def test_the_backup_result_is_read_from_the_servers_status_folder(
    db, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "status_dir", str(tmp_path))
    service = StatusService(db)
    assert (
        "No database backup has been reported yet."
        in service.status(now=NOW)["attention"]
    )

    report = {"at": "2026-10-07T07:15:04Z", "file": "a.dump", "size_bytes": 2048}
    (tmp_path / "backup.json").write_text(json.dumps(report))
    fresh = service.status(now=NOW)
    assert fresh["backup"]["known"] and fresh["backup"]["size_bytes"] == 2048
    assert not [line for line in fresh["attention"] if "backup" in line]

    report["at"] = "2026-10-04T07:15:04Z"
    (tmp_path / "backup.json").write_text(json.dumps(report))
    assert (
        "The last database backup was on 2026-10-04."
        in service.status(now=NOW)["attention"]
    )


def test_an_account_not_yet_added_shows_no_full_number(db):
    account = _linked_account(db, connection_status="broken")
    linked = db.query(BrokerageAccount).one()
    linked.account_id, linked.status = None, "unmapped"
    linked.name = "Brokerage Account — 12345678"
    db.delete(account)
    db.commit()

    status = StatusService(db).status(now=NOW)

    assert status["brokerage_accounts"][0]["name"] == "Brokerage Account"
    assert not [line for line in status["attention"] if "12345678" in line]


def test_a_client_user_cannot_read_the_status(anon_client):
    assert anon_client.get("/api/v1/admin/status").status_code == 401
