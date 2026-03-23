"""Tests for the player comparison tool endpoints and services."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.comparison_service import _compute_percentile, percentile_color


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class TestComparePageRoute:
    def test_compare_page_loads(self, client):
        response = client.get("/compare")
        assert response.status_code == 200
        assert "Compare Players" in response.text

    def test_compare_page_with_ids(self, client):
        response = client.get("/compare?ids=1,2")
        assert response.status_code == 200

    def test_compare_page_with_tab(self, client):
        response = client.get("/compare?tab=stats")
        assert response.status_code == 200


class TestCompareSearchEndpoint:
    def test_search_returns_json(self, client):
        response = client.get("/api/compare/search?q=test")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_search_with_position(self, client):
        response = client.get("/api/compare/search?q=test&position=OF")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_search_respects_limit(self, client):
        response = client.get("/api/compare/search?q=a&limit=3")
        assert response.status_code == 200
        assert len(response.json()) <= 3


class TestMultiEndpoint:
    def test_multi_returns_list(self, client):
        response = client.get("/api/compare/multi?ids=1,2,3")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_multi_caps_at_5(self, client):
        response = client.get("/api/compare/multi?ids=1,2,3,4,5,6,7")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 5

    def test_multi_invalid_ids(self, client):
        response = client.get("/api/compare/multi?ids=abc")
        assert response.status_code == 400


class TestStatLeadersEndpoint:
    def test_leaders_returns_list(self, client):
        response = client.get("/api/compare/stat-leaders?stat=wrc_plus")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestPlayerCardEndpoint:
    def test_nonexistent_player(self, client):
        response = client.get("/api/compare/player-card/999999")
        assert response.status_code == 404

    def test_player_card_structure(self, client):
        # This will likely return 404 unless there's data, which is fine
        response = client.get("/api/compare/player-card/1")
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = response.json()
            assert "player" in data
            assert "traditional" in data
            assert "statcast" in data
            assert "percentiles" in data


class TestPercentileCalculation:
    def test_median_gets_50th_percentile(self):
        """A player with the median value should get ~50th percentile."""
        dist = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        pct, rank, total = _compute_percentile(5.0, dist, lower_is_better=False)
        assert 40 <= pct <= 60, f"Expected ~50, got {pct}"
        assert total == 10

    def test_top_value_gets_high_percentile(self):
        dist = [1.0, 2.0, 3.0, 4.0, 5.0]
        pct, rank, total = _compute_percentile(5.0, dist, lower_is_better=False)
        assert pct >= 80

    def test_bottom_value_gets_low_percentile(self):
        dist = [1.0, 2.0, 3.0, 4.0, 5.0]
        pct, rank, total = _compute_percentile(1.0, dist, lower_is_better=False)
        assert pct <= 20

    def test_inverse_stat_low_is_good(self):
        """For ERA-like stats, lower value should get higher percentile."""
        dist = [2.0, 3.0, 4.0, 5.0, 6.0]
        pct, rank, total = _compute_percentile(2.0, dist, lower_is_better=True)
        assert pct >= 80

    def test_inverse_stat_high_is_bad(self):
        dist = [2.0, 3.0, 4.0, 5.0, 6.0]
        pct, rank, total = _compute_percentile(6.0, dist, lower_is_better=True)
        assert pct <= 20

    def test_empty_distribution(self):
        pct, rank, total = _compute_percentile(5.0, [], lower_is_better=False)
        assert pct == 50
        assert total == 0

    def test_percentile_bounds(self):
        """Percentile should always be between 0 and 100."""
        dist = [1.0, 2.0, 3.0]
        for val in [0.0, 1.0, 3.0, 100.0]:
            pct, _, _ = _compute_percentile(val, dist, lower_is_better=False)
            assert 0 <= pct <= 100


class TestPercentileColorMapping:
    def test_deep_blue_low(self):
        assert percentile_color(5) == '#1a3a6b'

    def test_medium_blue(self):
        assert percentile_color(20) == '#3b6cb5'

    def test_light_blue(self):
        assert percentile_color(40) == '#89b4e8'

    def test_light_red(self):
        assert percentile_color(60) == '#e88989'

    def test_medium_red(self):
        assert percentile_color(80) == '#c53030'

    def test_deep_red_elite(self):
        assert percentile_color(95) == '#8b1a1a'

    def test_boundaries(self):
        assert percentile_color(10) == '#1a3a6b'
        assert percentile_color(11) == '#3b6cb5'
        assert percentile_color(30) == '#3b6cb5'
        assert percentile_color(31) == '#89b4e8'
        assert percentile_color(50) == '#89b4e8'
        assert percentile_color(51) == '#e88989'
        assert percentile_color(70) == '#e88989'
        assert percentile_color(71) == '#c53030'
        assert percentile_color(90) == '#c53030'
        assert percentile_color(91) == '#8b1a1a'


class TestHTMXPartials:
    def test_stat_table_partial(self, client):
        response = client.get(
            "/api/compare/stat-table?ids=1,2&period=full_season&stat_type=standard"
        )
        assert response.status_code == 200

    def test_projections_partial(self, client):
        response = client.get("/api/compare/projections-panel?ids=1,2")
        assert response.status_code == 200

    def test_splits_partial(self, client):
        response = client.get("/api/compare/splits-panel?ids=1,2")
        assert response.status_code == 200
