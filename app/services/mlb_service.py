"""MLB Stats API service for live data: rosters, injuries, probable pitchers, schedule."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

import statsapi

from app.cache import cache

logger = logging.getLogger(__name__)

# Cache TTL: 2 hours for injury data (status changes throughout the day)
TTL_INJURIES = 2 * 60 * 60


async def _run_sync(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


@dataclass
class ProbablePitcher:
    game_id: int
    game_date: str
    away_team: str
    home_team: str
    away_pitcher_name: str | None
    away_pitcher_id: int | None
    home_pitcher_name: str | None
    home_pitcher_id: int | None


@dataclass
class InjuryEntry:
    player_name: str
    mlbam_id: int
    team: str
    status: str  # e.g. "10-Day IL", "60-Day IL", "DTD"
    injury: str


@dataclass
class ScheduleGame:
    game_id: int
    game_date: str
    game_time: str | None
    away_team: str
    home_team: str
    away_score: int | None
    home_score: int | None
    status: str  # "Preview", "Live", "Final"
    away_pitcher: str | None
    home_pitcher: str | None


async def get_probable_pitchers(game_date: date | None = None) -> list[ProbablePitcher]:
    """Get probable pitchers for a given date (defaults to today)."""
    dt = game_date or date.today()
    date_str = dt.strftime("%m/%d/%Y")

    try:
        schedule = await _run_sync(statsapi.schedule, date=date_str, sportId=1)
    except Exception as e:
        logger.error(f"Failed to fetch schedule for {date_str}: {e}")
        return []

    pitchers = []
    for game in schedule:
        pitchers.append(
            ProbablePitcher(
                game_id=game.get("game_id", 0),
                game_date=dt.isoformat(),
                away_team=game.get("away_name", ""),
                home_team=game.get("home_name", ""),
                away_pitcher_name=game.get("away_probable_pitcher", None),
                away_pitcher_id=game.get("away_pitcher_id", None),
                home_pitcher_name=game.get("home_probable_pitcher", None),
                home_pitcher_id=game.get("home_pitcher_id", None),
            )
        )

    logger.info(f"Found {len(pitchers)} games with probable pitchers for {dt}")
    return pitchers


async def get_schedule(game_date: date | None = None) -> list[ScheduleGame]:
    """Get the full game schedule for a given date."""
    dt = game_date or date.today()
    date_str = dt.strftime("%m/%d/%Y")

    try:
        schedule = await _run_sync(statsapi.schedule, date=date_str, sportId=1)
    except Exception as e:
        logger.error(f"Failed to fetch schedule for {date_str}: {e}")
        return []

    games = []
    for game in schedule:
        status_code = game.get("status", "")
        if "Final" in status_code:
            status = "Final"
        elif "In Progress" in status_code or "Live" in status_code:
            status = "Live"
        else:
            status = "Preview"

        games.append(
            ScheduleGame(
                game_id=game.get("game_id", 0),
                game_date=dt.isoformat(),
                game_time=game.get("game_datetime", None),
                away_team=game.get("away_name", ""),
                home_team=game.get("home_name", ""),
                away_score=game.get("away_score"),
                home_score=game.get("home_score"),
                status=status,
                away_pitcher=game.get("away_probable_pitcher"),
                home_pitcher=game.get("home_probable_pitcher"),
            )
        )

    return games


async def get_standings() -> list[dict]:
    """Get current MLB standings."""
    try:
        raw = await _run_sync(statsapi.standings_data, leagueId="103,104")
    except Exception as e:
        logger.error(f"Failed to fetch MLB standings: {e}")
        return []

    standings = []
    for div_id, div_data in raw.items():
        division = div_data.get("div_name", "")
        for team in div_data.get("teams", []):
            standings.append(
                {
                    "team": team.get("name", ""),
                    "division": division,
                    "wins": team.get("w", 0),
                    "losses": team.get("l", 0),
                    "pct": team.get("pct", ".000"),
                    "gb": team.get("gb", "-"),
                    "streak": team.get("strk", ""),
                    "last_10": f"{team.get('l10_w', 0)}-{team.get('l10_l', 0)}",
                }
            )

    return standings


async def get_team_roster(team_id: int) -> list[dict]:
    """Get the current roster for a team by MLB team ID."""
    try:
        await _run_sync(statsapi.roster, team_id)
    except Exception as e:
        logger.error(f"Failed to fetch roster for team {team_id}: {e}")
        return []

    # statsapi.roster returns a formatted string, so we use get() for structured data
    try:
        roster_data = await _run_sync(
            statsapi.get, "team_roster", {"teamId": team_id, "rosterType": "active"}
        )
    except Exception as e:
        logger.error(f"Failed to fetch structured roster for team {team_id}: {e}")
        return []

    players = []
    for entry in roster_data.get("roster", []):
        person = entry.get("person", {})
        position = entry.get("position", {})
        players.append(
            {
                "mlbam_id": person.get("id"),
                "name": person.get("fullName", ""),
                "jersey": entry.get("jerseyNumber", ""),
                "position": position.get("abbreviation", ""),
                "status": entry.get("status", {}).get("description", "Active"),
            }
        )

    return players


async def get_injuries() -> list[InjuryEntry]:
    """Fetch current MLB injury report by scanning all 30 teams' full rosters.

    The /injuries endpoint was removed from MLB Stats API. This uses the
    fullRoster endpoint instead, filtering for IL status codes:
    D7 (7-Day IL), D10 (10-Day IL), D15 (15-Day IL), D60 (60-Day IL),
    ILF (Full Season IL), DTD (Day-to-Day).
    """
    cache_key = "mlb:injuries"
    cached_val = cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    IL_CODES = {"D7", "D10", "D15", "D60", "ILF", "DTD"}

    injuries: list[InjuryEntry] = []
    try:
        # Get all team IDs
        teams_data = await _run_sync(statsapi.get, "teams", {"sportId": 1})
        team_list = teams_data.get("teams", [])

        for team_info in team_list:
            team_id = team_info.get("id")
            team_abbrev = team_info.get("abbreviation", "")
            if not team_id:
                continue
            try:
                roster_data = await _run_sync(
                    statsapi.get,
                    "team_roster",
                    {"teamId": team_id, "rosterType": "fullRoster"},
                )
                for entry in roster_data.get("roster", []):
                    status = entry.get("status", {})
                    code = status.get("code", "")
                    if code not in IL_CODES:
                        continue
                    person = entry.get("person", {})
                    mlbam_id = person.get("id")
                    if not mlbam_id:
                        continue
                    injuries.append(
                        InjuryEntry(
                            player_name=person.get("fullName", ""),
                            mlbam_id=int(mlbam_id),
                            team=team_abbrev,
                            status=status.get("description", code),
                            injury="",
                        )
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch roster for team {team_abbrev}: {e}")
    except Exception as e:
        logger.error(f"Failed to fetch injuries from rosters: {e}")

    cache.set(cache_key, injuries, expire=TTL_INJURIES)
    logger.info(f"Fetched {len(injuries)} injury entries from team rosters")
    return injuries


async def get_player_injury_status(mlbam_id: int) -> InjuryEntry | None:
    """Look up injury status for a specific player by MLB AM ID."""
    injuries = await get_injuries()
    for entry in injuries:
        if entry.mlbam_id == mlbam_id:
            return entry
    return None


def build_injury_lookup(injuries: list[InjuryEntry]) -> dict[int, InjuryEntry]:
    """Build a lookup dict from mlbam_id to InjuryEntry."""
    return {entry.mlbam_id: entry for entry in injuries}
