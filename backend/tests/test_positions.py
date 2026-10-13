"""Position calculation tests"""

import pytest
from unittest.mock import patch
from tests.conftest import create_test_strategy


class TestPositionCalculation:
    """Test position calculation and portfolio value"""

    def test_calculate_positions_single_buy(self, client):
        """Single BUY creates one open position"""
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="pos@test.com", strategy_name="Test Strategy"
        )

        trade_resp = client.post(
            "/api/v1/trades/",
            json={
                "sleeve_id": sleeve_id,
                "trade_date": "2024-01-15",
                "symbol": "AAPL",
                "action": "BUY",
                "quantity": 100,
                "price": 150.00,
                "commission": 10.00,
                "notes": "Initial purchase",
            },
        )
        assert trade_resp.status_code == 201

        pos_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
        )

        assert pos_resp.status_code == 200
        data = pos_resp.json()

        assert "summary" in data
        assert "positions" in data

        summary = data["summary"]
        assert summary["positions_count"] == 1
        assert summary["total_cost_basis"] == 15010.0  # 100 * 150 + 10

        positions = data["positions"]
        assert len(positions) == 1
        assert positions[0]["symbol"] == "AAPL"
        assert positions[0]["quantity"] == 100.0
        assert positions[0]["cost_basis"] == 15010.0
        assert positions[0]["status"] == "OPEN"

    def test_sell_without_matching_quantity_is_unmatched(self, client):
        """A SELL whose quantity matches no BUY leaves the BUY fully open."""
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="pos2@test.com", strategy_name="Test Strategy"
        )

        client.post(
            "/api/v1/trades/",
            json={
                "sleeve_id": sleeve_id,
                "trade_date": "2024-01-15",
                "symbol": "MSFT",
                "action": "BUY",
                "quantity": 50,
                "price": 300.00,
                "commission": 5.00,
            },
        )

        # SELL qty 25 — no BUY of qty 25 exists, so it does not match.
        client.post(
            "/api/v1/trades/",
            json={
                "sleeve_id": sleeve_id,
                "trade_date": "2024-02-20",
                "symbol": "MSFT",
                "action": "SELL",
                "quantity": 25,
                "price": 310.00,
                "commission": 5.00,
            },
        )

        pos_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
        )

        assert pos_resp.status_code == 200
        data = pos_resp.json()

        # The BUY 50 stays fully open; the qty-25 sell is ignored.
        positions = data["positions"]
        assert len(positions) == 1
        assert positions[0]["symbol"] == "MSFT"
        assert positions[0]["quantity"] == 50.0
        assert positions[0]["status"] == "OPEN"

        closed_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions/closed"
        )
        assert closed_resp.status_code == 200
        assert closed_resp.json()["positions"] == []

    def test_full_sell_creates_closed_position(self, client):
        """Fully selling a position moves it to closed with realized gain"""
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="closed@test.com", strategy_name="Closed Strategy"
        )

        # BUY 100 @ $100 + $0 commission → cost basis $10000
        client.post(
            "/api/v1/trades/",
            json={
                "sleeve_id": sleeve_id,
                "trade_date": "2024-01-01",
                "symbol": "FCG",
                "action": "BUY",
                "quantity": 100,
                "price": 100.00,
                "commission": 0,
            },
        )

        # SELL 100 @ $120 + $0 commission → proceeds $12000, gain = $2000
        client.post(
            "/api/v1/trades/",
            json={
                "sleeve_id": sleeve_id,
                "trade_date": "2024-06-01",
                "symbol": "FCG",
                "action": "SELL",
                "quantity": 100,
                "price": 120.00,
                "commission": 0,
            },
        )

        # Open positions should be empty
        pos_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
        )
        assert pos_resp.status_code == 200
        assert pos_resp.json()["positions"] == []
        assert pos_resp.json()["summary"]["positions_count"] == 0

        # Closed positions should have FCG with $2000 realized gain
        closed_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions/closed"
        )
        assert closed_resp.status_code == 200
        closed_data = closed_resp.json()
        assert len(closed_data["positions"]) == 1
        pos = closed_data["positions"][0]
        assert pos["symbol"] == "FCG"
        assert pos["status"] == "CLOSED"
        assert pos["realized_gain"] == 2000.0
        assert pos["realized_gain_pct"] == pytest.approx(20.0, rel=1e-4)
        assert closed_data["total_realized_gain"] == 2000.0

    def test_reopen_position_after_full_close(self, client):
        """Buying a symbol again after fully selling it creates a fresh open position"""
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="reopen@test.com", strategy_name="Reopen Strategy"
        )

        # First lot: BUY then fully SELL
        client.post("/api/v1/trades/", json={
            "sleeve_id": sleeve_id, "trade_date": "2024-01-01",
            "symbol": "TSLA", "action": "BUY", "quantity": 10, "price": 200.0, "commission": 0,
        })
        client.post("/api/v1/trades/", json={
            "sleeve_id": sleeve_id, "trade_date": "2024-03-01",
            "symbol": "TSLA", "action": "SELL", "quantity": 10, "price": 250.0, "commission": 0,
        })

        # Re-enter: BUY again
        client.post("/api/v1/trades/", json={
            "sleeve_id": sleeve_id, "trade_date": "2024-06-01",
            "symbol": "TSLA", "action": "BUY", "quantity": 5, "price": 300.0, "commission": 0,
        })

        pos_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
        )
        assert pos_resp.status_code == 200
        positions = pos_resp.json()["positions"]
        assert len(positions) == 1
        assert positions[0]["symbol"] == "TSLA"
        assert positions[0]["quantity"] == 5.0
        # Cost basis for the new lot only: 5 * 300 = 1500
        assert positions[0]["cost_basis"] == 1500.0

        # Closed endpoint should still show TSLA as closed (the first round trip)
        closed_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions/closed"
        )
        assert closed_resp.status_code == 200
        closed = closed_resp.json()["positions"]
        assert len(closed) == 1
        assert closed[0]["symbol"] == "TSLA"
        # Realized gain: (250 - 200) * 10 = 500
        assert closed[0]["realized_gain"] == 500.0

    def test_repeated_same_quantity_round_trips_pair_chronologically(self, client):
        """Two BUY/SELL pairs of the same symbol+qty form two distinct round-trips,
        each matched oldest-buy to oldest-sell (the sheet pattern)."""
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="qmatch@test.com", strategy_name="QMatch Strategy"
        )

        # Round-trip A: buy 40 @ 25.00, later sell 40 @ 21.00  (loss)
        client.post("/api/v1/trades/", json={
            "sleeve_id": sleeve_id, "trade_date": "2025-03-17",
            "symbol": "ABC", "action": "BUY", "quantity": 40, "price": 25.00, "commission": 0,
        })
        client.post("/api/v1/trades/", json={
            "sleeve_id": sleeve_id, "trade_date": "2025-04-04",
            "symbol": "ABC", "action": "SELL", "quantity": 40, "price": 21.00, "commission": 0,
        })
        # Round-trip B: buy 40 @ 25.50, later sell 40 @ 24.50  (loss)
        client.post("/api/v1/trades/", json={
            "sleeve_id": sleeve_id, "trade_date": "2025-12-01",
            "symbol": "ABC", "action": "BUY", "quantity": 40, "price": 25.50, "commission": 0,
        })
        client.post("/api/v1/trades/", json={
            "sleeve_id": sleeve_id, "trade_date": "2025-12-15",
            "symbol": "ABC", "action": "SELL", "quantity": 40, "price": 24.50, "commission": 0,
        })

        # No open position — both round-trips fully closed
        pos_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
        )
        assert pos_resp.json()["positions"] == []

        closed_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions/closed"
        )
        closed = closed_resp.json()["positions"]
        assert len(closed) == 2

        # Sorted by close date; each pairs with the correct entry price
        closed.sort(key=lambda p: p["closed_at"])
        a, b = closed
        assert a["entry_price"] == pytest.approx(25.00)
        assert a["exit_price"] == pytest.approx(21.00)
        assert a["realized_gain"] == pytest.approx((21.00 - 25.00) * 40)
        assert b["entry_price"] == pytest.approx(25.50)
        assert b["exit_price"] == pytest.approx(24.50)
        assert b["realized_gain"] == pytest.approx((24.50 - 25.50) * 40)

    def test_calculate_positions_multiple_symbols(self, client):
        """Portfolio with multiple holdings"""
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="multi@test.com", strategy_name="Multi Strategy"
        )

        for symbol in ["AAPL", "MSFT", "TSLA"]:
            client.post(
                "/api/v1/trades/",
                json={
                    "sleeve_id": sleeve_id,
                    "trade_date": "2024-01-15",
                    "symbol": symbol,
                    "action": "BUY",
                    "quantity": 100,
                    "price": 100.00,
                    "commission": 10.00,
                },
            )

        pos_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
        )

        assert pos_resp.status_code == 200
        data = pos_resp.json()

        assert data["summary"]["positions_count"] == 3
        assert len(data["positions"]) == 3
        assert {p["symbol"] for p in data["positions"]} == {"AAPL", "MSFT", "TSLA"}

    def test_positions_with_market_prices(self, client):
        """Open positions reflect persisted market prices"""
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="price@test.com", strategy_name="Price Strategy"
        )

        client.post(
            "/api/v1/trades/",
            json={
                "sleeve_id": sleeve_id,
                "trade_date": "2024-01-15",
                "symbol": "AAPL",
                "action": "BUY",
                "quantity": 100,
                "price": 150.00,
                "commission": 10.00,
            },
        )

        price_resp = client.post(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/market-prices",
            json={"prices": {"AAPL": 180.00}},
        )
        assert price_resp.status_code == 200

        with patch(
            "app.services.webull_market_data.WebullMarketDataService.get_current_price",
            return_value=180.0,
        ):
            pos_resp = client.get(
                f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
            )

        assert pos_resp.status_code == 200
        data = pos_resp.json()

        pos = data["positions"][0]
        assert pos["current_price"] == 180.0
        assert pos["market_value"] == 18000.0  # 100 * 180
        assert pos["unrealized_gain"] == 2990.0  # 18000 - 15010
        assert pos["unrealized_gain_pct"] > 0

    def test_positions_portfolio_summary(self, client):
        """Portfolio summary calculations"""
        client_id, account_id, sleeve_id = create_test_strategy(
            client, client_email="summary@test.com", strategy_name="Summary Strategy"
        )

        for qty, symbol in [(100, "AAPL"), (50, "MSFT")]:
            client.post(
                "/api/v1/trades/",
                json={
                    "sleeve_id": sleeve_id,
                    "trade_date": "2024-01-15",
                    "symbol": symbol,
                    "action": "BUY",
                    "quantity": qty,
                    "price": 100.00,
                    "commission": 10.00,
                },
            )

        client.post(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/market-prices",
            json={"prices": {"AAPL": 120.00, "MSFT": 110.00}},
        )

        prices_map = {"AAPL": 120.0, "MSFT": 110.0}
        with patch(
            "app.services.webull_market_data.WebullMarketDataService.get_current_price",
            side_effect=lambda sym: prices_map.get(sym),
        ):
            pos_resp = client.get(
                f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
            )

        assert pos_resp.status_code == 200
        summary = pos_resp.json()["summary"]
        # Cost: (100*100+10) + (50*100+10) = 10010 + 5010 = 15020
        assert summary["total_cost_basis"] == 15020.0
        # Market: 100*120 + 50*110 = 12000 + 5500 = 17500
        assert summary["total_market_value"] == 17500.0
        # Gain: 17500 - 15020 = 2480
        assert summary["total_unrealized_gain"] == 2480.0
        assert summary["total_realized_gain"] == 0.0
        assert summary["closed_positions_count"] == 0
