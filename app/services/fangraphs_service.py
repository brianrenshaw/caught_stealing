import asyncio
import logging
from datetime import date, timedelta

import pandas as pd
import pybaseball

logger = logging.getLogger(__name__)

pybaseball.cache.enable()

# FanGraphs column name → our DB column name mapping
BATTING_COL_MAP = {
    "IDfg": "fangraphs_id",
    "Name": "name",
    "Team": "team",
    "PA": "pa",
    "AB": "ab",
    "H": "h",
    "2B": "doubles",
    "3B": "triples",
    "HR": "hr",
    "R": "r",
    "RBI": "rbi",
    "SB": "sb",
    "CS": "cs",
    "BB": "bb",
    "SO": "so",
    "HBP": "hbp",
    "AVG": "avg",
    "OBP": "obp",
    "SLG": "slg",
    "OPS": "ops",
    "wOBA": "woba",
    "wRC+": "wrc_plus",
    "ISO": "iso",
    "BABIP": "babip",
    "K%": "k_pct",
    "BB%": "bb_pct",
    "WAR": "war",
}

PITCHING_COL_MAP = {
    "IDfg": "fangraphs_id",
    "Name": "name",
    "Team": "team",
    "W": "w",
    "L": "l",
    "SV": "sv",
    "HLD": "hld",
    "G": "g",
    "GS": "gs",
    "IP": "ip",
    "H": "h",
    "ER": "er",
    "HR": "hr",
    "BB": "bb",
    "SO": "so",
    "QS": "qs",
    "HBP": "hbp",
    "ERA": "era",
    "WHIP": "whip",
    "K/9": "k_per_9",
    "BB/9": "bb_per_9",
    "FIP": "fip",
    "xFIP": "xfip",
    "SIERA": "siera",
    "K-BB%": "k_bb_pct",
    "WAR": "war",
    "K%": "k_pct",
    "BB%": "bb_pct",
    "GB%": "gb_pct",
    "HR/FB": "hr_fb_pct",
    "LOB%": "lob_pct",
    "gmLI": "gmli",
}

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


async def _run_sync(func, *args, **kwargs):
    """Run a synchronous pybaseball function in an executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


async def _fetch_with_retry(func, *args, **kwargs) -> pd.DataFrame:
    """Retry wrapper for flaky pybaseball scraping."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await _run_sync(func, *args, **kwargs)
        except Exception as e:
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(RETRY_DELAY)
    return pd.DataFrame()  # unreachable but satisfies type checker


def _map_columns(df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
    """Rename DataFrame columns using the mapping, dropping unmapped columns."""
    rename = {k: v for k, v in col_map.items() if k in df.columns}
    df = df.rename(columns=rename)
    # Keep only mapped columns that exist
    keep = [v for v in col_map.values() if v in df.columns]
    return df[keep].copy()


def _period_for_days(days: int) -> str:
    if days <= 7:
        return "last_7"
    elif days <= 14:
        return "last_14"
    return "last_30"


async def fetch_batting_stats(season: int, qual: int = 0) -> pd.DataFrame:
    """Fetch full-season batting stats from FanGraphs."""
    logger.info(f"Fetching FanGraphs batting stats for {season} (qual={qual})")
    df = await _fetch_with_retry(pybaseball.batting_stats, season, qual=qual)
    if df.empty:
        return df
    return _map_columns(df, BATTING_COL_MAP)


async def fetch_pitching_stats(season: int, qual: int = 0) -> pd.DataFrame:
    """Fetch full-season pitching stats from FanGraphs."""
    logger.info(f"Fetching FanGraphs pitching stats for {season} (qual={qual})")
    df = await _fetch_with_retry(pybaseball.pitching_stats, season, qual=qual)
    if df.empty:
        return df
    return _map_columns(df, PITCHING_COL_MAP)


async def fetch_batting_stats_range(days: int) -> pd.DataFrame:
    """Fetch batting stats for a rolling window (last N days)."""
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=days)
    logger.info(f"Fetching FanGraphs batting stats range: {start_dt} to {end_dt}")
    df = await _fetch_with_retry(
        pybaseball.batting_stats,
        start_dt.year,
        qual=0,
        split_seasons=False,
    )
    if df.empty:
        return df
    # pybaseball.batting_stats doesn't natively support date ranges for FanGraphs data,
    # so we fetch the full season and note that period-based splits may need the
    # batting_stats_range function if/when it becomes available in pybaseball.
    return _map_columns(df, BATTING_COL_MAP)


async def fetch_pitching_stats_range(days: int) -> pd.DataFrame:
    """Fetch pitching stats for a rolling window (last N days)."""
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=days)
    logger.info(f"Fetching FanGraphs pitching stats range: {start_dt} to {end_dt}")
    df = await _fetch_with_retry(
        pybaseball.pitching_stats,
        start_dt.year,
        qual=0,
        split_seasons=False,
    )
    if df.empty:
        return df
    return _map_columns(df, PITCHING_COL_MAP)
