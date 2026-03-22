"""Test API endpoints with FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestSyncStatusEndpoint:
    def test_sync_status_never_synced(self, client):
        response = client.get("/api/sync/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


class TestPageRoutes:
    """Verify all pages return 200 and render without error."""

    def test_dashboard(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Dashboard" in response.text or "Fantasy Baseball" in response.text

    def test_roster(self, client):
        response = client.get("/roster")
        assert response.status_code == 200

    def test_projections(self, client):
        response = client.get("/projections")
        assert response.status_code == 200
        assert "Projections" in response.text

    def test_trades(self, client):
        response = client.get("/trades")
        assert response.status_code == 200
        assert "Trade" in response.text

    def test_waivers(self, client):
        response = client.get("/waivers")
        assert response.status_code == 200
        assert "Waiver" in response.text

    def test_matchups(self, client):
        response = client.get("/matchups")
        assert response.status_code == 200
        assert "Matchups" in response.text

    def test_projections_pitcher_filter(self, client):
        response = client.get("/projections?player_type=pitcher")
        assert response.status_code == 200

    def test_projections_position_filter(self, client):
        response = client.get("/projections?player_type=hitter&position=SS")
        assert response.status_code == 200
