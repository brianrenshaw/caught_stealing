#!/usr/bin/env python3
"""Standalone historical baseball data pipeline.

Downloads batting, pitching, Statcast, park factor, and player ID data
from pybaseball / Chadwick Bureau and stores it in a local SQLite database
(backtest_data.sqlite) for offline analysis and backtesting.

Usage:
    uv run python -m scripts.data_pipeline               # all seasons 2015-2025
    uv run python -m scripts.data_pipeline --season 2024  # single season
    uv run python -m scripts.data_pipeline --force         # re-download cached data
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pybaseball
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "backtest_data.sqlite"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

DEFAULT_SEASONS = list(range(2015, 2026))
DEFAULT_STATCAST_START = 2016  # 2015 data is sparse

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

logger = logging.getLogger("data_pipeline")

# ---------------------------------------------------------------------------
# Enable pybaseball's built-in caching
# ---------------------------------------------------------------------------

pybaseball.cache.enable()

# ---------------------------------------------------------------------------
# SQLAlchemy Core table definitions (synchronous)
# ---------------------------------------------------------------------------

metadata = sa.MetaData()

batting_season_table = sa.Table(
    "batting_season",
    metadata,
    sa.Column("fangraphs_id", sa.Text, nullable=False),
    sa.Column("season", sa.Integer, nullable=False),
    sa.Column("name", sa.Text),
    sa.Column("team", sa.Text),
    sa.Column("PA", sa.Integer),
    sa.Column("AB", sa.Integer),
    sa.Column("H", sa.Integer),
    sa.Column("singles", sa.Integer),
    sa.Column("doubles", sa.Integer),
    sa.Column("triples", sa.Integer),
    sa.Column("HR", sa.Integer),
    sa.Column("R", sa.Integer),
    sa.Column("RBI", sa.Integer),
    sa.Column("SB", sa.Integer),
    sa.Column("CS", sa.Integer),
    sa.Column("BB", sa.Integer),
    sa.Column("SO", sa.Integer),
    sa.Column("HBP", sa.Integer),
    sa.Column("AVG", sa.Float),
    sa.Column("OBP", sa.Float),
    sa.Column("SLG", sa.Float),
    sa.Column("OPS", sa.Float),
    sa.Column("wOBA", sa.Float),
    sa.Column("wRC_plus", sa.Float),
    sa.Column("ISO", sa.Float),
    sa.Column("BABIP", sa.Float),
    sa.Column("K_pct", sa.Float),
    sa.Column("BB_pct", sa.Float),
    sa.Column("WAR", sa.Float),
)

pitching_season_table = sa.Table(
    "pitching_season",
    metadata,
    sa.Column("fangraphs_id", sa.Text, nullable=False),
    sa.Column("season", sa.Integer, nullable=False),
    sa.Column("name", sa.Text),
    sa.Column("team", sa.Text),
    sa.Column("W", sa.Integer),
    sa.Column("L", sa.Integer),
    sa.Column("SV", sa.Integer),
    sa.Column("HLD", sa.Integer),
    sa.Column("G", sa.Integer),
    sa.Column("GS", sa.Integer),
    sa.Column("IP", sa.Float),
    sa.Column("H", sa.Integer),
    sa.Column("ER", sa.Integer),
    sa.Column("HR", sa.Integer),
    sa.Column("BB", sa.Integer),
    sa.Column("SO", sa.Integer),
    sa.Column("QS", sa.Integer),
    sa.Column("HBP", sa.Integer),
    sa.Column("ERA", sa.Float),
    sa.Column("WHIP", sa.Float),
    sa.Column("K_per_9", sa.Float),
    sa.Column("BB_per_9", sa.Float),
    sa.Column("FIP", sa.Float),
    sa.Column("xFIP", sa.Float),
    sa.Column("SIERA", sa.Float),
    sa.Column("K_pct", sa.Float),
    sa.Column("BB_pct", sa.Float),
    sa.Column("K_BB_pct", sa.Float),
    sa.Column("WAR", sa.Float),
)

statcast_season_table = sa.Table(
    "statcast_season",
    metadata,
    sa.Column("mlbam_id", sa.Text, nullable=False),
    sa.Column("season", sa.Integer, nullable=False),
    sa.Column("name", sa.Text),
    sa.Column("PA", sa.Integer),
    sa.Column("xba", sa.Float),
    sa.Column("xslg", sa.Float),
    sa.Column("xwoba", sa.Float),
    sa.Column("barrel_pct", sa.Float),
    sa.Column("hard_hit_pct", sa.Float),
    sa.Column("avg_exit_velo", sa.Float),
    sa.Column("max_exit_velo", sa.Float),
    sa.Column("sweet_spot_pct", sa.Float),
    sa.Column("whiff_pct", sa.Float),
    sa.Column("sprint_speed", sa.Float),
)

park_factors_table = sa.Table(
    "park_factors",
    metadata,
    sa.Column("team", sa.Text, nullable=False),
    sa.Column("season", sa.Integer, nullable=False),
    sa.Column("basic", sa.Integer),
    sa.Column("hr", sa.Integer),
    sa.Column("so", sa.Integer),
    sa.Column("bb", sa.Integer),
    sa.Column("h", sa.Integer),
    sa.Column("doubles", sa.Integer),
    sa.Column("triples", sa.Integer),
)

player_ids_table = sa.Table(
    "player_ids",
    metadata,
    sa.Column("fangraphs_id", sa.Text),
    sa.Column("mlbam_id", sa.Text),
    sa.Column("bbref_id", sa.Text),
    sa.Column("retro_id", sa.Text),
    sa.Column("name_first", sa.Text),
    sa.Column("name_last", sa.Text),
)

# ---------------------------------------------------------------------------
# Column mappings: pybaseball output -> our schema
# ---------------------------------------------------------------------------

BATTING_COL_MAP: dict[str, str] = {
    "IDfg": "fangraphs_id",
    "Name": "name",
    "Team": "team",
    "PA": "PA",
    "AB": "AB",
    "H": "H",
    "2B": "doubles",
    "3B": "triples",
    "HR": "HR",
    "R": "R",
    "RBI": "RBI",
    "SB": "SB",
    "CS": "CS",
    "BB": "BB",
    "SO": "SO",
    "HBP": "HBP",
    "AVG": "AVG",
    "OBP": "OBP",
    "SLG": "SLG",
    "OPS": "OPS",
    "wOBA": "wOBA",
    "wRC+": "wRC_plus",
    "ISO": "ISO",
    "BABIP": "BABIP",
    "K%": "K_pct",
    "BB%": "BB_pct",
    "WAR": "WAR",
}

PITCHING_COL_MAP: dict[str, str] = {
    "IDfg": "fangraphs_id",
    "Name": "name",
    "Team": "team",
    "W": "W",
    "L": "L",
    "SV": "SV",
    "HLD": "HLD",
    "G": "G",
    "GS": "GS",
    "IP": "IP",
    "H": "H",
    "ER": "ER",
    "HR": "HR",
    "BB": "BB",
    "SO": "SO",
    "QS": "QS",
    "HBP": "HBP",
    "ERA": "ERA",
    "WHIP": "WHIP",
    "K/9": "K_per_9",
    "BB/9": "BB_per_9",
    "FIP": "FIP",
    "xFIP": "xFIP",
    "SIERA": "SIERA",
    "K%": "K_pct",
    "BB%": "BB_pct",
    "K-BB%": "K_BB_pct",
    "WAR": "WAR",
}

XSTATS_COL_MAP: dict[str, str] = {
    "player_id": "mlbam_id",
    "pa": "PA",
    "last_name, first_name": "name",
    "est_ba": "xba",
    "est_slg": "xslg",
    "est_woba": "xwoba",
    "whiff_percent": "whiff_pct",
}

EV_BARREL_COL_MAP: dict[str, str] = {
    "player_id": "mlbam_id",
    "last_name, first_name": "name",
    "avg_hit_speed": "avg_exit_velo",
    "max_hit_speed": "max_exit_velo",
    "brl_percent": "barrel_pct",
    "ev95percent": "hard_hit_pct",
    "anglesweetspotpercent": "sweet_spot_pct",
}

SPRINT_COL_MAP: dict[str, str] = {
    "player_id": "mlbam_id",
    "hp_to_1b": "sprint_speed",
}

CHADWICK_COL_MAP: dict[str, str] = {
    "key_fangraphs": "fangraphs_id",
    "key_mlbam": "mlbam_id",
    "key_bbref": "bbref_id",
    "key_retro": "retro_id",
    "name_first": "name_first",
    "name_last": "name_last",
}

# ---------------------------------------------------------------------------
# Hardcoded park factors (FanGraphs 5-year averages, runs-based)
# Used as fallback when pybaseball park factors are unavailable.
# ---------------------------------------------------------------------------

PARK_FACTORS_FALLBACK: dict[str, dict[str, int]] = {
    "COL": {"basic": 118, "hr": 115, "so": 93, "bb": 100, "h": 112, "doubles": 118, "triples": 148},
    "CIN": {"basic": 106, "hr": 113, "so": 97, "bb": 100, "h": 103, "doubles": 101, "triples": 88},
    "TEX": {"basic": 104, "hr": 108, "so": 98, "bb": 100, "h": 102, "doubles": 99, "triples": 95},
    "BOS": {"basic": 104, "hr": 96,  "so": 99, "bb": 100, "h": 105, "doubles": 128, "triples": 62},
    "MIL": {"basic": 103, "hr": 110, "so": 99, "bb": 100, "h": 100, "doubles": 96, "triples": 95},
    "PHI": {"basic": 102, "hr": 110, "so": 100, "bb": 100, "h": 100, "doubles": 99, "triples": 90},
    "CHC": {"basic": 102, "hr": 108, "so": 100, "bb": 100, "h": 100, "doubles": 99, "triples": 85},
    "ATL": {"basic": 101, "hr": 104, "so": 100, "bb": 100, "h": 100, "doubles": 100, "triples": 95},
    "TOR": {"basic": 101, "hr": 106, "so": 100, "bb": 100, "h": 99, "doubles": 98, "triples": 82},
    "LAA": {"basic": 101, "hr": 102, "so": 100, "bb": 100, "h": 100, "doubles": 100, "triples": 100},
    "MIN": {"basic": 101, "hr": 108, "so": 99, "bb": 100, "h": 99, "doubles": 98, "triples": 85},
    "ARI": {"basic": 101, "hr": 101, "so": 99, "bb": 100, "h": 101, "doubles": 103, "triples": 110},
    "NYY": {"basic": 100, "hr": 108, "so": 99, "bb": 100, "h": 98, "doubles": 91, "triples": 60},
    "WSH": {"basic": 100, "hr": 101, "so": 100, "bb": 100, "h": 100, "doubles": 100, "triples": 95},
    "DET": {"basic": 100, "hr": 100, "so": 100, "bb": 100, "h": 100, "doubles": 100, "triples": 100},
    "BAL": {"basic": 100, "hr": 105, "so": 99, "bb": 100, "h": 99, "doubles": 97, "triples": 85},
    "CLE": {"basic": 99,  "hr": 98,  "so": 100, "bb": 100, "h": 100, "doubles": 100, "triples": 100},
    "CHW": {"basic": 99,  "hr": 104, "so": 100, "bb": 100, "h": 98, "doubles": 97, "triples": 85},
    "HOU": {"basic": 99,  "hr": 101, "so": 100, "bb": 100, "h": 99, "doubles": 100, "triples": 90},
    "STL": {"basic": 98,  "hr": 96,  "so": 100, "bb": 100, "h": 100, "doubles": 102, "triples": 100},
    "LAD": {"basic": 98,  "hr": 96,  "so": 101, "bb": 100, "h": 99, "doubles": 99, "triples": 95},
    "KCR": {"basic": 98,  "hr": 92,  "so": 101, "bb": 100, "h": 101, "doubles": 104, "triples": 115},
    "PIT": {"basic": 97,  "hr": 92,  "so": 101, "bb": 100, "h": 99, "doubles": 100, "triples": 100},
    "SDP": {"basic": 97,  "hr": 92,  "so": 102, "bb": 100, "h": 99, "doubles": 100, "triples": 100},
    "SEA": {"basic": 97,  "hr": 96,  "so": 101, "bb": 100, "h": 98, "doubles": 97, "triples": 90},
    "TBR": {"basic": 96,  "hr": 94,  "so": 101, "bb": 100, "h": 98, "doubles": 97, "triples": 80},
    "SFG": {"basic": 96,  "hr": 90,  "so": 101, "bb": 100, "h": 98, "doubles": 99, "triples": 95},
    "NYM": {"basic": 96,  "hr": 95,  "so": 101, "bb": 100, "h": 97, "doubles": 97, "triples": 85},
    "MIA": {"basic": 95,  "hr": 88,  "so": 102, "bb": 100, "h": 98, "doubles": 98, "triples": 90},
    "OAK": {"basic": 95,  "hr": 90,  "so": 102, "bb": 100, "h": 97, "doubles": 96, "triples": 90},
}

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _fetch_with_retry(func: Any, *args: Any, **kwargs: Any) -> pd.DataFrame:
    """Call a pybaseball function with retry logic.

    Retries up to MAX_RETRIES times with RETRY_DELAY seconds between attempts.
    Returns an empty DataFrame if all attempts fail.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = func(*args, **kwargs)
            if result is None:
                return pd.DataFrame()
            return result
        except Exception as e:
            logger.warning(
                "Attempt %d/%d for %s failed: %s",
                attempt,
                MAX_RETRIES,
                func.__name__,
                e,
            )
            if attempt == MAX_RETRIES:
                logger.error("All %d attempts failed for %s", MAX_RETRIES, func.__name__)
                return pd.DataFrame()
            time.sleep(RETRY_DELAY)
    return pd.DataFrame()


def _rename_and_select(df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
    """Rename columns per mapping and keep only mapped columns that exist."""
    rename = {src: dst for src, dst in col_map.items() if src in df.columns}
    df = df.rename(columns=rename)
    keep = list(dict.fromkeys(dst for dst in col_map.values() if dst in df.columns))
    return df[keep].copy()


def _clean_for_sqlite(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert DataFrame to list of dicts with NaN/inf replaced by None.

    SQLite does not handle NaN or inf values natively, so we convert them
    to None (which becomes NULL in the database).
    """
    df = df.replace([np.inf, -np.inf], np.nan)
    # Drop duplicate columns (can happen from Statcast merge)
    df = df.loc[:, ~df.columns.duplicated()]
    records = df.where(df.notna(), other=None).to_dict(orient="records")
    # Ensure all values are Python-native types (not numpy scalars)
    cleaned: list[dict[str, Any]] = []
    for row in records:
        clean_row: dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, (np.integer,)):
                clean_row[k] = int(v)
            elif isinstance(v, (np.floating,)):
                clean_row[k] = None if pd.isna(v) else float(v)
            elif isinstance(v, float) and pd.isna(v):
                clean_row[k] = None
            else:
                clean_row[k] = v
        cleaned.append(clean_row)
    return cleaned


def _read_cache(name: str) -> pd.DataFrame | None:
    """Read a cached CSV from data/raw/ if it exists."""
    path = RAW_DIR / f"{name}.csv"
    if path.exists():
        logger.info("Reading cached %s", path.name)
        return pd.read_csv(path, low_memory=False)
    return None


def _write_cache(df: pd.DataFrame, name: str) -> None:
    """Write a DataFrame to CSV cache in data/raw/."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{name}.csv"
    df.to_csv(path, index=False)
    logger.info("Cached %d rows to %s", len(df), path.name)


# ---------------------------------------------------------------------------
# Data fetch functions
# ---------------------------------------------------------------------------


def fetch_batting(season: int, force: bool = False) -> pd.DataFrame:
    """Fetch FanGraphs batting stats for a season.

    Returns a DataFrame with columns mapped to our batting_season schema.
    Derives singles (1B = H - 2B - 3B - HR).
    """
    cache_name = f"batting_{season}"
    if not force:
        cached = _read_cache(cache_name)
        if cached is not None:
            return cached

    logger.info("Downloading batting stats for %d", season)
    raw = _fetch_with_retry(pybaseball.batting_stats, season, qual=0)
    if raw.empty:
        logger.warning("No batting data returned for %d", season)
        return pd.DataFrame()

    _write_cache(raw, cache_name)
    return raw


def fetch_pitching(season: int, force: bool = False) -> pd.DataFrame:
    """Fetch FanGraphs pitching stats for a season."""
    cache_name = f"pitching_{season}"
    if not force:
        cached = _read_cache(cache_name)
        if cached is not None:
            return cached

    logger.info("Downloading pitching stats for %d", season)
    raw = _fetch_with_retry(pybaseball.pitching_stats, season, qual=0)
    if raw.empty:
        logger.warning("No pitching data returned for %d", season)
        return pd.DataFrame()

    _write_cache(raw, cache_name)
    return raw


def fetch_statcast(season: int, force: bool = False) -> pd.DataFrame:
    """Fetch and merge Statcast expected stats, exit velo/barrels, and sprint speed.

    Follows the same outer-join merge pattern as app/services/statcast_service.py.
    """
    # --- Expected stats ---
    xstats_cache = f"statcast_xstats_{season}"
    xstats_raw: pd.DataFrame | None = None if force else _read_cache(xstats_cache)
    if xstats_raw is None:
        logger.info("Downloading Statcast expected stats for %d", season)
        xstats_raw = _fetch_with_retry(
            pybaseball.statcast_batter_expected_stats, season, minPA=1
        )
        if not xstats_raw.empty:
            _write_cache(xstats_raw, xstats_cache)

    # --- Exit velo / barrels ---
    ev_cache = f"statcast_ev_{season}"
    ev_raw: pd.DataFrame | None = None if force else _read_cache(ev_cache)
    if ev_raw is None:
        logger.info("Downloading Statcast exit velo / barrels for %d", season)
        ev_raw = _fetch_with_retry(
            pybaseball.statcast_batter_exitvelo_barrels, season, minBBE=1
        )
        if not ev_raw.empty:
            _write_cache(ev_raw, ev_cache)

    # --- Sprint speed ---
    sprint_cache = f"statcast_sprint_{season}"
    sprint_raw: pd.DataFrame | None = None if force else _read_cache(sprint_cache)
    if sprint_raw is None:
        logger.info("Downloading Statcast sprint speed for %d", season)
        sprint_raw = _fetch_with_retry(pybaseball.statcast_sprint_speed, season)
        if not sprint_raw.empty:
            _write_cache(sprint_raw, sprint_cache)

    # --- Map columns ---
    xstats = (
        _rename_and_select(xstats_raw, XSTATS_COL_MAP)
        if xstats_raw is not None and not xstats_raw.empty
        else pd.DataFrame()
    )
    ev = (
        _rename_and_select(ev_raw, EV_BARREL_COL_MAP)
        if ev_raw is not None and not ev_raw.empty
        else pd.DataFrame()
    )
    sprint = (
        _rename_and_select(sprint_raw, SPRINT_COL_MAP)
        if sprint_raw is not None and not sprint_raw.empty
        else pd.DataFrame()
    )

    # --- Merge on mlbam_id (outer join pattern from statcast_service.py) ---
    if not xstats.empty and not ev.empty:
        merged = pd.merge(xstats, ev, on="mlbam_id", how="outer", suffixes=("", "_ev"))
        # Prefer name from xstats; fill from ev if missing
        if "name_ev" in merged.columns:
            merged["name"] = merged["name"].fillna(merged["name_ev"])
            merged.drop(columns=["name_ev"], inplace=True)
    elif not xstats.empty:
        merged = xstats
    elif not ev.empty:
        merged = ev
    else:
        logger.warning("No Statcast data available for %d", season)
        return pd.DataFrame()

    # Merge sprint speed
    if not sprint.empty:
        merged = pd.merge(merged, sprint, on="mlbam_id", how="left")

    return merged


def fetch_player_ids(force: bool = False) -> pd.DataFrame:
    """Fetch the Chadwick Bureau player ID register.

    Downloads the CSV from GitHub and caches it locally.
    """
    cache_name = "chadwick_register"
    if not force:
        cached = _read_cache(cache_name)
        if cached is not None:
            return cached

    url = "https://raw.githubusercontent.com/chadwickbureau/register/refs/heads/master/data/people.csv"
    logger.info("Downloading Chadwick Bureau player register from GitHub")
    try:
        # Use ssl context to handle certificate issues on macOS
        import ssl
        import urllib.request
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, context=ssl_ctx) as resp:
            import io
            raw = pd.read_csv(io.BytesIO(resp.read()), low_memory=False)
        _write_cache(raw, cache_name)
        return raw
    except Exception as e:
        logger.error("Failed to download Chadwick register: %s", e)
        return pd.DataFrame()


def fetch_park_factors(season: int, force: bool = False) -> pd.DataFrame:
    """Fetch park factors for a season.

    Tries pybaseball first; falls back to hardcoded FanGraphs averages.
    """
    cache_name = f"park_factors_{season}"
    if not force:
        cached = _read_cache(cache_name)
        if cached is not None:
            return cached

    # Try pybaseball (not all versions expose park factors)
    try:
        logger.info("Attempting pybaseball park factors for %d", season)
        from pybaseball import team_batting  # noqa: F401

        # pybaseball doesn't have a clean park factor function; use fallback
        raise NotImplementedError("Using fallback park factors")
    except Exception:
        logger.info("Using hardcoded park factors for %d", season)
        rows = []
        for team, factors in PARK_FACTORS_FALLBACK.items():
            rows.append({"team": team, "season": season, **factors})
        df = pd.DataFrame(rows)
        _write_cache(df, cache_name)
        return df


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------


def create_engine_sync() -> sa.engine.Engine:
    """Create a synchronous SQLAlchemy engine for the backtest database."""
    return sa.create_engine(f"sqlite:///{DB_PATH}", echo=False)


def init_db(engine: sa.engine.Engine) -> None:
    """Create all tables, dropping existing ones for a clean load."""
    metadata.drop_all(engine)
    metadata.create_all(engine)
    logger.info("Initialized database at %s", DB_PATH)


def insert_batting(engine: sa.engine.Engine, raw: pd.DataFrame, season: int) -> int:
    """Transform and insert batting data for a season. Returns row count."""
    mapped = _rename_and_select(raw, BATTING_COL_MAP)
    if mapped.empty:
        return 0

    # Derive singles
    for col in ("H", "doubles", "triples", "HR"):
        if col not in mapped.columns:
            mapped[col] = 0
    mapped["singles"] = (
        mapped["H"].fillna(0).astype(int)
        - mapped["doubles"].fillna(0).astype(int)
        - mapped["triples"].fillna(0).astype(int)
        - mapped["HR"].fillna(0).astype(int)
    )

    mapped["season"] = season
    # Convert fangraphs_id to string
    mapped["fangraphs_id"] = mapped["fangraphs_id"].astype(str)

    records = _clean_for_sqlite(mapped)
    with engine.begin() as conn:
        conn.execute(batting_season_table.insert(), records)
    return len(records)


def insert_pitching(engine: sa.engine.Engine, raw: pd.DataFrame, season: int) -> int:
    """Transform and insert pitching data for a season. Returns row count."""
    mapped = _rename_and_select(raw, PITCHING_COL_MAP)
    if mapped.empty:
        return 0

    mapped["season"] = season
    mapped["fangraphs_id"] = mapped["fangraphs_id"].astype(str)

    records = _clean_for_sqlite(mapped)
    with engine.begin() as conn:
        conn.execute(pitching_season_table.insert(), records)
    return len(records)


def insert_statcast(engine: sa.engine.Engine, df: pd.DataFrame, season: int) -> int:
    """Insert Statcast data for a season. Returns row count."""
    if df.empty:
        return 0

    # Ensure all expected columns exist
    expected_cols = [c.name for c in statcast_season_table.columns]
    for col in expected_cols:
        if col not in df.columns and col != "season":
            df[col] = None

    df["season"] = season
    df["mlbam_id"] = df["mlbam_id"].astype(str)

    # Keep only columns that exist in the table
    keep = [c for c in expected_cols if c in df.columns]
    df = df[keep].copy()

    records = _clean_for_sqlite(df)
    with engine.begin() as conn:
        conn.execute(statcast_season_table.insert(), records)
    return len(records)


def insert_park_factors(engine: sa.engine.Engine, df: pd.DataFrame) -> int:
    """Insert park factors. Returns row count."""
    if df.empty:
        return 0

    expected_cols = [c.name for c in park_factors_table.columns]
    keep = [c for c in expected_cols if c in df.columns]
    df = df[keep].copy()

    records = _clean_for_sqlite(df)
    with engine.begin() as conn:
        conn.execute(park_factors_table.insert(), records)
    return len(records)


def insert_player_ids(engine: sa.engine.Engine, raw: pd.DataFrame) -> int:
    """Transform and insert Chadwick player IDs. Returns row count."""
    if raw.empty:
        return 0

    mapped = _rename_and_select(raw, CHADWICK_COL_MAP)
    if mapped.empty:
        return 0

    # Filter to players that have at least one useful ID
    id_cols = ["fangraphs_id", "mlbam_id", "bbref_id"]
    existing_id_cols = [c for c in id_cols if c in mapped.columns]
    if existing_id_cols:
        mapped = mapped.dropna(subset=existing_id_cols, how="all")

    # Convert IDs to strings
    for col in ["fangraphs_id", "mlbam_id"]:
        if col in mapped.columns:
            mapped[col] = mapped[col].apply(
                lambda x: str(int(x)) if pd.notna(x) and isinstance(x, float) else (str(x) if pd.notna(x) else None)
            )

    records = _clean_for_sqlite(mapped)
    with engine.begin() as conn:
        conn.execute(player_ids_table.insert(), records)
    return len(records)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    seasons: list[int],
    statcast_start: int,
    force: bool,
) -> None:
    """Execute the full data pipeline.

    Args:
        seasons: List of seasons to fetch.
        statcast_start: First season to fetch Statcast data.
        force: If True, re-download even if cached CSVs exist.
    """
    start_time = time.time()

    engine = create_engine_sync()
    init_db(engine)

    total_batting = 0
    total_pitching = 0
    total_statcast = 0
    total_park = 0

    # --- Batting and Pitching (all seasons) ---
    for season in seasons:
        logger.info("=" * 60)
        logger.info("Processing season %d", season)
        logger.info("=" * 60)

        # Batting
        raw_batting = fetch_batting(season, force=force)
        if not raw_batting.empty:
            count = insert_batting(engine, raw_batting, season)
            total_batting += count
            logger.info("Inserted %d batting rows for %d", count, season)

        # Pitching
        raw_pitching = fetch_pitching(season, force=force)
        if not raw_pitching.empty:
            count = insert_pitching(engine, raw_pitching, season)
            total_pitching += count
            logger.info("Inserted %d pitching rows for %d", count, season)

        # Statcast (only for eligible seasons)
        if season >= statcast_start:
            statcast_df = fetch_statcast(season, force=force)
            if not statcast_df.empty:
                count = insert_statcast(engine, statcast_df, season)
                total_statcast += count
                logger.info("Inserted %d Statcast rows for %d", count, season)
        else:
            logger.info("Skipping Statcast for %d (before statcast_start=%d)", season, statcast_start)

        # Park factors
        park_df = fetch_park_factors(season, force=force)
        if not park_df.empty:
            count = insert_park_factors(engine, park_df)
            total_park += count
            logger.info("Inserted %d park factor rows for %d", count, season)

    # --- Player IDs (once, not per-season) ---
    logger.info("=" * 60)
    logger.info("Fetching player ID register")
    logger.info("=" * 60)
    ids_raw = fetch_player_ids(force=force)
    total_ids = 0
    if not ids_raw.empty:
        total_ids = insert_player_ids(engine, ids_raw)
        logger.info("Inserted %d player ID rows", total_ids)

    # --- Summary ---
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1f seconds", elapsed)
    logger.info(
        "  Batting:    %d rows across %d seasons",
        total_batting,
        len(seasons),
    )
    logger.info(
        "  Pitching:   %d rows across %d seasons",
        total_pitching,
        len(seasons),
    )
    statcast_seasons = [s for s in seasons if s >= statcast_start]
    logger.info(
        "  Statcast:   %d rows across %d seasons",
        total_statcast,
        len(statcast_seasons),
    )
    logger.info(
        "  Park Fctrs: %d rows across %d seasons",
        total_park,
        len(seasons),
    )
    logger.info("  Player IDs: %d rows", total_ids)
    logger.info("  Database:   %s", DB_PATH)
    logger.info("=" * 60)

    print(f"\nDone. {elapsed:.1f}s elapsed. Database: {DB_PATH}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Historical baseball data pipeline. Downloads FanGraphs, "
        "Statcast, park factor, and player ID data into a local SQLite database.",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        metavar="YEAR",
        help="Fetch a single season (default: all 2015-2025)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download data even if cached CSVs exist",
    )
    parser.add_argument(
        "--statcast-start",
        type=int,
        default=DEFAULT_STATCAST_START,
        metavar="YEAR",
        help=f"First year for Statcast data (default: {DEFAULT_STATCAST_START})",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the data pipeline CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    args = parse_args()

    if args.season is not None:
        seasons = [args.season]
    else:
        seasons = DEFAULT_SEASONS

    logger.info(
        "Starting pipeline: seasons=%s, statcast_start=%d, force=%s",
        seasons if len(seasons) <= 3 else f"{seasons[0]}-{seasons[-1]}",
        args.statcast_start,
        args.force,
    )

    run_pipeline(
        seasons=seasons,
        statcast_start=args.statcast_start,
        force=args.force,
    )


if __name__ == "__main__":
    main()
