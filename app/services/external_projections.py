"""Fetch rest-of-season projections from external systems via pybaseball/FanGraphs.

Supports Steamer, ZiPS, ATC, and THE BAT projection systems.
Results are stored in the projections table for blending and comparison.

Also fetches projections directly from FanGraphs API with full counting stats
for league-specific fantasy points calculation, including consensus blending
across multiple projection systems.
"""

import asyncio
import logging
from typing import Any

import httpx
import pandas as pd
import pybaseball

logger = logging.getLogger(__name__)

pybaseball.cache.enable()

# FanGraphs projections API endpoint
_FG_PROJECTIONS_URL = "https://www.fangraphs.com/api/projections"
_FG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko)"
    ),
    "Accept": "application/json",
    "Referer": "https://www.fangraphs.com/projections",
}

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

    # Filter col_map to only columns present in df
    available_cols = {src: dst for src, dst in col_map.items() if src in df.columns}
    results = []
    for row in df.itertuples(index=False):
        fg_id = None
        name = None
        stats = {}
        for src_col, dst_name in available_cols.items():
            val = getattr(row, src_col, None)
            if src_col == "IDfg":
                fg_id = str(int(val)) if pd.notna(val) else None
            elif src_col == "Name":
                name = str(val) if pd.notna(val) else None
            elif src_col == "Team":
                continue
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


# ── FanGraphs Projections API ──
# These fetch full counting stats directly from the FanGraphs projections API
# (not pybaseball leaderboards) so we can calculate league-specific fantasy points.
# Supports multiple projection systems: steamer, zips, atc, thebat.

# Systems used for consensus blending
CONSENSUS_SYSTEMS = ["steamer", "zips", "atc", "fangraphsdc", "thebatx"]

# Delay between system fetches to avoid FanGraphs rate limiting (seconds)
_RATE_LIMIT_DELAY = 2


async def _fetch_fg_batting_projections(system: str) -> list[dict]:
    """Fetch batting projections from the FanGraphs projections API.

    Args:
        system: Projection system name (steamer, zips, atc, thebat).

    Returns:
        List of dicts with fangraphs_id, mlbam_id, name, and full counting stats
        needed for fantasy points calculation.
    """
    logger.info(f"Fetching {system} batting projections from FanGraphs API")
    try:
        async with httpx.AsyncClient(headers=_FG_HEADERS, timeout=30) as client:
            resp = await client.get(
                _FG_PROJECTIONS_URL,
                params={
                    "type": system,
                    "stats": "bat",
                    "pos": "all",
                    "team": "0",
                    "lg": "all",
                    "players": "0",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for row in data:
            fg_id = row.get("playerid") or row.get("playerids")
            mlbam_id = row.get("xMLBAMID")
            if not fg_id:
                continue

            stats = {
                "PA": row.get("PA", 0) or 0,
                "H": row.get("H", 0) or 0,
                "1B": row.get("1B", 0) or 0,
                "2B": row.get("2B", 0) or 0,
                "3B": row.get("3B", 0) or 0,
                "HR": row.get("HR", 0) or 0,
                "R": row.get("R", 0) or 0,
                "RBI": row.get("RBI", 0) or 0,
                "SB": row.get("SB", 0) or 0,
                "CS": row.get("CS", 0) or 0,
                "BB": row.get("BB", 0) or 0,
                "HBP": row.get("HBP", 0) or 0,
                "SO": row.get("SO", 0) or 0,
            }

            results.append({
                "fangraphs_id": str(fg_id),
                "mlbam_id": str(int(mlbam_id)) if mlbam_id else None,
                "name": row.get("PlayerName", ""),
                "stats": stats,
            })

        logger.info(f"Fetched {len(results)} {system} batting projections")
        return results

    except Exception as e:
        logger.error(f"Failed to fetch {system} batting projections: {e}")
        return []


async def _fetch_fg_pitching_projections(system: str) -> list[dict]:
    """Fetch pitching projections from the FanGraphs projections API.

    Args:
        system: Projection system name (steamer, zips, atc, thebat).

    Returns:
        List of dicts with fangraphs_id, mlbam_id, name, is_reliever flag,
        and full counting stats needed for fantasy points calculation.
    """
    logger.info(f"Fetching {system} pitching projections from FanGraphs API")
    try:
        async with httpx.AsyncClient(headers=_FG_HEADERS, timeout=30) as client:
            resp = await client.get(
                _FG_PROJECTIONS_URL,
                params={
                    "type": system,
                    "stats": "pit",
                    "pos": "all",
                    "team": "0",
                    "lg": "all",
                    "players": "0",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for row in data:
            fg_id = row.get("playerid") or row.get("playerids")
            mlbam_id = row.get("xMLBAMID")
            if not fg_id:
                continue

            gs = row.get("GS", 0) or 0
            g = row.get("G", 0) or 0
            is_reliever = gs < (g * 0.3) if g > 0 else False

            stats = {
                "IP": row.get("IP", 0) or 0,
                "K": row.get("SO", 0) or 0,
                "W": row.get("W", 0) or 0,
                "SV": row.get("SV", 0) or 0,
                "HLD": row.get("HLD", 0) or 0,
                "QS": row.get("QS", 0) or 0,
                "H": row.get("H", 0) or 0,
                "ER": row.get("ER", 0) or 0,
                "BB": row.get("BB", 0) or 0,
                "HBP": row.get("HBP", 0) or 0,
                "GS": gs,
                "G": g,
            }

            results.append({
                "fangraphs_id": str(fg_id),
                "mlbam_id": str(int(mlbam_id)) if mlbam_id else None,
                "name": row.get("PlayerName", ""),
                "is_reliever": is_reliever,
                "stats": stats,
            })

        logger.info(f"Fetched {len(results)} {system} pitching projections")
        return results

    except Exception as e:
        logger.error(f"Failed to fetch {system} pitching projections: {e}")
        return []


# ── Backward-compatible Steamer wrappers ──


async def fetch_steamer_batting_ros() -> list[dict]:
    """Fetch Steamer batting projections from FanGraphs projections API.

    Returns list of dicts with fangraphs_id, mlbam_id, name, and full counting stats
    needed for fantasy points calculation.
    """
    return await _fetch_fg_batting_projections("steamer")


async def fetch_steamer_pitching_ros() -> list[dict]:
    """Fetch Steamer pitching projections from FanGraphs projections API.

    Returns list of dicts with fangraphs_id, mlbam_id, name, and full counting stats
    needed for fantasy points calculation.
    """
    return await _fetch_fg_pitching_projections("steamer")


# ── Consensus blending ──


def _blend_stats(systems: dict[str, dict[str, float]]) -> dict[str, float]:
    """Average each stat across available systems.

    Args:
        systems: Mapping of system_name -> stat_dict. Each stat_dict maps
                 stat_name -> numeric value.

    Returns:
        Dict of stat_name -> averaged value across all systems that have it.
    """
    combined: dict[str, list[float]] = {}
    for sys_stats in systems.values():
        for stat, val in sys_stats.items():
            if val is not None:
                combined.setdefault(stat, []).append(val)
    return {stat: sum(vals) / len(vals) for stat, vals in combined.items()}


async def fetch_consensus_batting_ros() -> list[dict]:
    """Fetch Steamer, ZiPS, and ATC batting projections and blend them.

    Equal-weight consensus: average counting stats across available systems.
    If a system fails or returns empty, auto-normalizes across remaining systems.
    Fetches sequentially with a 2-second delay between requests to respect
    FanGraphs rate limits.

    Returns:
        List of dicts in the same format as fetch_steamer_batting_ros(), with
        an additional 'systems' field listing which systems contributed.
    """
    # Fetch sequentially with rate limiting
    system_data: list[tuple[str, list[dict]]] = []
    for system in CONSENSUS_SYSTEMS:
        try:
            data = await _fetch_fg_batting_projections(system)
            system_data.append((system, data))
        except Exception as e:
            logger.warning(f"Failed to fetch {system} batting: {e}")
        await asyncio.sleep(_RATE_LIMIT_DELAY)

    # Index each system's data by fangraphs_id
    # player_systems: fg_id -> {system_name: {player_dict}}
    player_systems: dict[str, dict[str, dict[str, Any]]] = {}
    for system_name, players in system_data:
        for player in players:
            fg_id = player["fangraphs_id"]
            player_systems.setdefault(fg_id, {})[system_name] = player

    # Blend stats for each player
    results: list[dict] = []
    for fg_id, systems in player_systems.items():
        # Use the first available system for metadata (name, mlbam_id)
        first_player = next(iter(systems.values()))

        stat_by_system = {name: p["stats"] for name, p in systems.items()}
        blended = _blend_stats(stat_by_system)

        results.append({
            "fangraphs_id": fg_id,
            "mlbam_id": first_player.get("mlbam_id"),
            "name": first_player.get("name", ""),
            "stats": blended,
            "systems": sorted(systems.keys()),
        })

    succeeded = [name for name, data in system_data if data]
    counts = {name: len(data) for name, data in system_data}
    logger.info(
        f"Consensus batting: {counts}, "
        f"systems_ok={succeeded}, consensus={len(results)} players"
    )

    return results


async def fetch_consensus_pitching_ros() -> list[dict]:
    """Fetch Steamer, ZiPS, and ATC pitching projections and blend them.

    Equal-weight consensus: average counting stats across available systems.
    If a system fails or returns empty, auto-normalizes across remaining systems.
    Uses Steamer's is_reliever classification as default when available.

    Returns:
        List of dicts in the same format as fetch_steamer_pitching_ros(), with
        an additional 'systems' field listing which systems contributed.
    """
    # Fetch sequentially with rate limiting
    system_data: list[tuple[str, list[dict]]] = []
    for system in CONSENSUS_SYSTEMS:
        try:
            data = await _fetch_fg_pitching_projections(system)
            system_data.append((system, data))
        except Exception as e:
            logger.warning(f"Failed to fetch {system} pitching: {e}")
        await asyncio.sleep(_RATE_LIMIT_DELAY)

    # Index each system's data by fangraphs_id
    player_systems: dict[str, dict[str, dict[str, Any]]] = {}
    for system_name, players in system_data:
        for player in players:
            fg_id = player["fangraphs_id"]
            player_systems.setdefault(fg_id, {})[system_name] = player

    # Blend stats for each player
    results: list[dict] = []
    for fg_id, systems in player_systems.items():
        # Prefer Steamer for metadata and is_reliever classification
        ref_player = systems.get("steamer") or next(iter(systems.values()))

        stat_by_system = {name: p["stats"] for name, p in systems.items()}
        blended = _blend_stats(stat_by_system)

        results.append({
            "fangraphs_id": fg_id,
            "mlbam_id": ref_player.get("mlbam_id"),
            "name": ref_player.get("name", ""),
            "is_reliever": ref_player.get("is_reliever", False),
            "stats": blended,
            "systems": sorted(systems.keys()),
        })

    succeeded = [name for name, data in system_data if data]
    counts = {name: len(data) for name, data in system_data}
    logger.info(
        f"Consensus pitching: {counts}, "
        f"systems_ok={succeeded}, consensus={len(results)} players"
    )

    return results
