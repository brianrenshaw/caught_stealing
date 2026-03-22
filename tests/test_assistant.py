"""Test AI assistant tool handlers and engine."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.assistant_tools import (
    find_player,
    handle_compare_players,
    handle_get_player_stats,
)
from tests.conftest import (
    make_batting_stats,
    make_player,
    make_statcast_summary,
)


@pytest.mark.asyncio
class TestFindPlayer:
    async def test_exact_match(self, session):
        player = make_player(name="Mike Trout", team="LAA", position="OF")
        session.add(player)
        await session.flush()

        result = await find_player(session, "Mike Trout")
        assert result["found"] is True
        assert result["multiple"] is False
        assert result["player"].name == "Mike Trout"

    async def test_partial_match(self, session):
        player = make_player(name="Mike Trout", team="LAA", position="OF")
        session.add(player)
        await session.flush()

        result = await find_player(session, "Trout")
        assert result["found"] is True
        assert result["player"].name == "Mike Trout"

    async def test_no_match(self, session):
        result = await find_player(session, "Nonexistent Player")
        assert result["found"] is False
        assert "error" in result

    async def test_multiple_matches(self, session):
        session.add(make_player(name="Will Smith", team="LAD", position="C"))
        session.add(make_player(name="Will Smith", team="ATL", position="RP"))
        await session.flush()

        result = await find_player(session, "Will Smith")
        # Should find exact match (first one)
        assert result["found"] is True

    async def test_case_insensitive(self, session):
        player = make_player(name="Shohei Ohtani", team="LAD", position="DH")
        session.add(player)
        await session.flush()

        result = await find_player(session, "ohtani")
        assert result["found"] is True
        assert result["player"].name == "Shohei Ohtani"


@pytest.mark.asyncio
class TestGetPlayerStats:
    async def test_returns_batting_stats(self, session):
        player = make_player(name="Test Hitter", position="SS")
        session.add(player)
        await session.flush()

        batting = make_batting_stats(player.id, hr=30, avg=0.290)
        session.add(batting)

        sc = make_statcast_summary(player.id, xba=0.285, xwoba=0.370)
        session.add(sc)
        await session.flush()

        result = await handle_get_player_stats(session, "Test Hitter")
        assert result["name"] == "Test Hitter"
        assert result["batting_stats"]["hr"] == 30
        assert result["batting_stats"]["avg"] == 0.290
        assert result["statcast"]["xba"] == 0.285

    async def test_player_not_found(self, session):
        result = await handle_get_player_stats(session, "Nobody")
        assert result["found"] is False

    async def test_no_stats_returns_none(self, session):
        player = make_player(name="No Stats Guy", position="OF")
        session.add(player)
        await session.flush()

        result = await handle_get_player_stats(session, "No Stats Guy")
        assert result["batting_stats"] is None
        assert result["statcast"] is None


@pytest.mark.asyncio
class TestCompare:
    async def test_compare_two_players(self, session):
        p1 = make_player(name="Player A", position="1B")
        p2 = make_player(name="Player B", position="1B")
        session.add_all([p1, p2])
        await session.flush()

        session.add(make_batting_stats(p1.id, hr=25, avg=0.280))
        session.add(make_batting_stats(p2.id, hr=30, avg=0.260))
        await session.flush()

        result = await handle_compare_players(session, ["Player A", "Player B"])
        assert len(result["players"]) == 2
        assert result["players"][0]["name"] == "Player A"
        assert result["players"][1]["name"] == "Player B"


class TestAssistantEngine:
    """Test the assistant engine with mocked Anthropic client."""

    @pytest.mark.asyncio
    async def test_text_only_response(self):
        """Mock a response with no tool use — just text."""
        from app.services.assistant import FantasyAssistant

        assistant = FantasyAssistant()

        # Mock the Anthropic client
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [MagicMock(type="text", text="Here's your answer.")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        assistant.client = mock_client

        with (
            patch.object(assistant, "_check_daily_budget", return_value=True),
            patch.object(assistant, "_load_history", return_value=[]),
            patch.object(assistant, "_save_message", new_callable=AsyncMock),
            patch.object(assistant, "_log_usage", new_callable=AsyncMock),
        ):
            result = await assistant.ask("test-session", "Hello")

        assert result["answer"] == "Here's your answer."
        assert result["session_id"] == "test-session"
        assert result["tools_used"] == []

    @pytest.mark.asyncio
    async def test_budget_exceeded(self):
        """When daily budget is exceeded, return budget message."""
        from app.services.assistant import FantasyAssistant

        assistant = FantasyAssistant()
        assistant.client = MagicMock()  # just needs to be truthy

        with patch.object(assistant, "_check_daily_budget", return_value=False):
            result = await assistant.ask("test-session", "Hello")

        assert "budget" in result["answer"].lower()

    @pytest.mark.asyncio
    async def test_not_configured(self):
        """When no API key, return config message."""
        from app.services.assistant import FantasyAssistant

        assistant = FantasyAssistant()
        assistant.client = None

        result = await assistant.ask("test-session", "Hello")
        assert "not configured" in result["answer"].lower()


class TestAssistantAPI:
    """Test assistant API endpoints."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as c:
            yield c

    def test_usage_endpoint(self, client):
        response = client.get("/api/assistant/usage")
        assert response.status_code == 200
        data = response.json()
        assert "today" in data
        assert "daily_limit" in data

    def test_ask_returns_html(self, client):
        """POST /api/assistant/ask should return HTML partial."""
        with patch("app.routes.assistant.fantasy_assistant") as mock_assistant:
            mock_assistant.ask = AsyncMock(
                return_value={
                    "answer": "Test answer",
                    "session_id": "test-123",
                    "tools_used": [],
                }
            )
            response = client.post(
                "/api/assistant/ask",
                data={"message": "test question", "session_id": "test-123"},
            )
            assert response.status_code == 200
            assert "Test answer" in response.text

    def test_delete_history(self, client):
        response = client.delete("/api/assistant/history/nonexistent-session")
        assert response.status_code == 200
        assert response.json()["status"] == "cleared"
