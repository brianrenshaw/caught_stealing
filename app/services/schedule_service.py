"""Schedule service — team game counts, probable starters, and game details.

Provides weekly schedule intelligence for waiver wire, lineup optimization,
and AI analysis. All functions share a single cached batch API call per
date range for efficiency.
"""

import asyncio
import logging
from datetime import date, timedelta

import statsapi as statsapi_module

from app.cache import cache

logger = logging.getLogger(__name__)

# Cache TTL: 4 hours for schedule data
TTL_SCHEDULE = 4 * 60 * 60

# Map DB team abbreviations to MLB Stats API team IDs
_TEAM_ID_CACHE: dict[str, int] = {}
_ID_TO_ABBREV: dict[int, str] = {}

# Common abbreviation aliases
_TEAM_ALIASES = {
    "ARI": "AZ",
    "CWS": "CHW",
    "WSH": "WAS",
}


async def _ensure_team_ids() -> None:
    """Populate team ID cache from MLB Stats API (once)."""
    if _TEAM_ID_CACHE:
        return
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: statsapi_module.get("teams", {"sportId": 1}),
        )
        for t in data.get("teams", []):
            abbrev = t["abbreviation"]
            tid = t["id"]
            _TEAM_ID_CACHE[abbrev] = tid
            _ID_TO_ABBREV[tid] = abbrev
        # Set aliases
        for alias, canonical in _TEAM_ALIASES.items():
            team_id = _TEAM_ID_CACHE.get(canonical, 0)
            _TEAM_ID_CACHE[alias] = team_id
            _TEAM_ID_CACHE[canonical] = team_id
    except Exception as e:
        logger.warning(f"Failed to load MLB team IDs: {e}")


def get_team_abbrev(team_id: int) -> str:
    """Look up team abbreviation from MLB Stats API team ID."""
    return _ID_TO_ABBREV.get(team_id, "")


def get_week_boundaries(week_offset: int = 0) -> tuple[date, date]:
    """Return (monday, sunday) for the current or future week.

    Uses Monday as the weekly deadline boundary (matching league config).
    week_offset=0 is the current week, week_offset=1 is next week.
    """
    today = date.today()
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday) + timedelta(weeks=week_offset)
    sunday = monday + timedelta(days=6)
    return monday, sunday


async def _fetch_schedule_batch(start: date, end: date) -> list[dict]:
    """Fetch all games in a date range with a single API call.

    Returns the raw game list from statsapi.schedule(), filtered to
    regular season only. Cached for TTL_SCHEDULE.
    """
    cache_key = f"schedule:batch:{start}:{end}"
    cached_val = cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    await _ensure_team_ids()

    games: list[dict] = []
    try:
        start_str = start.strftime("%m/%d/%Y")
        end_str = end.strftime("%m/%d/%Y")
        raw = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: statsapi_module.schedule(
                start_date=start_str,
                end_date=end_str,
                sportId=1,
            ),
        )
        games = [g for g in raw if g.get("game_type") == "R"]
    except Exception as e:
        logger.warning(f"Failed to fetch schedule {start} to {end}: {e}")

    cache.set(cache_key, games, expire=TTL_SCHEDULE)
    return games


async def get_all_team_games_in_range(start: date, end: date) -> dict[str, int]:
    """Batch fetch game counts for all 30 MLB teams in a date range.

    Returns: {"NYY": 7, "BOS": 6, ...}
    """
    games = await _fetch_schedule_batch(start, end)

    team_games: dict[str, int] = {}
    for game in games:
        for side in ("away", "home"):
            team_id = game.get(f"{side}_id")
            abbrev = _ID_TO_ABBREV.get(team_id, "")
            if abbrev:
                team_games[abbrev] = team_games.get(abbrev, 0) + 1

    return team_games


async def get_probable_starters_in_range(start: date, end: date) -> dict[int, int]:
    """Get probable starter counts for a date range.

    Returns: {mlbam_id: number_of_starts}
    """
    games = await _fetch_schedule_batch(start, end)

    counts: dict[int, int] = {}
    for game in games:
        for side in ("away_pitcher_id", "home_pitcher_id"):
            pid = game.get(side)
            if pid:
                counts[int(pid)] = counts.get(int(pid), 0) + 1

    return counts


async def get_game_details_in_range(start: date, end: date) -> list[dict]:
    """Get detailed game info for a date range.

    Returns list of dicts with: game_date, away_team, home_team,
    pitcher IDs/names, venue, and weather data (when available).
    """
    games = await _fetch_schedule_batch(start, end)

    details: list[dict] = []
    for game in games:
        # Extract weather if available
        weather = {}
        if "weather" in game and game["weather"]:
            w = game["weather"]
            if isinstance(w, dict):
                weather = {
                    "temp": w.get("temp"),
                    "wind": w.get("wind"),
                    "condition": w.get("condition"),
                }
            elif isinstance(w, str):
                weather = {"condition": w}

        details.append(
            {
                "game_date": game.get("game_date", ""),
                "away_team": _ID_TO_ABBREV.get(game.get("away_id"), game.get("away_name", "")),
                "home_team": _ID_TO_ABBREV.get(game.get("home_id"), game.get("home_name", "")),
                "away_pitcher_id": game.get("away_pitcher_id"),
                "home_pitcher_id": game.get("home_pitcher_id"),
                "away_pitcher_name": game.get("away_probable_pitcher"),
                "home_pitcher_name": game.get("home_probable_pitcher"),
                "venue": game.get("venue_name", ""),
                "weather": weather,
            }
        )

    return details
