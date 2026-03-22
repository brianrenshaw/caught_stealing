import asyncio
import logging
from functools import partial
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class YahooService:
    def __init__(self) -> None:
        self._query = None
        self._my_team_id: str | None = None
        self._league_name: str | None = None

    def is_configured(self) -> bool:
        return bool(settings.yahoo_client_id and settings.yahoo_client_secret)

    def _get_query(self):
        if self._query is None:
            from yfpy.query import YahooFantasySportsQuery

            self._query = YahooFantasySportsQuery(
                league_id=settings.yahoo_league_id,
                game_code="mlb",
                game_id=None,
                yahoo_consumer_key=settings.yahoo_client_id,
                yahoo_consumer_secret=settings.yahoo_client_secret,
                env_file_location=Path.cwd(),
                env_var_fallback=False,
                browser_callback=True,
            )
        return self._query

    async def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous yfpy call in an executor to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        if kwargs:
            fn = partial(func, *args, **kwargs)
            return await loop.run_in_executor(None, fn)
        if args:
            return await loop.run_in_executor(None, func, *args)
        return await loop.run_in_executor(None, func)

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


yahoo_service = YahooService()
