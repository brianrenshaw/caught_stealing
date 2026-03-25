import asyncio
import json
import logging
from functools import partial
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# Persistent token file on the Fly volume (survives restarts)
TOKEN_FILE = Path(settings.data_dir) / "yahoo_token.json"


class YahooService:
    def __init__(self) -> None:
        self._query = None
        self._my_team_id: str | None = None
        self._league_name: str | None = None

    def is_configured(self) -> bool:
        return bool(settings.yahoo_client_id and settings.yahoo_client_secret)

    def _load_token_dict(self) -> dict | None:
        """Load Yahoo OAuth token, preferring the persisted volume file over the env var.

        Priority:
        1. Persisted token file on volume (has refreshed tokens from previous runs)
        2. YAHOO_ACCESS_TOKEN_JSON env var (initial bootstrap token)
        """
        # Try persisted file first (has latest refreshed tokens)
        if TOKEN_FILE.exists():
            try:
                token_dict = json.loads(TOKEN_FILE.read_text())
                logger.info("Loaded Yahoo token from persisted file %s", TOKEN_FILE)
                return token_dict
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load persisted token file: %s", e)

        # Fall back to env var (initial bootstrap)
        if settings.yahoo_access_token_json:
            try:
                token_dict = json.loads(settings.yahoo_access_token_json)
                if "guid" not in token_dict:
                    token_dict["guid"] = ""
                logger.info("Loaded Yahoo token from YAHOO_ACCESS_TOKEN_JSON env var")
                return token_dict
            except json.JSONDecodeError:
                logger.error("Invalid YAHOO_ACCESS_TOKEN_JSON — ignoring")

        return None

    def _persist_token(self) -> None:
        """Save the current OAuth token to disk so it survives restarts."""
        if not self._query or not self._query.oauth:
            return
        try:
            oauth = self._query.oauth
            token_data = {
                "access_token": oauth.access_token,
                "consumer_key": oauth.consumer_key,
                "consumer_secret": oauth.consumer_secret,
                "guid": getattr(oauth, "guid", ""),
                "refresh_token": oauth.refresh_token,
                "token_time": oauth.token_time,
                "token_type": oauth.token_type,
            }
            TOKEN_FILE.write_text(json.dumps(token_data))
            logger.info("Persisted refreshed Yahoo token to %s", TOKEN_FILE)
        except Exception as e:
            logger.warning("Failed to persist Yahoo token: %s", e)

    def _get_query(self):
        if self._query is None:
            from yfpy.query import YahooFantasySportsQuery

            kwargs = {
                "league_id": settings.yahoo_league_id,
                "game_code": "mlb",
                "game_id": None,
                "yahoo_consumer_key": settings.yahoo_client_id,
                "yahoo_consumer_secret": settings.yahoo_client_secret,
                "env_file_location": Path(settings.data_dir),
                "env_var_fallback": False,
                "browser_callback": not settings.headless,
            }

            # Load token from persisted file or env var
            token_dict = self._load_token_dict()
            if token_dict:
                kwargs["yahoo_access_token_json"] = token_dict

            self._query = YahooFantasySportsQuery(**kwargs)

            # Persist the token after auth (captures refreshed tokens)
            self._persist_token()
        return self._query

    async def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous yfpy call in an executor to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        if kwargs:
            fn = partial(func, *args, **kwargs)
            result = await loop.run_in_executor(None, fn)
        elif args:
            result = await loop.run_in_executor(None, func, *args)
        else:
            result = await loop.run_in_executor(None, func)
        # Persist token after each API call in case it was refreshed
        self._persist_token()
        return result

    async def _delay(self) -> None:
        """Rate limit: 0.5s between Yahoo API calls."""
        await asyncio.sleep(0.5)

    async def get_league_name(self) -> str:
        if self._league_name:
            return self._league_name
        try:
            query = self._get_query()
            await self._delay()
            league = await self._run_sync(query.get_league_info)
            name = league.name
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            self._league_name = name
            return self._league_name
        except Exception as e:
            logger.error(f"Failed to fetch league name: {e}")
            return "Unknown League"

    async def get_my_team_id(self) -> str:
        if self._my_team_id:
            return self._my_team_id
        try:
            query = self._get_query()
            await self._delay()
            teams = await self._run_sync(query.get_league_teams)
            for team in teams:
                if getattr(team, "is_owned_by_current_login", 0) == 1:
                    self._my_team_id = str(team.team_id)
                    return self._my_team_id
            # Fallback: use first team
            if teams:
                self._my_team_id = str(teams[0].team_id)
            return self._my_team_id or "1"
        except Exception as e:
            logger.error(f"Failed to find my team ID: {e}")
            return "1"

    async def get_league_standings(self):
        try:
            query = self._get_query()
            await self._delay()
            standings = await self._run_sync(query.get_league_standings)
            return standings
        except Exception as e:
            logger.error(f"Failed to fetch league standings: {e}")
            raise

    async def get_league_settings(self):
        try:
            query = self._get_query()
            await self._delay()
            league_settings = await self._run_sync(query.get_league_settings)
            return league_settings
        except Exception as e:
            logger.error(f"Failed to fetch league settings: {e}")
            raise

    async def get_my_roster(self) -> list:
        try:
            team_id = await self.get_my_team_id()
            return await self.get_team_roster(team_id)
        except Exception as e:
            logger.error(f"Failed to fetch roster: {e}")
            raise

    async def get_team_roster(self, team_id: str) -> list:
        """Try multiple methods to get a team's roster."""
        query = self._get_query()

        # Try get_team_roster_player_stats first (has stats)
        try:
            await self._delay()
            roster = await self._run_sync(query.get_team_roster_player_stats, team_id)
            if roster:
                return roster
        except Exception as e:
            logger.debug(f"get_team_roster_player_stats failed for {team_id}: {e}")

        # Fallback: get_team_roster_player_info_by_date (MLB uses dates)
        try:
            await self._delay()
            roster = await self._run_sync(query.get_team_roster_player_info_by_date, team_id)
            if roster:
                return roster
        except Exception as e:
            logger.debug(f"get_team_roster_player_info_by_date failed for {team_id}: {e}")

        # Fallback: get_team_roster_by_week with "current"
        try:
            await self._delay()
            roster = await self._run_sync(query.get_team_roster_by_week, team_id, "current")
            if roster and hasattr(roster, "players"):
                return roster.players
            if roster:
                return roster if isinstance(roster, list) else []
        except Exception as e:
            logger.debug(f"get_team_roster_by_week failed for {team_id}: {e}")

        logger.warning(f"All roster methods failed for team {team_id}")
        return []

    async def get_all_team_rosters(self) -> dict[str, list]:
        """Fetch rosters for all teams in the league."""
        try:
            query = self._get_query()
            await self._delay()
            teams = await self._run_sync(query.get_league_teams)
            rosters = {}
            for team in teams:
                tid = str(team.team_id)
                team_name = team.name
                if isinstance(team_name, bytes):
                    team_name = team_name.decode("utf-8")
                await self._delay()
                roster = await self._run_sync(query.get_team_roster_player_stats, tid)
                rosters[tid] = {
                    "team_name": team_name,
                    "team_id": tid,
                    "is_owned_by_current_login": getattr(team, "is_owned_by_current_login", 0),
                    "players": roster,
                }
            return rosters
        except Exception as e:
            logger.error(f"Failed to fetch all team rosters: {e}")
            raise

    async def get_league_transactions(self, limit: int = 10) -> list:
        try:
            query = self._get_query()
            await self._delay()
            transactions = await self._run_sync(query.get_league_transactions)
            return transactions[:limit] if transactions else []
        except Exception as e:
            logger.error(f"Failed to fetch transactions: {e}")
            return []

    async def get_free_agents(self, limit: int = 50) -> list:
        try:
            query = self._get_query()
            await self._delay()
            free_agents = await self._run_sync(
                partial(
                    query.get_league_players,
                    player_count_limit=limit,
                    player_count_start=0,
                )
            )
            return free_agents
        except Exception as e:
            logger.error(f"Failed to fetch free agents: {e}")
            return []

    async def get_matchup(self):
        try:
            query = self._get_query()
            team_id = await self.get_my_team_id()
            await self._delay()
            matchup = await self._run_sync(query.get_team_matchups, team_id)
            return matchup
        except Exception as e:
            logger.error(f"Failed to fetch matchup: {e}")
            raise

    async def get_scoreboard(self, week: int | str = "current"):
        """Get the league scoreboard for a given week."""
        try:
            query = self._get_query()
            await self._delay()
            scoreboard = await self._run_sync(query.get_league_scoreboard_by_week, week)
            return scoreboard
        except Exception as e:
            logger.error(f"Failed to fetch scoreboard for week {week}: {e}")
            raise

    async def get_team_weekly_stats(self, team_id: str | int, week: int | str = "current"):
        """Get a team's actual and projected points for a given week."""
        try:
            query = self._get_query()
            await self._delay()
            stats = await self._run_sync(query.get_team_stats_by_week, team_id, week)
            return stats
        except Exception as e:
            logger.error(f"Failed to fetch weekly stats for team {team_id}: {e}")
            raise

    async def get_team_roster_weekly_stats(
        self, team_id: str | int, week: int | str = "current"
    ):
        """Get per-player stats for a team's roster for a given week."""
        try:
            query = self._get_query()
            await self._delay()
            roster = await self._run_sync(
                query.get_team_roster_player_stats_by_week, team_id, week
            )
            return roster
        except Exception as e:
            logger.error(f"Failed to fetch roster weekly stats for team {team_id}: {e}")
            raise


yahoo_service = YahooService()
