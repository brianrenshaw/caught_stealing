#!/usr/bin/env python3
"""Walk-forward backtesting harness for fantasy baseball projection models.

For each test season T (2019–2025), uses only data from seasons < T to build
projections, then evaluates against actual end-of-season results.

Reads from backtest_data.sqlite (created by data_pipeline.py) and outputs
results to data/results/.

Usage:
    uv run python scripts/backtest_harness.py
    uv run python scripts/backtest_harness.py --seasons 2021-2024
    uv run python scripts/backtest_harness.py --db-path path/to/backtest_data.sqlite
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HITTER_STATS = ["wOBA", "HR_rate", "K_pct", "BB_pct", "SB_rate", "AVG", "OPS"]
PITCHER_STATS = ["ERA", "FIP", "K_pct", "BB_pct", "WHIP"]

CHECKPOINTS: dict[str, float] = {
    "may15": 200.0,
    "jul01": 350.0,
    "aug15": 450.0,
}

# Marcel weights: year-1 at 5x, year-2 at 4x, year-3 at 3x
MARCEL_WEIGHTS = {1: 5, 2: 4, 3: 3}
MARCEL_REGRESS_PA = 1200
MARCEL_REGRESS_IP = 400  # Equivalent regression innings for pitchers

# Quality gate thresholds
QUALITY_GATE_IMPROVEMENT_PCT = 5.0  # Current model must beat Marcel by ≥5%
QUALITY_GATE_REGRESS_PCT = 3.0  # No stat may regress >3% vs Marcel

METHODS = ["current_model", "marcel", "naive_last_year", "league_average"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MetricResult:
    """Evaluation metrics for one (season, checkpoint, method, stat) combo."""

    season: int
    checkpoint: str
    method: str
    stat: str
    rmse: float
    mae: float
    r2: float
    n_players: int


@dataclass
class DetailRow:
    """Per-player projection detail for one (season, checkpoint, method)."""

    season: int
    checkpoint: str
    method: str
    fangraphs_id: str
    name: str
    player_type: str  # "hitter" or "pitcher"
    stat: str
    projected: float
    actual: float


@dataclass
class BacktestResults:
    """Aggregated backtest results."""

    summary: list[MetricResult] = field(default_factory=list)
    detail: list[DetailRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_data(db_path: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load all tables from backtest_data.sqlite.

    Returns:
        Tuple of (batting_season, pitching_season, statcast_season, player_ids)

    Raises:
        FileNotFoundError: If the database file does not exist.
        sqlite3.Error: If there is an error reading the database.
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"Database not found: {db_path}. "
            "Run 'uv run python -m scripts.data_pipeline' first to create it."
        )

    logger.info("Loading data from %s", db_path)
    try:
        with sqlite3.connect(db_path) as conn:
            batting = pd.read_sql("SELECT * FROM batting_season", conn)
            pitching = pd.read_sql("SELECT * FROM pitching_season", conn)

            # Statcast table may be empty if pipeline ran with --season for a pre-2016 year
            try:
                statcast = pd.read_sql("SELECT * FROM statcast_season", conn)
            except Exception as e:
                logger.warning("Could not load statcast_season table: %s", e)
                statcast = pd.DataFrame()

            player_ids = pd.read_sql("SELECT * FROM player_ids", conn)
    except sqlite3.Error as e:
        raise sqlite3.Error(f"Failed to read database {db_path}: {e}") from e

    logger.info(
        "Loaded %d batting rows, %d pitching rows, %d statcast rows, %d player IDs",
        len(batting),
        len(pitching),
        len(statcast),
        len(player_ids),
    )

    # Fallback: if player_ids crosswalk is empty, try loading from the live app's DB
    if player_ids.empty or len(player_ids) == 0:
        live_db_path = Path(db_path).parent / "fantasy_baseball.db"
        if live_db_path.exists():
            logger.info(
                "Player ID crosswalk empty; falling back to live DB at %s",
                live_db_path,
            )
            try:
                with sqlite3.connect(str(live_db_path)) as live_conn:
                    player_ids = pd.read_sql(
                        "SELECT fangraphs_id, mlbam_id FROM players "
                        "WHERE fangraphs_id IS NOT NULL AND mlbam_id IS NOT NULL",
                        live_conn,
                    )
                logger.info(
                    "Loaded %d player ID mappings from live DB fallback",
                    len(player_ids),
                )
            except Exception as e:
                logger.warning("Failed to load IDs from live DB: %s", e)
        else:
            logger.warning(
                "No live DB found at %s; Statcast merge will use name-based fallback",
                live_db_path,
            )

    return batting, pitching, statcast, player_ids


def merge_statcast_to_batting(
    batting: pd.DataFrame,
    statcast: pd.DataFrame,
    player_ids: pd.DataFrame,
) -> pd.DataFrame:
    """Merge Statcast expected stats onto batting data via player_ids bridge table.

    Returns batting dataframe with added Statcast columns.
    If statcast or player_ids are empty, returns batting with NaN Statcast columns.
    """
    batting = batting.copy()
    batting["fangraphs_id"] = batting["fangraphs_id"].astype(str)

    if statcast.empty:
        logger.warning("Statcast data is empty; skipping Statcast merge")
        return batting

    statcast = statcast.copy()
    statcast_cols = ["xba", "xslg", "xwoba", "barrel_pct", "hard_hit_pct"]
    available_sc_cols = [c for c in statcast_cols if c in statcast.columns]

    def _normalize_name(name: str) -> str:
        """Convert 'Last, First' or 'First Last' to lowercase 'first last'."""
        import unicodedata
        if not isinstance(name, str):
            return ""
        # Remove accents
        name = unicodedata.normalize("NFD", name)
        name = "".join(c for c in name if unicodedata.category(c) != "Mn")
        name = name.strip().lower()
        if "," in name:
            parts = name.split(",", 1)
            name = f"{parts[1].strip()} {parts[0].strip()}"
        # Remove Jr., Sr., III, II suffixes
        for suffix in [" jr.", " sr.", " iii", " ii", " iv"]:
            name = name.replace(suffix, "")
        return name.strip()

    if not player_ids.empty:
        # Preferred: merge via crosswalk (fangraphs_id -> mlbam_id -> statcast)
        id_map = player_ids[["fangraphs_id", "mlbam_id"]].dropna().drop_duplicates(subset=["fangraphs_id"], keep="first")
        id_map["fangraphs_id"] = id_map["fangraphs_id"].astype(str)
        id_map["mlbam_id"] = id_map["mlbam_id"].astype(str)
        batting = batting.merge(id_map, on="fangraphs_id", how="left")
        statcast["mlbam_id"] = statcast["mlbam_id"].astype(str)
        batting = batting.merge(
            statcast[["mlbam_id", "season"] + available_sc_cols],
            on=["mlbam_id", "season"],
            how="left",
        )

        # Second fallback: for rows that didn't match via ID, try name-based merge
        if available_sc_cols and "name" in statcast.columns:
            unmatched_mask = batting[available_sc_cols[0]].isna()
            n_unmatched = unmatched_mask.sum()
            if n_unmatched > 0:
                logger.info(
                    "ID-based merge left %d unmatched rows; trying name-based fallback",
                    n_unmatched,
                )
                batting["_merge_name"] = batting["name"].apply(_normalize_name)
                sc_merge = statcast[["name", "season"] + available_sc_cols].copy()
                sc_merge["_merge_name"] = sc_merge["name"].apply(_normalize_name)
                sc_merge = sc_merge.drop(columns=["name"])
                sc_merge = sc_merge.drop_duplicates(
                    subset=["_merge_name", "season"], keep="first"
                )
                # Merge name-based statcast into a temp frame
                name_merged = batting.loc[unmatched_mask, ["_merge_name", "season"]].merge(
                    sc_merge,
                    on=["_merge_name", "season"],
                    how="left",
                )
                # Fill in the unmatched rows
                for col in available_sc_cols:
                    if col in name_merged.columns:
                        batting.loc[unmatched_mask, col] = name_merged[col].values
                batting = batting.drop(columns=["_merge_name"], errors="ignore")
                name_matched = batting.loc[unmatched_mask, available_sc_cols[0]].notna().sum()
                logger.info(
                    "Name-based fallback matched %d additional rows", name_matched
                )
    else:
        # Full fallback: merge by normalized player name + season (no crosswalk at all)
        logger.info("Player ID crosswalk unavailable; merging Statcast by name+season")
        if "name" not in statcast.columns:
            logger.warning("Statcast data has no 'name' column; cannot merge")
            return batting

        batting["_merge_name"] = batting["name"].apply(_normalize_name)
        sc_merge = statcast[["name", "season"] + available_sc_cols].copy()
        sc_merge["_merge_name"] = sc_merge["name"].apply(_normalize_name)
        sc_merge = sc_merge.drop(columns=["name"])
        # Drop duplicate merge keys (keep first)
        sc_merge = sc_merge.drop_duplicates(subset=["_merge_name", "season"], keep="first")
        batting = batting.merge(
            sc_merge,
            on=["_merge_name", "season"],
            how="left",
        )
        batting = batting.drop(columns=["_merge_name"], errors="ignore")

    merged_count = batting[available_sc_cols[0]].notna().sum() if available_sc_cols else 0
    logger.info("Statcast merge: %d of %d players matched", merged_count, len(batting))

    return batting


# ---------------------------------------------------------------------------
# League average computation
# ---------------------------------------------------------------------------


def compute_league_averages(batting: pd.DataFrame, pitching: pd.DataFrame) -> dict[int, dict[str, float]]:
    """Compute league-average rates per season.

    Returns dict[season][stat_name] = league_avg_value.
    """
    averages: dict[int, dict[str, float]] = {}

    for season in batting["season"].unique():
        b = batting[batting["season"] == season]
        p = pitching[pitching["season"] == season]
        avgs: dict[str, float] = {}

        # Hitter rates (qualified: 200+ PA)
        bq = b[b["PA"] >= 200]
        if len(bq) > 0:
            avgs["wOBA"] = float(bq["wOBA"].mean()) if "wOBA" in bq.columns else 0.320
            avgs["AVG"] = float(bq["AVG"].mean()) if "AVG" in bq.columns else 0.250
            avgs["OPS"] = float(bq["OPS"].mean()) if "OPS" in bq.columns else 0.720
            avgs["K_pct_hit"] = float(bq["K_pct"].mean()) if "K_pct" in bq.columns else 22.0
            avgs["BB_pct_hit"] = float(bq["BB_pct"].mean()) if "BB_pct" in bq.columns else 8.5
            total_pa = float(bq["PA"].sum())
            avgs["HR_rate"] = float(bq["HR"].sum()) / total_pa if total_pa > 0 else 0.030
            avgs["SB_rate"] = float(bq["SB"].sum()) / total_pa if total_pa > 0 else 0.015

        # Pitcher rates (qualified: 50+ IP)
        pq = p[p["IP"] >= 50]
        if len(pq) > 0:
            avgs["ERA"] = float(pq["ERA"].mean()) if "ERA" in pq.columns else 4.20
            avgs["FIP"] = float(pq["FIP"].mean()) if "FIP" in pq.columns else 4.10
            avgs["WHIP"] = float(pq["WHIP"].mean()) if "WHIP" in pq.columns else 1.30
            avgs["K_pct_pitch"] = float(pq["K_pct"].mean()) if "K_pct" in pq.columns else 22.0
            avgs["BB_pct_pitch"] = float(pq["BB_pct"].mean()) if "BB_pct" in pq.columns else 8.0

        averages[int(season)] = avgs

    return averages


# ---------------------------------------------------------------------------
# Derived stat helpers
# ---------------------------------------------------------------------------


def add_hitter_derived_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Add HR_rate and SB_rate columns to a batting dataframe."""
    df = df.copy()
    pa = df["PA"].replace(0, np.nan)
    df["HR_rate"] = df["HR"] / pa
    df["SB_rate"] = df["SB"] / pa
    return df


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert a value to float, returning default for NaN/None."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    try:
        result = float(val)
        return default if np.isnan(result) else result
    except (TypeError, ValueError):
        return default


def get_hitter_stat(row: pd.Series, stat: str) -> float:
    """Extract a hitter stat value from a row."""
    if stat == "HR_rate":
        pa = _safe_float(row.get("PA", 0))
        return _safe_float(row.get("HR", 0)) / pa if pa > 0 else 0.0
    elif stat == "SB_rate":
        pa = _safe_float(row.get("PA", 0))
        return _safe_float(row.get("SB", 0)) / pa if pa > 0 else 0.0
    else:
        return _safe_float(row.get(stat, 0.0))


def get_pitcher_stat(row: pd.Series, stat: str) -> float:
    """Extract a pitcher stat value from a row."""
    return _safe_float(row.get(stat, 0.0))


# ---------------------------------------------------------------------------
# Projection methods
# ---------------------------------------------------------------------------


def project_current_model_hitters(
    batting: pd.DataFrame,
    test_season: int,
    checkpoint: str,
    checkpoint_pa: float,
    league_avgs: dict[int, dict[str, float]],
) -> pd.DataFrame:
    """Current model projection blend for hitters.

    Uses a multi-layer blend:
    1. Current (T-1) season stats blended with Statcast expected stats
    2. Prior-season anchoring (T-2) weighted by PA accumulated — at early
       checkpoints with small samples, prior seasons get more weight, similar
       to how the live app relies on preseason projections early on
    3. Regression toward league average

    Season weighting: season_weight = min(checkpoint_pa / 400, 0.8)
    So at 200 PA (may15) the current season gets 50%, at 400+ PA it gets 80%.
    """
    prior = batting[batting["season"] == test_season - 1].copy()
    if prior.empty:
        return pd.DataFrame()

    prior = add_hitter_derived_stats(prior)

    # Look up T-2 season for prior-season anchoring
    prior_t2 = batting[batting["season"] == test_season - 2].copy()
    if not prior_t2.empty:
        prior_t2 = add_hitter_derived_stats(prior_t2)
    # Index T-2 by fangraphs_id for quick lookup
    t2_lookup: dict[str, pd.Series] = {}
    if not prior_t2.empty:
        for _, r in prior_t2.iterrows():
            t2_lookup[str(r["fangraphs_id"])] = r

    # Season weight: how much to trust current (T-1) vs prior (T-2)
    season_weight = min(checkpoint_pa / 400.0, 0.8)

    results = []
    for _, row in prior.iterrows():
        proj: dict[str, Any] = {
            "fangraphs_id": row["fangraphs_id"],
            "name": row["name"],
        }

        has_statcast = pd.notna(row.get("xwoba")) and row.get("xwoba", 0) > 0
        trad_weight = 0.50
        stat_weight = 0.50 if has_statcast else 0.0
        total_weight = trad_weight + stat_weight

        for stat in HITTER_STATS:
            trad_val = get_hitter_stat(row, stat)

            # Statcast mapping: xwoba->wOBA, xba->AVG, xslg->SLG component of OPS
            if has_statcast:
                if stat == "wOBA":
                    stat_val = _safe_float(
                        row.get("xwoba"), trad_val
                    )
                elif stat == "AVG":
                    stat_val = _safe_float(
                        row.get("xba"), trad_val
                    )
                elif stat == "OPS":
                    xba = _safe_float(row.get("xba", 0))
                    xslg = _safe_float(row.get("xslg", 0))
                    # Approximate OPS: xOBP ≈ xBA + walk component
                    obp_val = _safe_float(row.get("OBP", 0))
                    avg_val = _safe_float(row.get("AVG", 0))
                    obp_adj = obp_val - avg_val
                    stat_val = (xba + obp_adj) + xslg
                else:
                    # K_pct, BB_pct, HR_rate, SB_rate: Statcast doesn't directly project these
                    stat_val = trad_val
            else:
                stat_val = trad_val

            current_blend = (trad_weight * trad_val + stat_weight * stat_val) / total_weight

            # Prior-season anchoring: blend current season with T-2 season
            # For stats where Statcast provides expected values, the Statcast
            # blend already serves as an anchor — only add T-2 for traditional stats
            fid = str(row["fangraphs_id"])
            if has_statcast and stat in ("wOBA", "AVG", "OPS"):
                # Statcast expected stats already provide a skill anchor;
                # use current blend directly
                proj[stat] = current_blend
            elif fid in t2_lookup:
                prior_val = get_hitter_stat(t2_lookup[fid], stat)
                proj[stat] = season_weight * current_blend + (1 - season_weight) * prior_val
            else:
                # No T-2 data: use league average as anchor (same as Marcel regression)
                prior_avgs = league_avgs.get(test_season - 2, league_avgs.get(test_season - 1, {}))
                lg_key = _hitter_lg_avg_key(stat)
                lg_avg = prior_avgs.get(lg_key, current_blend)
                proj[stat] = season_weight * current_blend + (1 - season_weight) * lg_avg

        # Apply checkpoint-based regression toward league average
        # More regression at earlier checkpoints (less data available)
        prior_avgs = league_avgs.get(test_season - 1, {})
        regression_factor = max(0.05, 1.0 - (checkpoint_pa / 600.0))

        for stat in HITTER_STATS:
            lg_key = _hitter_lg_avg_key(stat)
            lg_avg = prior_avgs.get(lg_key, proj.get(stat, 0.0))
            proj[stat] = proj[stat] * (1 - regression_factor) + lg_avg * regression_factor

        results.append(proj)

    return pd.DataFrame(results)


def _hitter_lg_avg_key(stat: str) -> str:
    """Map a hitter stat name to its league-average dict key."""
    mapping = {
        "wOBA": "wOBA",
        "HR_rate": "HR_rate",
        "K_pct": "K_pct_hit",
        "BB_pct": "BB_pct_hit",
        "SB_rate": "SB_rate",
        "AVG": "AVG",
        "OPS": "OPS",
    }
    return mapping.get(stat, stat)


def project_current_model_pitchers(
    pitching: pd.DataFrame,
    test_season: int,
    checkpoint: str,
    checkpoint_pa: float,
    league_avgs: dict[int, dict[str, float]],
) -> pd.DataFrame:
    """Current model projection blend for pitchers.

    Similar approach to hitters but using pitcher-specific stats.
    Traditional 50% + ERA estimators (FIP, xFIP, SIERA) as 50%.

    Includes prior-season anchoring: at early checkpoints with small IP,
    blend with T-2 season stats. season_weight = min(checkpoint_pa / 400, 0.8).
    """
    prior = pitching[pitching["season"] == test_season - 1].copy()
    if prior.empty:
        return pd.DataFrame()

    # Look up T-2 season for prior-season anchoring
    prior_t2 = pitching[pitching["season"] == test_season - 2].copy()
    t2_lookup: dict[str, pd.Series] = {}
    if not prior_t2.empty:
        for _, r in prior_t2.iterrows():
            t2_lookup[str(r["fangraphs_id"])] = r

    # Season weight: how much to trust current (T-1) vs prior (T-2)
    season_weight = min(checkpoint_pa / 400.0, 0.8)

    results = []
    for _, row in prior.iterrows():
        proj: dict[str, Any] = {
            "fangraphs_id": row["fangraphs_id"],
            "name": row["name"],
        }

        has_advanced = pd.notna(row.get("xFIP")) and row.get("xFIP", 0) > 0

        trad_weight = 0.50
        adv_weight = 0.50 if has_advanced else 0.0
        total_weight = trad_weight + adv_weight

        for stat in PITCHER_STATS:
            trad_val = get_pitcher_stat(row, stat)

            if has_advanced:
                if stat == "ERA":
                    # Blend ERA with FIP/xFIP/SIERA for skill-based estimate
                    fip = _safe_float(row.get("FIP"), trad_val)
                    xfip = _safe_float(row.get("xFIP"), fip)
                    siera = _safe_float(row.get("SIERA"), xfip)
                    adv_val = (fip + xfip + siera) / 3.0
                elif stat == "FIP":
                    adv_val = _safe_float(row.get("xFIP"), trad_val)
                elif stat == "WHIP":
                    # Use BB_per_9 and K_per_9 context
                    adv_val = trad_val  # No direct Statcast WHIP equivalent
                else:
                    adv_val = trad_val
            else:
                adv_val = trad_val

            current_blend = (trad_weight * trad_val + adv_weight * adv_val) / total_weight

            # Prior-season anchoring: blend current season with T-2
            # For ERA/FIP where advanced estimators already anchor skill,
            # use current blend directly when advanced stats are available
            fid = str(row["fangraphs_id"])
            if has_advanced and stat in ("ERA", "FIP"):
                proj[stat] = current_blend
            elif fid in t2_lookup:
                prior_val = get_pitcher_stat(t2_lookup[fid], stat)
                proj[stat] = season_weight * current_blend + (1 - season_weight) * prior_val
            else:
                # No T-2 data: use league average as anchor
                fallback_avgs = league_avgs.get(
                    test_season - 2, league_avgs.get(test_season - 1, {})
                )
                lg_key = _pitcher_lg_avg_key(stat)
                lg_avg = fallback_avgs.get(lg_key, current_blend)
                proj[stat] = season_weight * current_blend + (1 - season_weight) * lg_avg

        # Regression toward league average
        prior_avgs = league_avgs.get(test_season - 1, {})
        regression_factor = max(0.05, 1.0 - (checkpoint_pa / 600.0))

        for stat in PITCHER_STATS:
            lg_key = _pitcher_lg_avg_key(stat)
            lg_avg = prior_avgs.get(lg_key, proj.get(stat, 0.0))
            proj[stat] = proj[stat] * (1 - regression_factor) + lg_avg * regression_factor

        results.append(proj)

    return pd.DataFrame(results)


def _pitcher_lg_avg_key(stat: str) -> str:
    """Map a pitcher stat name to its league-average dict key."""
    mapping = {
        "ERA": "ERA",
        "FIP": "FIP",
        "K_pct": "K_pct_pitch",
        "BB_pct": "BB_pct_pitch",
        "WHIP": "WHIP",
    }
    return mapping.get(stat, stat)


def project_marcel_hitters(
    batting: pd.DataFrame,
    test_season: int,
    league_avgs: dict[int, dict[str, float]],
) -> pd.DataFrame:
    """Marcel method projection for hitters.

    Weight last 3 years: year-1 at 5x, year-2 at 4x, year-3 at 3x.
    Regress toward 1200 PA of league average.
    Age adjustment: -0.003 wOBA per year after 29, +0.001 per year before 27.
    """
    results = []

    # Collect prior seasons
    prior_seasons = {
        1: batting[batting["season"] == test_season - 1].copy(),
        2: batting[batting["season"] == test_season - 2].copy(),
        3: batting[batting["season"] == test_season - 3].copy(),
    }

    # Add derived stats
    for k in prior_seasons:
        if not prior_seasons[k].empty:
            prior_seasons[k] = add_hitter_derived_stats(prior_seasons[k])

    # Get all players who appeared in at least one prior season
    all_ids = set()
    for df in prior_seasons.values():
        if not df.empty:
            all_ids.update(df["fangraphs_id"].unique())

    # Get most recent league averages for regression target
    recent_avgs = {}
    for s in range(test_season - 1, test_season - 4, -1):
        if s in league_avgs:
            recent_avgs = league_avgs[s]
            break

    for fid in all_ids:
        weighted_stats: dict[str, float] = {}
        total_pa = 0.0
        total_weight = 0.0
        name = ""

        for years_back, weight in MARCEL_WEIGHTS.items():
            df = prior_seasons[years_back]
            if df.empty:
                continue
            player = df[df["fangraphs_id"] == fid]
            if player.empty:
                continue

            row = player.iloc[0]
            if not name:
                name = row["name"]
            pa = float(row.get("PA", 0))
            if pa == 0:
                continue

            total_pa += pa * weight
            total_weight += weight

            for stat in HITTER_STATS:
                val = get_hitter_stat(row, stat)
                weighted_stats[stat] = weighted_stats.get(stat, 0.0) + val * weight * pa

        if total_weight == 0 or total_pa == 0:
            continue

        proj: dict[str, Any] = {"fangraphs_id": fid, "name": name}

        # Weighted average
        for stat in HITTER_STATS:
            player_val = weighted_stats.get(stat, 0.0) / total_pa
            lg_avg = recent_avgs.get(_hitter_lg_avg_key(stat), player_val)

            # Regress: blend player with league average weighted by MARCEL_REGRESS_PA
            regress_weight = MARCEL_REGRESS_PA / (total_pa + MARCEL_REGRESS_PA)
            proj[stat] = player_val * (1 - regress_weight) + lg_avg * regress_weight

        # Age adjustment on wOBA (proxy for overall quality)
        # Estimate age from seasons played — rough heuristic
        # We don't have birth dates, so skip detailed age adjustment
        # but apply a mild regression toward mean for older data
        if total_weight > 0:
            staleness = sum(
                years_back * MARCEL_WEIGHTS[years_back]
                for years_back in MARCEL_WEIGHTS
                if not prior_seasons[years_back].empty
                and fid in prior_seasons[years_back]["fangraphs_id"].values
            ) / total_weight
            # Slight penalty for staleness (older data dominates)
            if staleness > 1.5:
                age_adj = -0.002 * (staleness - 1.5)
                proj["wOBA"] = proj.get("wOBA", 0.320) + age_adj

        results.append(proj)

    return pd.DataFrame(results) if results else pd.DataFrame()


def project_marcel_pitchers(
    pitching: pd.DataFrame,
    test_season: int,
    league_avgs: dict[int, dict[str, float]],
) -> pd.DataFrame:
    """Marcel method projection for pitchers."""
    results = []

    prior_seasons = {
        1: pitching[pitching["season"] == test_season - 1].copy(),
        2: pitching[pitching["season"] == test_season - 2].copy(),
        3: pitching[pitching["season"] == test_season - 3].copy(),
    }

    all_ids = set()
    for df in prior_seasons.values():
        if not df.empty:
            all_ids.update(df["fangraphs_id"].unique())

    recent_avgs = {}
    for s in range(test_season - 1, test_season - 4, -1):
        if s in league_avgs:
            recent_avgs = league_avgs[s]
            break

    for fid in all_ids:
        weighted_stats: dict[str, float] = {}
        total_ip = 0.0
        total_weight = 0.0
        name = ""

        for years_back, weight in MARCEL_WEIGHTS.items():
            df = prior_seasons[years_back]
            if df.empty:
                continue
            player = df[df["fangraphs_id"] == fid]
            if player.empty:
                continue

            row = player.iloc[0]
            if not name:
                name = row["name"]
            ip = float(row.get("IP", 0))
            if ip == 0:
                continue

            total_ip += ip * weight
            total_weight += weight

            for stat in PITCHER_STATS:
                val = get_pitcher_stat(row, stat)
                weighted_stats[stat] = weighted_stats.get(stat, 0.0) + val * weight * ip

        if total_weight == 0 or total_ip == 0:
            continue

        proj: dict[str, Any] = {"fangraphs_id": fid, "name": name}

        # Regress using IP-weighted equivalent of PA regression
        regress_ip = float(MARCEL_REGRESS_IP)
        for stat in PITCHER_STATS:
            player_val = weighted_stats.get(stat, 0.0) / total_ip
            lg_avg = recent_avgs.get(_pitcher_lg_avg_key(stat), player_val)
            regress_weight = regress_ip / (total_ip + regress_ip)
            proj[stat] = player_val * (1 - regress_weight) + lg_avg * regress_weight

        results.append(proj)

    return pd.DataFrame(results) if results else pd.DataFrame()


def project_naive_hitters(batting: pd.DataFrame, test_season: int) -> pd.DataFrame:
    """Naive last-year projection: just use prior season's stats."""
    prior = batting[batting["season"] == test_season - 1].copy()
    if prior.empty:
        return pd.DataFrame()
    prior = add_hitter_derived_stats(prior)
    return prior[["fangraphs_id", "name"] + [s for s in HITTER_STATS if s in prior.columns]].copy()


def project_naive_pitchers(pitching: pd.DataFrame, test_season: int) -> pd.DataFrame:
    """Naive last-year projection for pitchers."""
    prior = pitching[pitching["season"] == test_season - 1].copy()
    if prior.empty:
        return pd.DataFrame()
    return prior[["fangraphs_id", "name"] + [s for s in PITCHER_STATS if s in prior.columns]].copy()


def project_league_avg_hitters(
    batting: pd.DataFrame,
    test_season: int,
    league_avgs: dict[int, dict[str, float]],
) -> pd.DataFrame:
    """Project everyone at league average for each stat."""
    actual = batting[batting["season"] == test_season]
    if actual.empty:
        return pd.DataFrame()

    avgs = league_avgs.get(test_season - 1, {})
    rows = []
    for _, row in actual.iterrows():
        proj: dict[str, Any] = {"fangraphs_id": row["fangraphs_id"], "name": row["name"]}
        for stat in HITTER_STATS:
            proj[stat] = avgs.get(_hitter_lg_avg_key(stat), 0.0)
        rows.append(proj)

    return pd.DataFrame(rows)


def project_league_avg_pitchers(
    pitching: pd.DataFrame,
    test_season: int,
    league_avgs: dict[int, dict[str, float]],
) -> pd.DataFrame:
    """Project everyone at league average for each stat."""
    actual = pitching[pitching["season"] == test_season]
    if actual.empty:
        return pd.DataFrame()

    avgs = league_avgs.get(test_season - 1, {})
    rows = []
    for _, row in actual.iterrows():
        proj: dict[str, Any] = {"fangraphs_id": row["fangraphs_id"], "name": row["name"]}
        for stat in PITCHER_STATS:
            proj[stat] = avgs.get(_pitcher_lg_avg_key(stat), 0.0)
        rows.append(proj)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def compute_metrics(projected: np.ndarray, actual: np.ndarray) -> tuple[float, float, float]:
    """Compute RMSE, MAE, and R-squared.

    Args:
        projected: Array of projected values.
        actual: Array of actual values.

    Returns:
        Tuple of (RMSE, MAE, R2). Returns (nan, nan, nan) if inputs are
        empty or contain only non-finite values.
    """
    if len(projected) == 0:
        return (np.nan, np.nan, np.nan)

    # Filter out NaN/inf pairs (both must be finite to count)
    mask = np.isfinite(projected) & np.isfinite(actual)
    projected = projected[mask]
    actual = actual[mask]

    if len(projected) == 0:
        return (np.nan, np.nan, np.nan)

    residuals = projected - actual
    rmse = float(np.sqrt(np.mean(residuals**2)))
    mae = float(np.mean(np.abs(residuals)))

    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    # When all actual values are identical, R2 is undefined
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else np.nan

    return (rmse, mae, r2)


def evaluate_projections(
    proj_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    stats: list[str],
    season: int,
    checkpoint: str,
    method: str,
    player_type: str,
    results: BacktestResults,
) -> None:
    """Evaluate a set of projections against actuals and append to results.

    Args:
        proj_df: DataFrame with fangraphs_id and stat columns (projected).
        actual_df: DataFrame with fangraphs_id and stat columns (actual).
        stats: List of stat names to evaluate.
        season: Test season.
        checkpoint: Checkpoint name (may15, jul01, aug15).
        method: Projection method name.
        player_type: "hitter" or "pitcher".
        results: BacktestResults to append to.
    """
    if proj_df.empty or actual_df.empty:
        return

    # Inner join on fangraphs_id — only evaluate players in both sets
    merged = proj_df.merge(
        actual_df,
        on="fangraphs_id",
        suffixes=("_proj", "_actual"),
    )

    if merged.empty:
        return

    for stat in stats:
        proj_col = f"{stat}_proj" if f"{stat}_proj" in merged.columns else stat
        actual_col = f"{stat}_actual" if f"{stat}_actual" in merged.columns else None

        if actual_col is None or proj_col not in merged.columns or actual_col not in merged.columns:
            continue

        valid = merged[[proj_col, actual_col]].dropna()
        if valid.empty:
            continue

        projected = valid[proj_col].values.astype(float)
        actual = valid[actual_col].values.astype(float)

        rmse, mae, r2 = compute_metrics(projected, actual)

        results.summary.append(
            MetricResult(
                season=season,
                checkpoint=checkpoint,
                method=method,
                stat=stat,
                rmse=rmse,
                mae=mae,
                r2=r2,
                n_players=len(valid),
            )
        )

        # Detail rows
        name_col = "name_proj" if "name_proj" in merged.columns else "name"
        for idx in valid.index:
            results.detail.append(
                DetailRow(
                    season=season,
                    checkpoint=checkpoint,
                    method=method,
                    fangraphs_id=str(merged.loc[idx, "fangraphs_id"]),
                    name=str(merged.loc[idx, name_col]) if name_col in merged.columns else "",
                    player_type=player_type,
                    stat=stat,
                    projected=float(merged.loc[idx, proj_col]),
                    actual=float(merged.loc[idx, actual_col]),
                )
            )


# ---------------------------------------------------------------------------
# Main walk-forward loop
# ---------------------------------------------------------------------------


def run_backtest(
    batting: pd.DataFrame,
    pitching: pd.DataFrame,
    league_avgs: dict[int, dict[str, float]],
    seasons: list[int],
) -> BacktestResults:
    """Run walk-forward backtest across all seasons, checkpoints, and methods.

    Args:
        batting: Full batting dataset with Statcast columns merged.
        pitching: Full pitching dataset.
        league_avgs: Pre-computed league averages per season.
        seasons: List of test seasons.

    Returns:
        BacktestResults with summary and detail data.
    """
    results = BacktestResults()

    for test_season in seasons:
        logger.info("=" * 60)
        logger.info("Testing season %d (training on data before %d)", test_season, test_season)

        # Actual end-of-season results for the test season
        actual_bat = batting[batting["season"] == test_season].copy()
        actual_pit = pitching[pitching["season"] == test_season].copy()

        # Filter to qualified players
        actual_bat = actual_bat[actual_bat["PA"] >= 200].copy()
        actual_pit = actual_pit[actual_pit["IP"] >= 50].copy()

        if actual_bat.empty and actual_pit.empty:
            logger.warning("No qualified players for season %d, skipping", test_season)
            continue

        actual_bat = add_hitter_derived_stats(actual_bat)

        logger.info(
            "  %d qualified hitters, %d qualified pitchers",
            len(actual_bat),
            len(actual_pit),
        )

        # Training data: only seasons before test_season
        train_bat = batting[batting["season"] < test_season].copy()
        train_pit = pitching[pitching["season"] < test_season].copy()

        for cp_name, cp_pa in CHECKPOINTS.items():
            logger.info("  Checkpoint: %s (simulated ~%d PA)", cp_name, int(cp_pa))

            # --- Current Model ---
            cm_bat = project_current_model_hitters(
                train_bat, test_season, cp_name, cp_pa, league_avgs
            )
            cm_pit = project_current_model_pitchers(
                train_pit, test_season, cp_name, cp_pa, league_avgs
            )
            evaluate_projections(
                cm_bat, actual_bat, HITTER_STATS, test_season, cp_name, "current_model", "hitter", results
            )
            evaluate_projections(
                cm_pit, actual_pit, PITCHER_STATS, test_season, cp_name, "current_model", "pitcher", results
            )

            # --- Marcel ---
            marcel_bat = project_marcel_hitters(train_bat, test_season, league_avgs)
            marcel_pit = project_marcel_pitchers(train_pit, test_season, league_avgs)
            evaluate_projections(
                marcel_bat, actual_bat, HITTER_STATS, test_season, cp_name, "marcel", "hitter", results
            )
            evaluate_projections(
                marcel_pit, actual_pit, PITCHER_STATS, test_season, cp_name, "marcel", "pitcher", results
            )

            # --- Naive Last Year ---
            naive_bat = project_naive_hitters(train_bat, test_season)
            naive_pit = project_naive_pitchers(train_pit, test_season)
            evaluate_projections(
                naive_bat, actual_bat, HITTER_STATS, test_season, cp_name, "naive_last_year", "hitter", results
            )
            evaluate_projections(
                naive_pit, actual_pit, PITCHER_STATS, test_season, cp_name, "naive_last_year", "pitcher", results
            )

            # --- League Average ---
            lgavg_bat = project_league_avg_hitters(batting, test_season, league_avgs)
            lgavg_pit = project_league_avg_pitchers(pitching, test_season, league_avgs)
            evaluate_projections(
                lgavg_bat, actual_bat, HITTER_STATS, test_season, cp_name, "league_average", "hitter", results
            )
            evaluate_projections(
                lgavg_pit, actual_pit, PITCHER_STATS, test_season, cp_name, "league_average", "pitcher", results
            )

    return results


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------


def run_quality_gate(summary_df: pd.DataFrame) -> dict[str, Any]:
    """Evaluate quality gate: current model vs Marcel.

    Returns dict with pass/fail status and details.
    """
    gate: dict[str, Any] = {
        "overall_pass": False,
        "woba_improvement_pct": None,
        "era_improvement_pct": None,
        "stat_regressions": [],
        "details": [],
    }

    if summary_df.empty:
        gate["details"].append("No summary data available for quality gate evaluation.")
        return gate

    # Average RMSE across checkpoints for each (method, stat)
    avg_rmse = (
        summary_df.groupby(["method", "stat"])["rmse"]
        .mean()
        .reset_index()
        .rename(columns={"rmse": "avg_rmse"})
    )

    # Current model vs Marcel for wOBA
    cm_woba = avg_rmse[(avg_rmse["method"] == "current_model") & (avg_rmse["stat"] == "wOBA")]
    marcel_woba = avg_rmse[(avg_rmse["method"] == "marcel") & (avg_rmse["stat"] == "wOBA")]

    woba_pass = False
    if not cm_woba.empty and not marcel_woba.empty:
        cm_val = cm_woba.iloc[0]["avg_rmse"]
        marcel_val = marcel_woba.iloc[0]["avg_rmse"]
        if marcel_val > 0:
            improvement = (marcel_val - cm_val) / marcel_val * 100
            gate["woba_improvement_pct"] = round(improvement, 2)
            woba_pass = improvement >= QUALITY_GATE_IMPROVEMENT_PCT
            gate["details"].append(
                f"wOBA RMSE: Current={cm_val:.4f}, Marcel={marcel_val:.4f}, "
                f"Improvement={improvement:.1f}% {'PASS' if woba_pass else 'FAIL'}"
            )

    # Current model vs Marcel for ERA
    cm_era = avg_rmse[(avg_rmse["method"] == "current_model") & (avg_rmse["stat"] == "ERA")]
    marcel_era = avg_rmse[(avg_rmse["method"] == "marcel") & (avg_rmse["stat"] == "ERA")]

    era_pass = False
    if not cm_era.empty and not marcel_era.empty:
        cm_val = cm_era.iloc[0]["avg_rmse"]
        marcel_val = marcel_era.iloc[0]["avg_rmse"]
        if marcel_val > 0:
            improvement = (marcel_val - cm_val) / marcel_val * 100
            gate["era_improvement_pct"] = round(improvement, 2)
            era_pass = improvement >= QUALITY_GATE_IMPROVEMENT_PCT
            gate["details"].append(
                f"ERA RMSE: Current={cm_val:.4f}, Marcel={marcel_val:.4f}, "
                f"Improvement={improvement:.1f}% {'PASS' if era_pass else 'FAIL'}"
            )

    # Check no stat regresses >3% vs Marcel
    all_stats = set(avg_rmse["stat"].unique())
    regressions = []
    for stat in all_stats:
        cm_row = avg_rmse[(avg_rmse["method"] == "current_model") & (avg_rmse["stat"] == stat)]
        marcel_row = avg_rmse[(avg_rmse["method"] == "marcel") & (avg_rmse["stat"] == stat)]
        if cm_row.empty or marcel_row.empty:
            continue
        cm_val = cm_row.iloc[0]["avg_rmse"]
        marcel_val = marcel_row.iloc[0]["avg_rmse"]
        if marcel_val > 0:
            change = (cm_val - marcel_val) / marcel_val * 100
            if change > QUALITY_GATE_REGRESS_PCT:
                regressions.append(
                    {"stat": stat, "regression_pct": round(change, 2)}
                )

    gate["stat_regressions"] = regressions
    no_regressions = len(regressions) == 0

    gate["overall_pass"] = woba_pass and era_pass and no_regressions

    if regressions:
        gate["details"].append(
            f"REGRESSION WARNING: {len(regressions)} stat(s) regressed >3% vs Marcel: "
            + ", ".join(f"{r['stat']} (+{r['regression_pct']}%)" for r in regressions)
        )

    return gate


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_outputs(
    results: BacktestResults,
    quality_gate: dict[str, Any],
    output_dir: Path,
) -> None:
    """Write backtest results to CSV and JSON files.

    Args:
        results: BacktestResults with summary and detail data.
        quality_gate: Quality gate evaluation results.
        output_dir: Directory to write output files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Summary CSV
    summary_path = output_dir / "backtest_summary.csv"
    if results.summary:
        summary_df = pd.DataFrame([vars(r) for r in results.summary])
        summary_df.to_csv(summary_path, index=False, float_format="%.6f")
        logger.info("Wrote summary to %s (%d rows)", summary_path, len(summary_df))
    else:
        logger.warning("No summary results to write.")

    # Detail CSV
    detail_path = output_dir / "backtest_detail.csv"
    if results.detail:
        detail_df = pd.DataFrame([vars(r) for r in results.detail])
        detail_df.to_csv(detail_path, index=False, float_format="%.6f")
        logger.info("Wrote detail to %s (%d rows)", detail_path, len(detail_df))
    else:
        logger.warning("No detail results to write.")

    # Summary JSON with quality gate
    json_path = output_dir / "backtest_summary.json"
    json_output: dict[str, Any] = {
        "quality_gate": quality_gate,
        "methods": METHODS,
        "hitter_stats": HITTER_STATS,
        "pitcher_stats": PITCHER_STATS,
        "checkpoints": list(CHECKPOINTS.keys()),
    }

    # Aggregate RMSE by method and stat (averaged across seasons and checkpoints)
    if results.summary:
        summary_df = pd.DataFrame([vars(r) for r in results.summary])
        agg = (
            summary_df.groupby(["method", "stat"])
            .agg(
                avg_rmse=("rmse", "mean"),
                avg_mae=("mae", "mean"),
                avg_r2=("r2", "mean"),
                total_players=("n_players", "sum"),
            )
            .reset_index()
        )
        json_output["aggregated_metrics"] = agg.to_dict(orient="records")

    # Replace NaN/inf with None for valid JSON output
    def _sanitize_for_json(obj: Any) -> Any:
        if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: _sanitize_for_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize_for_json(v) for v in obj]
        return obj

    json_output = _sanitize_for_json(json_output)

    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    logger.info("Wrote JSON summary to %s", json_path)


def print_quality_gate(gate: dict[str, Any]) -> None:
    """Print quality gate results to console."""
    print("\n" + "=" * 70)
    print("QUALITY GATE RESULTS")
    print("=" * 70)

    status = "PASS" if gate["overall_pass"] else "FAIL"
    print(f"\nOverall: {status}")
    print()

    for detail in gate.get("details", []):
        print(f"  {detail}")

    if gate["stat_regressions"]:
        print("\n  Stat regressions vs Marcel:")
        for r in gate["stat_regressions"]:
            print(f"    - {r['stat']}: +{r['regression_pct']}% worse RMSE")

    print()
    if not gate["overall_pass"]:
        print("  WARNING: Phase 2 calibration should be reconsidered.")
        print("  The current model does not sufficiently outperform Marcel.")
    else:
        print("  Current model projection blend meets quality thresholds.")
    print("=" * 70)


def print_summary_table(results: BacktestResults) -> None:
    """Print a concise RMSE comparison table to console."""
    if not results.summary:
        return

    df = pd.DataFrame([vars(r) for r in results.summary])

    print("\n" + "=" * 70)
    print("RMSE COMPARISON (averaged across seasons)")
    print("=" * 70)

    agg = df.groupby(["method", "stat"])["rmse"].mean().reset_index()
    pivot = agg.pivot(index="stat", columns="method", values="rmse")

    # Reorder columns
    col_order = [c for c in METHODS if c in pivot.columns]
    pivot = pivot[col_order]

    print("\n" + pivot.to_string(float_format="{:.4f}".format))
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Walk-forward backtesting harness for fantasy baseball projections.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s --seasons 2021-2024
  %(prog)s --db-path /path/to/backtest_data.sqlite --output-dir /path/to/results
        """,
    )
    parser.add_argument(
        "--seasons",
        type=str,
        default="2019-2025",
        help="Season range to test, e.g. '2019-2025' (default: %(default)s)",
    )
    project_root = Path(__file__).resolve().parent.parent
    default_db = str(project_root / "backtest_data.sqlite")
    parser.add_argument(
        "--db-path",
        type=str,
        default=default_db,
        help="Path to backtest_data.sqlite (default: %(default)s)",
    )
    default_output = str(project_root / "data" / "results")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=default_output,
        help="Directory for output files (default: %(default)s)",
    )
    return parser.parse_args(argv)


def parse_season_range(season_str: str) -> list[int]:
    """Parse a season range string like '2019-2025' into a list of ints."""
    parts = season_str.split("-")
    if len(parts) == 2:
        start, end = int(parts[0]), int(parts[1])
        return list(range(start, end + 1))
    elif len(parts) == 1:
        return [int(parts[0])]
    else:
        raise ValueError(f"Invalid season range: {season_str}")


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the backtest harness.

    Args:
        argv: Command-line arguments (None for sys.argv).

    Returns:
        Exit code: 0 for PASS, 1 for FAIL.
    """
    args = parse_args(argv)
    seasons = parse_season_range(args.seasons)
    output_dir = Path(args.output_dir)
    db_path = args.db_path

    logger.info("Backtest harness starting")
    logger.info("  Seasons: %s", seasons)
    logger.info("  Database: %s", db_path)
    logger.info("  Output: %s", output_dir)

    # Load data
    try:
        batting, pitching, statcast, player_ids = load_data(db_path)
    except (FileNotFoundError, sqlite3.Error) as e:
        logger.error("%s", e)
        return 1

    # Merge Statcast onto batting
    batting = merge_statcast_to_batting(batting, statcast, player_ids)

    # Compute league averages
    league_avgs = compute_league_averages(batting, pitching)
    logger.info("Computed league averages for %d seasons", len(league_avgs))

    # Run walk-forward backtest
    results = run_backtest(batting, pitching, league_avgs, seasons)

    logger.info(
        "Backtest complete: %d summary rows, %d detail rows",
        len(results.summary),
        len(results.detail),
    )

    # Quality gate
    summary_df = pd.DataFrame([vars(r) for r in results.summary]) if results.summary else pd.DataFrame()
    quality_gate = run_quality_gate(summary_df)

    # Output
    write_outputs(results, quality_gate, output_dir)
    print_summary_table(results)
    print_quality_gate(quality_gate)

    return 0 if quality_gate["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
