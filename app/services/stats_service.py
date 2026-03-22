import logging

import pandas as pd
import pybaseball

logger = logging.getLogger(__name__)

# Enable pybaseball's built-in caching
pybaseball.cache.enable()


class StatsService:
    async def get_batting_stats(self, season: int) -> pd.DataFrame:
        try:
            df = pybaseball.batting_stats(season)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch batting stats for {season}: {e}")
            raise

    async def get_pitching_stats(self, season: int) -> pd.DataFrame:
        try:
            df = pybaseball.pitching_stats(season)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch pitching stats for {season}: {e}")
            raise

    async def get_statcast_batter(self, player_id: int, start_dt: str, end_dt: str) -> pd.DataFrame:
        try:
            df = pybaseball.statcast_batter(start_dt, end_dt, player_id)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch Statcast data for player {player_id}: {e}")
            raise


stats_service = StatsService()
