"""Admin endpoint tests"""

from tests.conftest import create_test_strategy


def _make_client_and_sleeve(client, suffix=""):
    """Create a client + account + global strategy + sleeve.

    Returns ``(client_id, sleeve_id)``.
    """
    client_id, _account_id, sleeve_id = create_test_strategy(
        client,
        client_name=f"Test Fund {suffix}",
        client_email=f"import{suffix}@test.com",
        account_name="Main Account",
        strategy_name=f"Test Strategy {suffix}",
    )
    return client_id, sleeve_id


class TestAdminImport:
    """Test admin import endpoints"""

    def _get_ids(self, client, suffix=""):
        """Helper returning (client_id, sleeve_id)"""
        return _make_client_and_sleeve(client, suffix)

    def test_import_validate_mode(self, client):
        """Test CSV import in VALIDATE mode"""
        client_id, sleeve_id = self._get_ids(client, "1")

        csv_content = b"""Date,Symbol,Action,Quantity,Price,Commission,Strategy,Notes
2024-01-15,AAPL,BUY,100,150.00,10.00,Growth,Initial purchase
2024-01-20,MSFT,BUY,50,300.00,5.00,Growth,Diversification"""

        response = client.post(
            "/api/v1/admin/import-historical",
            params={
                "client_id": client_id,
                "sleeve_id": sleeve_id,
                "mode": "VALIDATE",
            },
            files={"file": ("trades.csv", csv_content)},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["mode"] == "VALIDATE"
        assert data["summary"]["total_rows"] == 2
        assert data["summary"]["valid_trades"] == 2
        assert "sync_log_id" not in data

    def test_import_with_invalid_rows(self, client):
        """Test import with invalid data"""
        client_id, sleeve_id = self._get_ids(client, "2")

        csv_content = b"""Date,Symbol,Action,Quantity,Price,Commission,Strategy,Notes
2024-01-15,AAPL,BUY,100,150.00,10.00,Growth,Valid trade
2024-01-20,MSFT,BUY,-50,300.00,5.00,Growth,Invalid: negative quantity"""

        response = client.post(
            "/api/v1/admin/import-historical",
            params={
                "client_id": client_id,
                "sleeve_id": sleeve_id,
                "mode": "VALIDATE",
            },
            files={"file": ("trades.csv", csv_content)},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["summary"]["valid_trades"] == 1
        assert data["summary"]["errors"] > 0

    def test_import_nonexistent_sleeve(self, client):
        """Test import with nonexistent sleeve"""
        client_resp = client.post(
            "/api/v1/clients/",
            json={"name": "Test Fund 3", "email": "import3@test.com"},
        )
        client_id = client_resp.json()["id"]

        csv_content = b"""Date,Symbol,Action,Quantity,Price,Commission,Strategy,Notes
2024-01-15,AAPL,BUY,100,150.00,10.00,Growth,Initial purchase"""

        response = client.post(
            "/api/v1/admin/import-historical",
            params={
                "client_id": client_id,
                "sleeve_id": "nonexistent-id",
                "mode": "VALIDATE",
            },
            files={"file": ("trades.csv", csv_content)},
        )

        assert response.status_code == 404

    def test_import_mode_persist(self, client):
        """Test import in IMPORT mode (persist to DB)"""
        client_id, sleeve_id = self._get_ids(client, "4")

        csv_content = b"""Date,Symbol,Action,Quantity,Price,Commission,Strategy,Notes
2024-01-15,AAPL,BUY,100,150.00,10.00,Growth,Initial purchase
2024-01-20,MSFT,BUY,50,300.00,5.00,Growth,Diversification"""

        validate_resp = client.post(
            "/api/v1/admin/import-historical",
            params={
                "client_id": client_id,
                "sleeve_id": sleeve_id,
                "mode": "VALIDATE",
            },
            files={"file": ("trades.csv", csv_content)},
        )
        assert validate_resp.status_code == 200

        response = client.post(
            "/api/v1/admin/import-historical",
            params={
                "client_id": client_id,
                "sleeve_id": sleeve_id,
                "mode": "IMPORT",
            },
            files={"file": ("trades.csv", csv_content)},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["mode"] == "IMPORT"
        assert data["summary"]["valid_trades"] == 2
        assert data["sync_log_id"] is not None

    def test_import_deduplication(self, client):
        """Test that duplicate trades are detected"""
        client_id, sleeve_id = self._get_ids(client, "5")

        csv_content = b"""Date,Symbol,Action,Quantity,Price,Commission,Strategy,Notes
2024-01-15,AAPL,BUY,100,150.00,10.00,Growth,Trade 1"""

        response1 = client.post(
            "/api/v1/admin/import-historical",
            params={
                "client_id": client_id,
                "sleeve_id": sleeve_id,
                "mode": "IMPORT",
            },
            files={"file": ("trades.csv", csv_content)},
        )
        assert response1.status_code == 200
        assert response1.json()["summary"]["valid_trades"] == 1

        response2 = client.post(
            "/api/v1/admin/import-historical",
            params={
                "client_id": client_id,
                "sleeve_id": sleeve_id,
                "mode": "IMPORT",
            },
            files={"file": ("trades.csv", csv_content)},
        )
        assert response2.status_code == 200
        assert response2.json()["summary"]["duplicates_found"] == 1
        assert response2.json()["summary"]["valid_trades"] == 0

    def test_invalid_mode(self, client):
        """Test with invalid mode parameter"""
        client_id, sleeve_id = self._get_ids(client, "6")

        csv_content = b"""Date,Symbol,Action,Quantity,Price,Commission,Strategy,Notes
2024-01-15,AAPL,BUY,100,150.00,10.00,Growth,Trade"""

        response = client.post(
            "/api/v1/admin/import-historical",
            params={
                "client_id": client_id,
                "sleeve_id": sleeve_id,
                "mode": "INVALID_MODE",
            },
            files={"file": ("trades.csv", csv_content)},
        )

        assert response.status_code == 400

    def test_import_persists_open_and_closed_positions(self, client, db):
        """After IMPORT, positions endpoints reflect persisted open + closed rows."""
        client_id, account_id, sleeve_id = create_test_strategy(
            client,
            client_name="Persist Fund",
            client_email="persistpos@test.com",
            account_name="Main Account",
            strategy_name="Persist Strategy",
        )

        # FCG is fully sold out (closed); AAPL stays open.
        csv_content = (
            b"Date,Symbol,Action,Quantity,Price,Commission,Strategy,Notes\n"
            b"2024-01-01,FCG,BUY,100,100.00,0,Persist Strategy,open\n"
            b"2024-06-01,FCG,SELL,100,120.00,0,Persist Strategy,close\n"
            b"2024-01-02,AAPL,BUY,10,150.00,0,Persist Strategy,open"
        )

        resp = client.post(
            "/api/v1/admin/import-historical",
            params={"client_id": client_id, "sleeve_id": sleeve_id, "mode": "IMPORT"},
            files={"file": ("trades.csv", csv_content)},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        # Open positions: only AAPL
        open_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
        )
        assert open_resp.status_code == 200
        open_data = open_resp.json()
        assert {p["symbol"] for p in open_data["positions"]} == {"AAPL"}

        # Closed positions: FCG with realized gain (120-100)*100 = 2000
        closed_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions/closed"
        )
        assert closed_resp.status_code == 200
        closed_data = closed_resp.json()
        assert len(closed_data["positions"]) == 1
        assert closed_data["positions"][0]["symbol"] == "FCG"
        assert closed_data["positions"][0]["realized_gain"] == 2000.0
        assert closed_data["total_realized_gain"] == 2000.0

        # The persisted positions table has both an OPEN and a CLOSED row
        from app.models.position import Position

        rows = db.query(Position).filter(Position.sleeve_id == sleeve_id).all()
        by_status = {(r.symbol, r.status) for r in rows}
        assert ("AAPL", "OPEN") in by_status
        assert ("FCG", "CLOSED") in by_status


class TestSyncLogs:
    """Tests for sync-logs total correctness and import_type tracking."""

    def _import_csv(self, client, client_id, sleeve_id, csv_content):
        return client.post(
            "/api/v1/admin/import-historical",
            params={
                "client_id": client_id,
                "sleeve_id": sleeve_id,
                "mode": "IMPORT",
            },
            files={"file": ("trades.csv", csv_content)},
        )

    def test_sync_logs_total_is_real_count_not_page_size(self, client):
        """total must equal the real number of SyncLog rows, not len(page)."""
        client_id, sleeve_id = _make_client_and_sleeve(client, "sl")

        # Create 3 imports to produce 3 SyncLog rows
        header = "Date,Symbol,Action,Quantity,Price,Commission,Strategy,Notes"
        for i, symbol in enumerate(["AAPL", "MSFT", "TSLA"]):
            row = f"2024-0{i + 1}-01,{symbol},BUY,1,100,0,S,"
            self._import_csv(
                client,
                client_id,
                sleeve_id,
                f"{header}\n{row}\n".encode(),
            )

        # Fetch with limit=1 so page has 1 item but total should be 3
        resp = client.get(
            f"/api/v1/admin/sync-logs?client_id={client_id}&skip=0&limit=1"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 3  # real count, not len(page)
        assert len(data["logs"]) == 1  # page limited to 1

    def test_sync_log_import_type_historical(self, client):
        """CSV import via import-historical records import_type=HISTORICAL."""
        client_id, sleeve_id = _make_client_and_sleeve(client, "it")

        csv_content = b"Date,Symbol,Action,Quantity,Price,Commission,Strategy,Notes\n2024-01-01,AAPL,BUY,1,100,0,S,\n"
        import_resp = self._import_csv(client, client_id, sleeve_id, csv_content)
        sync_log_id = import_resp.json()["sync_log_id"]

        logs_resp = client.get(f"/api/v1/admin/sync-logs?client_id={client_id}")
        logs = {log["id"]: log for log in logs_resp.json()["logs"]}
        assert logs[sync_log_id]["import_type"] == "HISTORICAL"


class TestAutoRouteImport:
    """Auto-routing import: no sleeve_id, route by Account + Strategy columns."""

    # Columns mirror the historical sheet format (note YYYY/MM/DD + Buy/Sell case)
    CSV = (
        b"Date,Symbol,Action,Quantity,Price,Commission,Strategy,Account,Notes\n"
        b"2025/03/17,ABC,Buy,40,25.00,0,Thematic ETFs,10000001,\n"
        b"2025/03/17,DEF,Buy,15,60.00,0,Thematic ETFs,10000001,\n"
        b"2025/04/04,ABC,Sell,40,21.00,0,Thematic ETFs,10000001,\n"
        b"2026/01/05,AAPL,Buy,10,150.00,0,Core Equity,99999999,\n"
    )

    def _client(self, client, email):
        resp = client.post(
            "/api/v1/clients/", json={"name": "Route Fund", "email": email}
        )
        return resp.json()["id"]

    def test_validate_reports_what_would_be_created(self, client):
        client_id = self._client(client, "route1@test.com")
        resp = client.post(
            "/api/v1/admin/import-historical",
            params={"client_id": client_id, "mode": "VALIDATE"},
            files={"file": ("hist.csv", self.CSV)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["routing"] == "auto-route"
        # 2 distinct accounts (10000001, 99999999), 2 distinct strategies
        assert data["summary"]["accounts_created"] == 2
        assert data["summary"]["strategies_created"] == 2
        assert data["summary"]["sleeves_created"] == 2
        assert data["summary"]["valid_trades"] == 4
        # VALIDATE must not write anything
        assert "sync_log_id" not in data

    def test_import_creates_accounts_strategies_and_routes_trades(self, client):
        client_id = self._client(client, "route2@test.com")
        resp = client.post(
            "/api/v1/admin/import-historical",
            params={"client_id": client_id, "mode": "IMPORT"},
            files={"file": ("hist.csv", self.CSV)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["accounts_created"] == 2
        assert data["summary"]["strategies_created"] == 2
        assert data["summary"]["sleeves_created"] == 2
        assert data["summary"]["valid_trades"] == 4

        # The "10000001" account + "Thematic ETFs" sleeve now exist with 3 trades
        accounts = client.get(f"/api/v1/clients/{client_id}/accounts").json()
        by_number = {a["account_number"]: a for a in accounts}
        assert "10000001" in by_number and "99999999" in by_number

        acct = by_number["10000001"]
        sleeves = client.get(
            f"/api/v1/clients/{client_id}/accounts/{acct['id']}/sleeves"
        ).json()
        thematic = next(s for s in sleeves if s["strategy_name"] == "Thematic ETFs")
        trades = client.get(
            f"/api/v1/clients/{client_id}/accounts/{acct['id']}"
            f"/sleeves/{thematic['id']}/trades"
        ).json()
        assert trades["total"] == 3

    def test_strategy_name_routing_is_case_insensitive(self, client):
        """Rows naming the same strategy in different casing route to ONE sleeve."""
        client_id = self._client(client, "route_ci@test.com")
        csv = (
            b"Date,Symbol,Action,Quantity,Price,Commission,Strategy,Account,Notes\n"
            b"2025/03/17,ABC,Buy,10,25.00,0,Thematic ETFs,10000001,\n"
            b"2025/03/18,DEF,Buy,5,60.00,0,thematic etfs,10000001,\n"
        )
        resp = client.post(
            "/api/v1/admin/import-historical",
            params={"client_id": client_id, "mode": "IMPORT"},
            files={"file": ("hist.csv", csv)},
        )
        assert resp.status_code == 200
        data = resp.json()
        # One account, one strategy definition, one sleeve — despite the case diff
        assert data["summary"]["accounts_created"] == 1
        assert data["summary"]["strategies_created"] == 1
        assert data["summary"]["sleeves_created"] == 1
        assert data["summary"]["valid_trades"] == 2

        strategies = client.get("/api/v1/strategies/").json()
        thematic = [s for s in strategies if s["name"].lower() == "thematic etfs"]
        assert len(thematic) == 1

    def test_reimport_is_deduplicated(self, client):
        client_id = self._client(client, "route3@test.com")
        params = {"client_id": client_id, "mode": "IMPORT"}
        first = client.post(
            "/api/v1/admin/import-historical",
            params=params,
            files={"file": ("hist.csv", self.CSV)},
        ).json()
        assert first["summary"]["valid_trades"] == 4

        # Second run: same file → all duplicates, nothing imported, no new entities
        second = client.post(
            "/api/v1/admin/import-historical",
            params=params,
            files={"file": ("hist.csv", self.CSV)},
        ).json()
        assert second["summary"]["valid_trades"] == 0
        assert second["summary"]["duplicates_found"] == 4
        assert second["summary"]["accounts_created"] == 0
        assert second["summary"]["strategies_created"] == 0
        assert second["summary"]["sleeves_created"] == 0
