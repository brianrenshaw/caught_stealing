import asyncio
import logging

import pandas as pd
import pybaseball

logger = logging.getLogger(__name__)

pybaseball.cache.enable()

# Statcast expected stats column mapping (batter)
BATTER_XSTATS_COL_MAP = {
    "xMLBAMID": "mlbam_id",  # column name may vary; fallback handled below
    "player_id": "mlbam_id",
    "pa": "pa",
    "avg_hit_speed": "avg_exit_velo",
    "max_hit_speed": "max_exit_velo",
    "brl_percent": "barrel_pct",
    "ev95percent": "hard_hit_pct",
    "xba": "xba",
    "xslg": "xslg",
    "xwoba": "xwoba",
    "sweetspot_percent": "sweet_spot_pct",
    "sprint_speed": "sprint_speed",
    "whiff_percent": "whiff_pct",
    "chase_percent": "chase_pct",
}

# Statcast expected stats column mapping (pitcher)
PITCHER_XSTATS_COL_MAP = {
    "xMLBAMID": "mlbam_id",
    "player_id": "mlbam_id",
    "pa": "pa",
    "avg_hit_speed": "avg_exit_velo",
    "max_hit_speed": "max_exit_velo",
    "brl_percent": "barrel_pct",
    "ev95percent": "hard_hit_pct",
    "xba": "xba",
    "xslg": "xslg",
    "xwoba": "xwoba",
    "sweetspot_percent": "sweet_spot_pct",
    "whiff_percent": "whiff_pct",
    "chase_percent": "chase_pct",
}

MAX_RETRIES = 3
RETRY_DELAY = 5


async def _run_sync(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


async def _fetch_with_retry(func, *args, **kwargs) -> pd.DataFrame:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await _run_sync(func, *args, **kwargs)
        except Exception as e:
            logger.warning(f"Statcast fetch attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(RETRY_DELAY)
    return pd.DataFrame()


def _map_xstats_columns(df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
    """Map Statcast expected stats columns to our schema."""
    rename = {}
    for src, dst in col_map.items():
        if src in df.columns and dst not in rename.values():
            rename[src] = dst
    df = df.rename(columns=rename)
    keep = [c for c in col_map.values() if c in df.columns]
    # Deduplicate column list while preserving order
    seen: set[str] = set()
    unique_keep: list[str] = []
    for c in keep:
        if c not in seen:
            seen.add(c)
            unique_keep.append(c)
    return df[unique_keep].copy()


async def fetch_statcast_batting_summary(season: int) -> pd.DataFrame:
    """Fetch aggregate Statcast expected batting stats for a season.

    Uses Baseball Savant's expected stats leaderboard via pybaseball.
    Returns one row per batter with xBA, xSLG, xwOBA, barrel%, etc.
    """
    logger.info(f"Fetching Statcast batter expected stats for {season}")
    df = await _fetch_with_retry(pybaseball.statcast_batter_expected_stats, season, minPA=1)
    if df.empty:
        logger.warning(f"No Statcast batter data returned for {season}")
        return df
    logger.info(f"Got {len(df)} batter Statcast summary rows for {season}")
    return _map_xstats_columns(df, BATTER_XSTATS_COL_MAP)


async def fetch_statcast_pitching_summary(season: int) -> pd.DataFrame:
    """Fetch aggregate Statcast expected pitching stats for a season.

    Uses Baseball Savant's expected stats leaderboard via pybaseball.
    Returns one row per pitcher with xBA-against, xSLG-against, xwOBA-against, etc.
    """
    logger.info(f"Fetching Statcast pitcher expected stats for {season}")
    df = await _fetch_with_retry(pybaseball.statcast_pitcher_expected_stats, season, minPA=1)
    if df.empty:
        logger.warning(f"No Statcast pitcher data returned for {season}")
        return df
    logger.info(f"Got {len(df)} pitcher Statcast summary rows for {season}")
    return _map_xstats_columns(df, PITCHER_XSTATS_COL_MAP)
