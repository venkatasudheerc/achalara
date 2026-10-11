"""Performance metrics tests (sleeve / account / client levels)"""

from tests.conftest import create_test_strategy


def _add_trade(client, sleeve_id, **overrides):
    payload = {
        "sleeve_id": sleeve_id,
        "trade_date": "2024-01-15",
        "symbol": "AAPL",
        "action": "BUY",
        "quantity": 100,
        "price": 150.00,
        "commission": 10.00,
    }
    payload.update(overrides)
    resp = client.post("/api/v1/trades/", json=payload)
    assert resp.status_code == 201
    return resp.json()


class TestSleevePerformance:
    """Sleeve-level performance endpoint."""

    def test_get_performance_basic(self, client):
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="perf@test.com", strategy_name="Perf Strategy"
        )
        _add_trade(client, sleeve_id)

        resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}"
            f"/sleeves/{sleeve_id}/performance"
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["level"] == "sleeve"
        assert data["id"] == sleeve_id
        assert data["summary"]["trades_count"] == 1
        # One point per market day from the first trade.
        assert data["timeseries"][0]["date"] == "2024-01-15"
        assert len(data["timeseries"]) > 1

    def test_get_performance_with_date_range(self, client):
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="perf2@test.com", strategy_name="Perf Strategy"
        )
        for trade_date, qty in [("2024-01-15", 100), ("2024-02-15", 50)]:
            _add_trade(
                client, sleeve_id, trade_date=trade_date, quantity=qty, commission=5.0
            )

        resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}"
            f"/sleeves/{sleeve_id}/performance"
            "?start_date=2024-01-01&end_date=2024-03-01"
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["trades_count"] == 2
        assert data["start_date"] == "2024-01-01"
        assert data["end_date"] == "2024-03-01"

    def test_performance_no_trades_is_zeroed(self, client):
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="notrades@test.com", strategy_name="Empty Strategy"
        )

        resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}"
            f"/sleeves/{sleeve_id}/performance"
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["trades_count"] == 0
        assert data["timeseries"] == []

    def test_performance_invalid_date_range(self, client):
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="datetest@test.com", strategy_name="Date Strategy"
        )
        _add_trade(client, sleeve_id, trade_date="2024-02-15")

        resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}"
            f"/sleeves/{sleeve_id}/performance"
            "?start_date=2024-03-01&end_date=2024-01-01"
        )

        assert resp.status_code == 400
        assert "start_date must be before end_date" in resp.json()["detail"]

    def test_performance_nonexistent_sleeve(self, client):
        fake = "00000000-0000-0000-0000-000000000000"
        resp = client.get(
            f"/api/v1/clients/{fake}/accounts/{fake}/sleeves/{fake}/performance"
        )
        assert resp.status_code == 404
