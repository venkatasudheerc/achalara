"""Tests for benchmark endpoints"""
from unittest.mock import patch


class TestBenchmarkEndpoints:
    def test_benchmark_no_webull_keys(self, client, monkeypatch):
        """Returns 200 with empty timeseries and a warning when Webull keys are absent"""
        from app.config import settings

        monkeypatch.setattr(settings, "webull_app_key", "")
        monkeypatch.setattr(settings, "webull_app_secret", "")

        response = client.get("/api/v1/benchmarks/SPY/performance")
        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "SPY"
        assert data["timeseries"] == []
        assert data["warning"] is not None
        assert (
            "not configured" in data["warning"].lower()
            or "unavailable" in data["warning"].lower()
        )

    def test_benchmark_invalid_ticker(self, client):
        """Returns 422 for tickers with invalid characters"""
        response = client.get("/api/v1/benchmarks/S P Y/performance")
        assert response.status_code in (404, 422)

    def test_benchmark_invalid_ticker_special_chars(self, client):
        """Returns 422 for tickers containing injection-risk characters"""
        response = client.get("/api/v1/benchmarks/SPY%3BHACK/performance")
        assert response.status_code in (404, 422)

    def test_benchmark_ticker_all_punctuation_rejected(self, client):
        """Tickers that are only punctuation (e.g. '...', '---') are rejected"""
        for bad in ("...", "---", ".-^"):
            response = client.get(f"/api/v1/benchmarks/{bad}/performance")
            assert response.status_code in (404, 422), bad

    def test_benchmark_start_after_end_rejected(self, client, monkeypatch):
        """start_date later than end_date returns 422"""
        from app.config import settings

        monkeypatch.setattr(settings, "webull_app_key", "test-key")
        monkeypatch.setattr(settings, "webull_app_secret", "test-secret")

        response = client.get(
            "/api/v1/benchmarks/SPY/performance",
            params={"start_date": "2024-12-31", "end_date": "2024-01-01"},
        )
        assert response.status_code == 422

    def test_benchmark_date_filter(self, client, monkeypatch):
        """Only returns bars within the requested date range"""
        from app.config import settings

        monkeypatch.setattr(settings, "webull_app_key", "test-key")
        monkeypatch.setattr(settings, "webull_app_secret", "test-secret")

        mock_bars = [
            {"date": "2024-03-01", "close": "510.00"},
            {"date": "2024-02-01", "close": "500.00"},
            {"date": "2024-01-01", "close": "490.00"},
            {"date": "2023-12-01", "close": "480.00"},
        ]

        with patch(
            "app.services.webull_market_data.WebullMarketDataService.get_historical_bars",
            return_value=mock_bars,
        ):
            response = client.get(
                "/api/v1/benchmarks/SPY/performance",
                params={"start_date": "2024-01-01", "end_date": "2024-02-28"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["ticker"] == "SPY"
        dates = [pt["date"] for pt in data["timeseries"]]
        assert "2023-12-01" not in dates
        assert "2024-03-01" not in dates
        assert "2024-01-01" in dates
        assert "2024-02-01" in dates

    def test_benchmark_returns_sorted_ascending(self, client, monkeypatch):
        """Timeseries is returned in ascending date order regardless of API order"""
        from app.config import settings

        monkeypatch.setattr(settings, "webull_app_key", "test-key")
        monkeypatch.setattr(settings, "webull_app_secret", "test-secret")

        mock_bars = [
            {"date": "2024-03-01", "close": "510.00"},
            {"date": "2024-01-01", "close": "490.00"},
            {"date": "2024-02-01", "close": "500.00"},
        ]

        with patch(
            "app.services.webull_market_data.WebullMarketDataService.get_historical_bars",
            return_value=mock_bars,
        ):
            response = client.get("/api/v1/benchmarks/SPY/performance")

        assert response.status_code == 200
        data = response.json()
        dates = [pt["date"] for pt in data["timeseries"]]
        assert dates == sorted(dates)

    def test_benchmark_webull_failure_returns_warning(self, client, monkeypatch):
        """When Webull raises an exception the endpoint returns warning, not 500"""
        from app.config import settings

        monkeypatch.setattr(settings, "webull_app_key", "test-key")
        monkeypatch.setattr(settings, "webull_app_secret", "test-secret")

        with patch(
            "app.services.webull_market_data.WebullMarketDataService.get_historical_bars",
            side_effect=RuntimeError("network error"),
        ):
            response = client.get("/api/v1/benchmarks/SPY/performance")

        assert response.status_code == 200
        data = response.json()
        assert data["timeseries"] == []
        assert data["warning"] is not None
