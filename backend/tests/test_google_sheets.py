"""Live tests for the Google Sheets sync, against a sheet you name.

Opt-in only: they make real HTTP requests, so they are marked ``live`` and
skip themselves unless ``GOOGLE_SHEETS_TEST_SHEET_ID`` names a sheet that is
readable by link. No sheet id is kept in the repository.

    export GOOGLE_SHEETS_TEST_SHEET_ID=<sheet id>
    pytest backend/tests/test_google_sheets.py -m live -v
"""
import os

import pytest

from tests.conftest import create_test_strategy
from app.services.google_sheets_sync import GoogleSheetsService

SHEET_ID = os.environ.get("GOOGLE_SHEETS_TEST_SHEET_ID", "")
SHEET_GID = os.environ.get("GOOGLE_SHEETS_TEST_SHEET_GID", "0")  # first tab

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not SHEET_ID, reason="GOOGLE_SHEETS_TEST_SHEET_ID is not set"),
]


class TestGoogleSheetsFetch:
    """Tests that verify the sheet can be fetched and parsed correctly"""

    def test_fetch_returns_rows(self):
        """Sheet should return all trade rows"""
        service = GoogleSheetsService()
        rows = service.fetch_sheet_data(SHEET_ID, SHEET_GID)

        assert len(rows) > 0

    def test_fetch_has_expected_columns(self):
        """Each row should have the required trade columns"""
        service = GoogleSheetsService()
        rows = service.fetch_sheet_data(SHEET_ID, SHEET_GID)

        required_columns = {
            "Date",
            "Symbol",
            "Action",
            "Quantity",
            "Price",
            "Commission",
        }
        assert required_columns.issubset(set(rows[0].keys()))

    def test_first_row_is_a_trade(self):
        """The first row reads as a trade: a date, a symbol and a side."""
        service = GoogleSheetsService()
        rows = service.fetch_sheet_data(SHEET_ID, SHEET_GID)

        first = rows[0]
        assert first["Date"] and first["Symbol"]
        assert first["Action"].upper() in ("BUY", "SELL")

    def test_contains_buy_and_sell_actions(self):
        """Sheet should contain both BUY and SELL trades"""
        service = GoogleSheetsService()
        rows = service.fetch_sheet_data(SHEET_ID, SHEET_GID)

        actions = {r["Action"].upper() for r in rows}
        assert "BUY" in actions
        assert "SELL" in actions


class TestSyncDailyEndpoint:
    """Tests for the sync-daily endpoint using the sheet named in the environment"""

    def test_sync_validates_sheet_data(self, client):
        """Full sync-daily round-trip: fetch sheet, validate, import trades"""
        client_id, account_id, sleeve_id = create_test_strategy(
            client,
            client_email="sheets@test.com",
            strategy_name="Thematic ETFs",
        )

        response = client.post(
            "/api/v1/admin/sync-daily",
            params={
                "client_id": client_id,
                "sleeve_id": sleeve_id,
                "sheet_id": SHEET_ID,
                "range_name": SHEET_GID,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["summary"]["total_rows"] > 0
        assert data["summary"]["imported"] > 0
        assert data["summary"]["duplicates_skipped"] == 0

    def test_sync_deduplicates_on_second_run(self, client):
        """Second sync of the same sheet should import 0 new trades"""
        client_id, account_id, sleeve_id = create_test_strategy(
            client,
            client_email="sheets_dedup@test.com",
            strategy_name="Thematic ETFs Dedup",
        )

        params = {
            "client_id": client_id,
            "sleeve_id": sleeve_id,
            "sheet_id": SHEET_ID,
            "range_name": SHEET_GID,
        }

        # First sync
        resp1 = client.post("/api/v1/admin/sync-daily", params=params)
        assert resp1.status_code == 200
        imported = resp1.json()["summary"]["imported"]
        assert imported > 0

        # Second sync — all trades already exist, none should be re-imported
        resp2 = client.post("/api/v1/admin/sync-daily", params=params)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["summary"]["imported"] == 0
        assert data2["summary"]["duplicates_skipped"] == imported

    def test_sync_invalid_sheet_id(self, client):
        """Invalid sheet ID should return 502"""
        client_id, account_id, sleeve_id = create_test_strategy(
            client,
            client_email="sheets_bad@test.com",
            strategy_name="Bad Sheet Test",
        )

        response = client.post(
            "/api/v1/admin/sync-daily",
            params={
                "client_id": client_id,
                "sleeve_id": sleeve_id,
                "sheet_id": "invalid-sheet-id-that-does-not-exist",
                "range_name": "0",
            },
        )

        assert response.status_code == 502
