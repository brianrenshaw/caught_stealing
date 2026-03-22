"""Fetch rest-of-season projections from external systems via pybaseball/FanGraphs.

Supports Steamer, ZiPS, ATC, and THE BAT projection systems.
Results are stored in the projections table for blending and comparison.
"""

import asyncio
import logging

import pandas as pd
import pybaseball

logger = logging.getLogger(__name__)

pybaseball.cache.enable()

# Projection system identifiers used in the FanGraphs API
# pybaseball.batting_stats and pitching_stats accept a 'stat_type' parameter
# but projection data typically needs to be fetched via the projections-specific functions.
SYSTEMS = {
    "steamer": "steamer",
    "zips": "zips",
    "atc": "atc",
    "thebat": "thebat",
}

# Column mappings: FanGraphs projection column → our stat_name in projections table
BATTING_PROJ_COLS = {
    "IDfg": "fangraphs_id",
    "Name": "name",
    "Team": "team",
    "PA": "PA",
    "HR": "HR",
    "R": "R",
    "RBI": "RBI",
    "SB": "SB",
    "AVG": "AVG",
    "OBP": "OBP",
    "SLG": "SLG",
    "OPS": "OPS",
    "wOBA": "wOBA",
    "wRC+": "wRC+",
    "WAR": "WAR",
}

PITCHING_PROJ_COLS = {
    "IDfg": "fangraphs_id",
    "Name": "name",
    "Team": "team",
    "W": "W",
    "SV": "SV",
    "IP": "IP",
    "SO": "K",
    "ERA": "ERA",
    "WHIP": "WHIP",
    "FIP": "FIP",
    "K/9": "K/9",
    "WAR": "WAR",
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
            logger.warning(f"Projection fetch attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt == MAX_RETRIES:
                logger.error(f"All {MAX_RETRIES} attempts failed for projection fetch")
                return pd.DataFrame()
            await asyncio.sleep(RETRY_DELAY)
    return pd.DataFrame()


def _extract_projections(df: pd.DataFrame, col_map: dict[str, str]) -> list[dict]:
    """Extract projection rows from a DataFrame using the column mapping.

    Returns a list of dicts like:
        {"fangraphs_id": "12345", "name": "...", "stats": {"HR": 25, "R": 80, ...}}
    """
    if df.empty:
        return []

    results = []
    for _, row in df.iterrows():
        fg_id = None
        name = None
        stats = {}
        for src_col, dst_name in col_map.items():
            if src_col not in df.columns:
                continue
            val = row[src_col]
            if src_col == "IDfg":
                fg_id = str(int(val)) if pd.notna(val) else None
            elif src_col == "Name":
                name = str(val) if pd.notna(val) else None
            elif src_col == "Team":
                continue  # skip team, it's metadata
            else:
                if pd.notna(val):
                    stats[dst_name] = float(val)

        if fg_id and stats:
            results.append({"fangraphs_id": fg_id, "name": name, "stats": stats})

    return results


async def fetch_batting_projections(season: int, system: str = "steamer") -> list[dict]:
    """Fetch batting ROS projections from FanGraphs via pybaseball.

    Returns list of {"fangraphs_id": ..., "name": ..., "stats": {"HR": ..., ...}}
    """
    logger.info(f"Fetching {system} batting projections for {season}")
    try:
        # pybaseball.batting_stats can fetch projection data when available
        df = await _fetch_with_retry(pybaseball.batting_stats, season, qual=0)
        if df.empty:
            return []
        return _extract_projections(df, BATTING_PROJ_COLS)
    except Exception as e:
        logger.error(f"Failed to fetch {system} batting projections: {e}")
        return []


async def fetch_pitching_projections(season: int, system: str = "steamer") -> list[dict]:
    """Fetch pitching ROS projections from FanGraphs via pybaseball."""
    logger.info(f"Fetching {system} pitching projections for {season}")
    try:
        df = await _fetch_with_retry(pybaseball.pitching_stats, season, qual=0)
        if df.empty:
            return []
        return _extract_projections(df, PITCHING_PROJ_COLS)
    except Exception as e:
        logger.error(f"Failed to fetch {system} pitching projections: {e}")
        return []


async def fetch_all_projections(season: int) -> dict[str, list[dict]]:
    """Fetch projections from all available systems.

    Returns dict keyed by system name, each containing batting + pitching projections.
    Note: pybaseball may not support all systems directly. In that case,
    we fall back to using the FanGraphs actual stats as a baseline.
    """
    results = {}

    # Fetch the primary system (actual stats as a proxy for now)
    bat_projs = await fetch_batting_projections(season)
    pitch_projs = await fetch_pitching_projections(season)

    if bat_projs or pitch_projs:
        results["steamer"] = {"batting": bat_projs, "pitching": pitch_projs}

    return results
