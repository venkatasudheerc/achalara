"""Tests for daily sync service and SheetSyncConfig CRUD."""

from unittest.mock import patch
from tests.conftest import create_test_strategy
from app.services.daily_sync import run_daily_sync, run_all_enabled_syncs
from app.models.sheet_sync_config import SheetSyncConfig
from app.models.sync_log import SyncLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_ROWS = [
    {
        "Date": "2024-03-01",
        "Symbol": "TSLA",
        "Action": "BUY",
        "Quantity": "5",
        "Price": "200.00",
        "Commission": "0",
        "Strategy": "Test",
        "Notes": "",
    }
]


def _make_sleeve(client):
    return create_test_strategy(client, client_email="sched@example.com")


# ---------------------------------------------------------------------------
# run_daily_sync unit tests (service-layer, mocking Sheets)
# ---------------------------------------------------------------------------


def test_run_daily_sync_imports_new_trades(client, db):
    _client_id, _account_id, sleeve_id = _make_sleeve(client)

    with patch(
        "app.services.google_sheets_sync.GoogleSheetsService.fetch_sheet_data",
        return_value=_SAMPLE_ROWS,
    ):
        result = run_daily_sync(
            db=db,
            sleeve_id=sleeve_id,
            sheet_id="fake-sheet-id",
        )

    assert result["success"] is True
    assert result["imported"] == 1
    assert result["duplicates"] == 0

    log = db.query(SyncLog).filter(SyncLog.id == result["sync_log_id"]).first()
    assert log is not None
    assert log.import_type == "DAILY"
    assert log.status == "SUCCESS"


def test_run_daily_sync_deduplicates(client, db):
    _client_id, _account_id, sleeve_id = _make_sleeve(client)

    with patch(
        "app.services.google_sheets_sync.GoogleSheetsService.fetch_sheet_data",
        return_value=_SAMPLE_ROWS,
    ):
        run_daily_sync(db=db, sleeve_id=sleeve_id, sheet_id="fake")
        result = run_daily_sync(db=db, sleeve_id=sleeve_id, sheet_id="fake")

    assert result["imported"] == 0
    assert result["duplicates"] == 1


def test_run_daily_sync_empty_sheet_returns_zero(client, db):
    _client_id, _account_id, sleeve_id = _make_sleeve(client)

    with patch(
        "app.services.google_sheets_sync.GoogleSheetsService.fetch_sheet_data",
        return_value=[],
    ):
        result = run_daily_sync(db=db, sleeve_id=sleeve_id, sheet_id="fake")

    assert result["success"] is True
    assert result["imported"] == 0
    assert result["sync_log_id"] is None


def test_run_all_enabled_syncs_updates_last_synced_at(client, db):
    _client_id, _account_id, sleeve_id = _make_sleeve(client)

    cfg = SheetSyncConfig(
        sleeve_id=sleeve_id,
        sheet_id="fake-sheet",
        range_name="Sheet1",
        enabled=True,
    )
    db.add(cfg)
    db.commit()

    with patch(
        "app.services.google_sheets_sync.GoogleSheetsService.fetch_sheet_data",
        return_value=_SAMPLE_ROWS,
    ):
        run_all_enabled_syncs(db)

    db.refresh(cfg)
    assert cfg.last_synced_at is not None


# ---------------------------------------------------------------------------
# SheetSyncConfig CRUD endpoint tests
# ---------------------------------------------------------------------------


def test_create_sync_config(client):
    _client_id, _account_id, sleeve_id = create_test_strategy(
        client, client_email="cfg1@example.com"
    )
    resp = client.post(
        "/api/v1/admin/sync-configs",
        json={
            "sleeve_id": sleeve_id,
            "sheet_id": "abc123",
            "range_name": "Sheet1",
            "enabled": True,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["sheet_id"] == "abc123"
    assert data["enabled"] is True


def test_list_sync_configs(client):
    client_id, _account_id, sleeve_id = create_test_strategy(
        client, client_email="cfg2@example.com"
    )
    client.post(
        "/api/v1/admin/sync-configs",
        json={"sleeve_id": sleeve_id, "sheet_id": "s1"},
    )
    resp = client.get(f"/api/v1/admin/sync-configs?client_id={client_id}")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_update_sync_config_toggle(client):
    _client_id, _account_id, sleeve_id = create_test_strategy(
        client, client_email="cfg3@example.com"
    )
    create_resp = client.post(
        "/api/v1/admin/sync-configs",
        json={"sleeve_id": sleeve_id, "sheet_id": "s2"},
    )
    config_id = create_resp.json()["id"]

    patch_resp = client.patch(
        f"/api/v1/admin/sync-configs/{config_id}",
        json={"enabled": False},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["enabled"] is False


def test_delete_sync_config(client):
    client_id, _account_id, sleeve_id = create_test_strategy(
        client, client_email="cfg4@example.com"
    )
    create_resp = client.post(
        "/api/v1/admin/sync-configs",
        json={"sleeve_id": sleeve_id, "sheet_id": "s3"},
    )
    config_id = create_resp.json()["id"]

    del_resp = client.delete(f"/api/v1/admin/sync-configs/{config_id}")
    assert del_resp.status_code == 204

    list_resp = client.get(f"/api/v1/admin/sync-configs?client_id={client_id}")
    ids = [c["id"] for c in list_resp.json()]
    assert config_id not in ids
