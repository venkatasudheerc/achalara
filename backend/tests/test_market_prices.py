"""Tests for market price endpoints — Webull is mocked, no live API calls."""
import pytest
from unittest.mock import patch
from tests.conftest import create_test_strategy
from app.services.webull_market_data import WebullMarketDataService


class TestSymbolNormalization:
    """Google Finance 'EXCHANGE:TICKER' must be stripped before hitting Webull."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("BATS:IGE", "IGE"),
            ("NASDAQ:AAPL", "AAPL"),
            ("NYSEARCA:GDX", "GDX"),
            ("AAPL", "AAPL"),
            ("nyse:gdx", "GDX"),
            (" spy ", "SPY"),
            ("XYZ B", "XYZ B"),
            ("XYZ.B", "XYZ B"),
            ("XYZ-B", "XYZ B"),
            ("XYZ/B", "XYZ B"),
            ("NYSE:XYZ.B", "XYZ B"),
        ],
    )
    def test_normalize_symbol(self, raw, expected):
        assert WebullMarketDataService._normalize_symbol(raw) == expected

    def test_snapshot_request_uses_bare_ticker(self):
        """get_current_price('BATS:IGE') must send symbols=IGE to Webull."""
        svc = WebullMarketDataService()
        captured = {}

        class _FakeResp:
            def read(self):
                return b'[{"price": 55.83}]'

        class _FakeConn:
            def __init__(self, *args, **kwargs):
                pass

            def request(self, method, path, body, headers):
                captured["path"] = path

            def getresponse(self):
                return _FakeResp()

        with patch(
            "app.services.webull_market_data.http.client.HTTPSConnection",
            _FakeConn,
        ):
            price = svc.get_current_price("BATS:IGE")

        assert "symbols=IGE" in captured["path"]
        assert "BATS" not in captured["path"]
        assert price == 55.83


def _add_trade(
    client, sleeve_id, symbol="AAPL", action="BUY", quantity=10, price=150.0
):
    resp = client.post(
        "/api/v1/trades/",
        json={
            "sleeve_id": sleeve_id,
            "trade_date": "2024-01-15",
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "commission": 0.0,
        },
    )
    assert resp.status_code == 201
    return resp.json()


def test_manual_update_market_prices_persists_to_db(client):
    client_id, account_id, sleeve_id = create_test_strategy(
        client, client_email="mp1@example.com"
    )
    _add_trade(client, sleeve_id, symbol="AAPL", price=150.0)

    resp = client.post(
        f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/market-prices",
        json={"prices": {"AAPL": 200.0}},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1

    # Positions should now reflect 200.0; mock Webull so live fetch doesn't override it.
    with patch(
        "app.services.webull_market_data.WebullMarketDataService.get_current_price",
        return_value=200.0,
    ):
        pos_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
        )
    assert pos_resp.status_code == 200
    positions = pos_resp.json()["positions"]
    aapl = next(p for p in positions if p["symbol"] == "AAPL")
    assert aapl["current_price"] == pytest.approx(200.0, rel=1e-3)
    assert aapl["market_value"] == pytest.approx(2000.0, rel=1e-3)


def test_fetch_market_prices_from_webull_persists_to_db(client):
    client_id, account_id, sleeve_id = create_test_strategy(
        client, client_email="mp2@example.com"
    )
    _add_trade(client, sleeve_id, symbol="MSFT", price=300.0)

    with patch(
        "app.services.webull_market_data.WebullMarketDataService.get_current_price",
        return_value=380.0,
    ):
        resp = client.post(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/fetch-market-prices"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "MSFT" in data["symbols"]

        pos_resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
        )
    positions = pos_resp.json()["positions"]
    msft = next(p for p in positions if p["symbol"] == "MSFT")
    assert msft["current_price"] == pytest.approx(380.0, rel=1e-3)
    assert msft["market_value"] == pytest.approx(3800.0, rel=1e-3)


def test_fetch_market_prices_no_trades(client):
    client_id, account_id, sleeve_id = create_test_strategy(
        client, client_email="mp3@example.com"
    )
    resp = client.post(
        f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/fetch-market-prices"
    )
    assert resp.status_code == 400


def test_positions_fall_back_to_cost_basis_when_no_prices(client):
    client_id, account_id, sleeve_id = create_test_strategy(
        client, client_email="mp4@example.com"
    )
    _add_trade(client, sleeve_id, symbol="NVDA", price=500.0, quantity=5)

    # Mock Webull returning None so the endpoint falls back to cost basis.
    with patch(
        "app.services.webull_market_data.WebullMarketDataService.get_current_price",
        return_value=None,
    ):
        resp = client.get(
            f"/api/v1/clients/{client_id}/accounts/{account_id}/sleeves/{sleeve_id}/positions"
        )
    assert resp.status_code == 200
    positions = resp.json()["positions"]
    nvda = next(p for p in positions if p["symbol"] == "NVDA")
    # No price fetched → current_price is None, market_value falls back to cost basis
    assert nvda["current_price"] is None
    assert nvda["market_value"] == pytest.approx(nvda["cost_basis"], rel=1e-3)
