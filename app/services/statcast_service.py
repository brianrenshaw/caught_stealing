import asyncio
import logging

import pandas as pd
import pybaseball

logger = logging.getLogger(__name__)

pybaseball.cache.enable()

# Column mapping for expected stats (from statcast_batter/pitcher_expected_stats)
XSTATS_COL_MAP = {
    "player_id": "mlbam_id",
    "pa": "pa",
    "est_ba": "xba",
    "est_slg": "xslg",
    "est_woba": "xwoba",
    "whiff_percent": "whiff_pct",
}

# Pitcher-specific expected stats (includes xERA)
PITCHER_XSTATS_COL_MAP = {
    "player_id": "mlbam_id",
    "pa": "pa",
    "est_ba": "xba",
    "est_slg": "xslg",
    "est_woba": "xwoba",
    "est_era": "xera",
    "whiff_percent": "whiff_pct",
}

# Column mapping for sprint speed data
SPRINT_SPEED_COL_MAP = {
    "player_id": "mlbam_id",
    "hp_to_1b": "sprint_speed",
}

# Column mapping for exit velo/barrel data (from statcast_batter/pitcher_exitvelo_barrels)
EV_BARREL_COL_MAP = {
    "player_id": "mlbam_id",
    "avg_hit_speed": "avg_exit_velo",
    "max_hit_speed": "max_exit_velo",
    "brl_percent": "barrel_pct",
    "ev95percent": "hard_hit_pct",
    "anglesweetspotpercent": "sweet_spot_pct",
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


def _rename_and_select(df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
    """Rename columns per mapping and keep only mapped columns that exist."""
    rename = {}
    for src, dst in col_map.items():
        if src in df.columns and dst not in rename.values():
            rename[src] = dst
    df = df.rename(columns=rename)
    keep = [c for c in col_map.values() if c in df.columns]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_keep: list[str] = []
    for c in keep:
        if c not in seen:
            seen.add(c)
            unique_keep.append(c)
    return df[unique_keep].copy()


async def fetch_statcast_batting_summary(season: int) -> pd.DataFrame:
    """Fetch aggregate Statcast expected batting stats for a season.

    Combines expected stats (xBA, xSLG, xwOBA) with exit velocity / barrel data
    into a single DataFrame keyed by mlbam_id.
    """
    logger.info(f"Fetching Statcast batter expected stats for {season}")
    xstats_df = await _fetch_with_retry(pybaseball.statcast_batter_expected_stats, season, minPA=1)

    logger.info(f"Fetching Statcast batter exit velo / barrel data for {season}")
    ev_df = await _fetch_with_retry(pybaseball.statcast_batter_exitvelo_barrels, season, minBBE=1)

    if xstats_df.empty and ev_df.empty:
        logger.warning(f"No Statcast batter data returned for {season}")
        return pd.DataFrame()

    # Map columns from each source
    xstats_mapped = (
        _rename_and_select(xstats_df, XSTATS_COL_MAP) if not xstats_df.empty else pd.DataFrame()
    )
    ev_mapped = _rename_and_select(ev_df, EV_BARREL_COL_MAP) if not ev_df.empty else pd.DataFrame()

    # Merge on mlbam_id
    if not xstats_mapped.empty and not ev_mapped.empty:
        merged = pd.merge(xstats_mapped, ev_mapped, on="mlbam_id", how="outer")
    elif not xstats_mapped.empty:
        merged = xstats_mapped
    else:
        merged = ev_mapped

    logger.info(f"Got {len(merged)} batter Statcast summary rows for {season}")
    return merged


async def fetch_statcast_pitching_summary(season: int) -> pd.DataFrame:
    """Fetch aggregate Statcast expected pitching stats for a season.

    Combines expected stats (xBA-against, xSLG-against, xwOBA-against) with
    exit velocity / barrel data into a single DataFrame keyed by mlbam_id.
    """
    logger.info(f"Fetching Statcast pitcher expected stats for {season}")
    xstats_df = await _fetch_with_retry(pybaseball.statcast_pitcher_expected_stats, season, minPA=1)

    logger.info(f"Fetching Statcast pitcher exit velo / barrel data for {season}")
    ev_df = await _fetch_with_retry(pybaseball.statcast_pitcher_exitvelo_barrels, season, minBBE=1)

    if xstats_df.empty and ev_df.empty:
        logger.warning(f"No Statcast pitcher data returned for {season}")
        return pd.DataFrame()

    xstats_mapped = (
        _rename_and_select(xstats_df, PITCHER_XSTATS_COL_MAP)
        if not xstats_df.empty
        else pd.DataFrame()
    )
    ev_mapped = _rename_and_select(ev_df, EV_BARREL_COL_MAP) if not ev_df.empty else pd.DataFrame()

    if not xstats_mapped.empty and not ev_mapped.empty:
        merged = pd.merge(xstats_mapped, ev_mapped, on="mlbam_id", how="outer")
    elif not xstats_mapped.empty:
        merged = xstats_mapped
    else:
        merged = ev_mapped

    # Derive xERA from xwOBA-against if not directly available
    if "xera" not in merged.columns and "xwoba" in merged.columns:
        league_avg_woba = 0.320
        league_avg_era = 4.00
        merged["xera"] = (merged["xwoba"] / league_avg_woba) * league_avg_era

    logger.info(f"Got {len(merged)} pitcher Statcast summary rows for {season}")
    return merged


async def fetch_sprint_speed(season: int) -> pd.DataFrame:
    """Fetch sprint speed data for all players in a season.

    Returns DataFrame with mlbam_id and sprint_speed (ft/s).
    """
    logger.info(f"Fetching Statcast sprint speed data for {season}")
    try:
        df = await _fetch_with_retry(pybaseball.statcast_sprint_speed, season)
        if df.empty:
            logger.warning(f"No sprint speed data returned for {season}")
            return pd.DataFrame()
        mapped = _rename_and_select(df, SPRINT_SPEED_COL_MAP)
        logger.info(f"Got {len(mapped)} sprint speed rows for {season}")
        return mapped
    except Exception as e:
        logger.warning(f"Failed to fetch sprint speed data: {e}")
        return pd.DataFrame()
