#!/usr/bin/env python3
"""Automated parameter tuning for the projection engine.

Uses scipy.optimize (Nelder-Mead) to find optimal blend weights and thresholds
by minimizing projection RMSE against historical end-of-season outcomes.

Walk-forward validation: for each test season, uses only prior-season data as
the "prior" and simulates partial-season checkpoints (200/350/450 PA for hitters,
50/100/140 IP for pitchers) blended with that prior to predict end-of-season stats.

WARNING: Results from validation mode are tested against historical data only.
Do NOT apply optimized parameters to production until April 30, 2026, when
enough 2026 in-season projection_log data exists for live validation.

Usage:
    uv run python -m scripts.optimize_parameters
    uv run python -m scripts.optimize_parameters --mode validation --seasons 2024,2025
    uv run python -m scripts.optimize_parameters --max-iter 1000
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sqlalchemy as sa
from scipy.optimize import minimize

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKTEST_DB = PROJECT_ROOT / "backtest_data.sqlite"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "optimization"

logger = logging.getLogger("optimize_parameters")

# ---------------------------------------------------------------------------
# Current production parameter values (baseline)
# ---------------------------------------------------------------------------

CURRENT_PARAMS: dict[str, float] = {
    "w_full_season_trad": 0.25,
    "w_last_30_trad": 0.15,
    "w_last_14_trad": 0.10,
    "w_full_season_statcast": 0.30,
    "w_last_30_statcast": 0.20,
    "phase1_dampening": 0.50,
    "phase2_dampening": 0.35,
    "signal_threshold": 0.030,
}

# Parameter names in optimization vector order
PARAM_NAMES: list[str] = list(CURRENT_PARAMS.keys())

# Indices for weight groups that must sum to 1.0
BLEND_WEIGHT_INDICES: list[int] = [0, 1, 2, 3, 4]  # first 5 params

# Bounds for each parameter
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "w_full_season_trad": (0.05, 1.0),
    "w_last_30_trad": (0.05, 1.0),
    "w_last_14_trad": (0.05, 1.0),
    "w_full_season_statcast": (0.05, 1.0),
    "w_last_30_statcast": (0.05, 1.0),
    "phase1_dampening": (0.20, 0.80),
    "phase2_dampening": (0.20, 0.80),
    "signal_threshold": (0.010, 0.060),
}

# Hitter PA checkpoints for walk-forward evaluation
HITTER_PA_CHECKPOINTS: list[int] = [200, 350, 450]

# Pitcher IP checkpoints for walk-forward evaluation
PITCHER_IP_CHECKPOINTS: list[float] = [50.0, 100.0, 140.0]

# Minimum PA/IP for a player to be included in the test set
MIN_PA_FULL_SEASON: int = 400
MIN_IP_FULL_SEASON: float = 80.0

# Objective function weighting
HITTER_WEIGHT: float = 0.6
PITCHER_WEIGHT: float = 0.4


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _get_engine(db_path: Path) -> sa.engine.Engine:
    """Create a synchronous SQLAlchemy engine."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    return sa.create_engine(f"sqlite:///{db_path}", echo=False)


def _load_batting(engine: sa.engine.Engine, seasons: list[int]) -> pd.DataFrame:
    """Load batting_season rows for the requested seasons."""
    query = sa.text(
        "SELECT * FROM batting_season WHERE season IN :seasons AND PA IS NOT NULL"
    ).bindparams(sa.bindparam("seasons", expanding=True))
    with engine.connect() as conn:
        df = pd.read_sql_query(query, conn, params={"seasons": seasons})
    logger.info("Loaded %d batting rows for seasons %s", len(df), seasons)
    return df


def _load_pitching(engine: sa.engine.Engine, seasons: list[int]) -> pd.DataFrame:
    """Load pitching_season rows for the requested seasons."""
    query = sa.text(
        "SELECT * FROM pitching_season WHERE season IN :seasons AND IP IS NOT NULL"
    ).bindparams(sa.bindparam("seasons", expanding=True))
    with engine.connect() as conn:
        df = pd.read_sql_query(query, conn, params={"seasons": seasons})
    logger.info("Loaded %d pitching rows for seasons %s", len(df), seasons)
    return df


def _load_statcast(engine: sa.engine.Engine, seasons: list[int]) -> pd.DataFrame:
    """Load statcast_season rows for the requested seasons."""
    query = sa.text("SELECT * FROM statcast_season WHERE season IN :seasons").bindparams(
        sa.bindparam("seasons", expanding=True)
    )
    with engine.connect() as conn:
        df = pd.read_sql_query(query, conn, params={"seasons": seasons})
    logger.info("Loaded %d statcast rows for seasons %s", len(df), seasons)
    return df


def _load_player_ids(engine: sa.engine.Engine, db_path: Path) -> pd.DataFrame:
    """Load the player_ids cross-reference table with fallback logic.

    Tries three sources in order:
      1. player_ids table in backtest_data.sqlite
      2. players table in fantasy_baseball.db (live app DB)
      3. Returns empty DataFrame (merge will use name-based fallback)
    """
    import sqlite3

    with engine.connect() as conn:
        df = pd.read_sql_query(sa.text("SELECT * FROM player_ids"), conn)
    logger.info("Loaded %d player ID mappings from backtest DB", len(df))

    # Fallback: if player_ids crosswalk is empty, try the live app's DB
    if df.empty or len(df) == 0:
        live_db_path = db_path.parent / "fantasy_baseball.db"
        if live_db_path.exists():
            logger.info(
                "Player ID crosswalk empty; falling back to live DB at %s",
                live_db_path,
            )
            try:
                with sqlite3.connect(str(live_db_path)) as live_conn:
                    df = pd.read_sql(
                        "SELECT fangraphs_id, mlbam_id FROM players "
                        "WHERE fangraphs_id IS NOT NULL AND mlbam_id IS NOT NULL",
                        live_conn,
                    )
                logger.info(
                    "Loaded %d player ID mappings from live DB fallback",
                    len(df),
                )
            except Exception as e:
                logger.warning("Failed to load IDs from live DB: %s", e)
        else:
            logger.warning(
                "No live DB found at %s; Statcast merge will use name-based fallback",
                live_db_path,
            )

    return df


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------


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


def _merge_statcast_to_batting(
    batting: pd.DataFrame,
    statcast: pd.DataFrame,
    id_map: pd.DataFrame,
) -> pd.DataFrame:
    """Join Statcast expected stats onto batting rows.

    Uses a three-tier merge strategy:
      1. ID-based crosswalk (fangraphs_id -> mlbam_id) when id_map is available
      2. Name-based fallback for rows unmatched by ID
      3. Pure name-based merge when no crosswalk is available

    Returns batting DataFrame with additional columns: xba, xslg, xwoba.
    """
    batting = batting.copy()
    batting["fangraphs_id"] = batting["fangraphs_id"].astype(str)

    if statcast.empty:
        logger.warning("Statcast data is empty; skipping Statcast merge")
        return batting

    statcast = statcast.copy()
    statcast_cols = ["xba", "xslg", "xwoba"]
    available_sc_cols = [c for c in statcast_cols if c in statcast.columns]

    if not available_sc_cols:
        logger.warning("No expected stat columns found in statcast data")
        return batting

    if not id_map.empty:
        # Preferred: merge via crosswalk (fangraphs_id -> mlbam_id -> statcast)
        xref = (
            id_map[["fangraphs_id", "mlbam_id"]]
            .dropna()
            .drop_duplicates(subset=["fangraphs_id"], keep="first")
        )
        xref["fangraphs_id"] = xref["fangraphs_id"].astype(str)
        xref["mlbam_id"] = xref["mlbam_id"].astype(str)
        batting = batting.merge(xref, on="fangraphs_id", how="left")

        statcast["mlbam_id"] = statcast["mlbam_id"].astype(str)
        batting = batting.merge(
            statcast[["mlbam_id", "season"] + available_sc_cols],
            on=["mlbam_id", "season"],
            how="left",
        )

        # Second fallback: for rows that didn't match via ID, try name-based merge
        if "name" in statcast.columns and "name" in batting.columns:
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
                sc_merge = sc_merge.drop_duplicates(subset=["_merge_name", "season"], keep="first")
                name_merged = batting.loc[unmatched_mask, ["_merge_name", "season"]].merge(
                    sc_merge,
                    on=["_merge_name", "season"],
                    how="left",
                )
                for col in available_sc_cols:
                    if col in name_merged.columns:
                        batting.loc[unmatched_mask, col] = name_merged[col].values
                batting = batting.drop(columns=["_merge_name"], errors="ignore")
                name_matched = batting.loc[unmatched_mask, available_sc_cols[0]].notna().sum()
                logger.info("Name-based fallback matched %d additional rows", name_matched)
    else:
        # Full fallback: merge by normalized player name + season (no crosswalk)
        logger.info("Player ID crosswalk unavailable; merging Statcast by name+season")
        if "name" not in statcast.columns or "name" not in batting.columns:
            logger.warning("No 'name' column in statcast/batting data; cannot merge")
            return batting

        batting["_merge_name"] = batting["name"].apply(_normalize_name)
        sc_merge = statcast[["name", "season"] + available_sc_cols].copy()
        sc_merge["_merge_name"] = sc_merge["name"].apply(_normalize_name)
        sc_merge = sc_merge.drop(columns=["name"])
        sc_merge = sc_merge.drop_duplicates(subset=["_merge_name", "season"], keep="first")
        batting = batting.merge(
            sc_merge,
            on=["_merge_name", "season"],
            how="left",
        )
        batting = batting.drop(columns=["_merge_name"], errors="ignore")

    merged_count = batting[available_sc_cols[0]].notna().sum()
    logger.info("Statcast merge: %d of %d players matched", merged_count, len(batting))

    return batting


# ---------------------------------------------------------------------------
# Parameter vector <-> dict conversion
# ---------------------------------------------------------------------------


def params_to_vector(params: dict[str, float]) -> np.ndarray:
    """Convert parameter dict to numpy vector in canonical order."""
    return np.array([params[name] for name in PARAM_NAMES])


def vector_to_params(x: np.ndarray) -> dict[str, float]:
    """Convert numpy vector back to parameter dict, enforcing constraints."""
    params = {name: float(x[i]) for i, name in enumerate(PARAM_NAMES)}

    # Enforce minimum bounds
    for name, (lo, hi) in PARAM_BOUNDS.items():
        params[name] = max(lo, min(hi, params[name]))

    # Normalize blend weights to sum to 1.0
    weight_names = [PARAM_NAMES[i] for i in BLEND_WEIGHT_INDICES]
    weight_sum = sum(params[n] for n in weight_names)
    if weight_sum > 0:
        for n in weight_names:
            params[n] = params[n] / weight_sum
    else:
        # Fallback: equal weights
        for n in weight_names:
            params[n] = 1.0 / len(weight_names)

    # Re-enforce minimums after normalization (and re-normalize if needed)
    for n in weight_names:
        if params[n] < 0.05:
            params[n] = 0.05
    weight_sum = sum(params[n] for n in weight_names)
    for n in weight_names:
        params[n] = params[n] / weight_sum

    return params


def _enforce_max_change(
    candidate: dict[str, float],
    baseline: dict[str, float],
    max_pct: float = 0.20,
) -> dict[str, float]:
    """Clamp each parameter to within max_pct of the baseline value."""
    clamped = {}
    for name in PARAM_NAMES:
        base = baseline[name]
        lo = base * (1.0 - max_pct)
        hi = base * (1.0 + max_pct)
        # For very small base values, use absolute range
        abs_lo, abs_hi = PARAM_BOUNDS[name]
        lo = max(lo, abs_lo)
        hi = min(hi, abs_hi)
        clamped[name] = max(lo, min(hi, candidate[name]))
    return clamped


# ---------------------------------------------------------------------------
# Projection simulation (walk-forward)
# ---------------------------------------------------------------------------


def _simulate_hitter_woba(
    prior_woba: float | None,
    prior_xwoba: float | None,
    checkpoint_woba: float,
    checkpoint_xwoba: float | None,
    params: dict[str, float],
    checkpoint_pa: int,
) -> float:
    """Simulate a projected end-of-season wOBA for a hitter at a given checkpoint.

    Blends prior-season data with current partial-season data using candidate weights.

    The idea: at checkpoint_pa into the season, we have partial traditional stats
    and partial Statcast stats. We blend them with prior-season data to form a
    projection. The blend weights being optimized determine how much to weight
    each data source.

    For simplicity in walk-forward:
      - "full_season_trad" weight -> applied to prior-season wOBA
      - "last_30_trad" weight -> applied to partial-season wOBA (recent proxy)
      - "last_14_trad" weight -> applied to partial-season wOBA (more recent proxy,
        with small noise to distinguish from last_30)
      - "full_season_statcast" weight -> applied to prior-season xwOBA
      - "last_30_statcast" weight -> applied to partial-season xwOBA
    """
    components: list[tuple[float | None, float]] = [
        (prior_woba, params["w_full_season_trad"]),
        (checkpoint_woba, params["w_last_30_trad"]),
        (checkpoint_woba, params["w_last_14_trad"]),
        (prior_xwoba, params["w_full_season_statcast"]),
        (checkpoint_xwoba, params["w_last_30_statcast"]),
    ]

    valid = [(v, w) for v, w in components if v is not None]
    if not valid:
        return checkpoint_woba  # fallback
    total_w = sum(w for _, w in valid)
    if total_w == 0:
        return checkpoint_woba
    return sum(v * w for v, w in valid) / total_w


def _simulate_pitcher_era(
    prior_era: float | None,
    prior_fip: float | None,
    prior_xfip: float | None,
    checkpoint_era: float,
    checkpoint_fip: float | None,
    params: dict[str, float],
    checkpoint_ip: float,
) -> float:
    """Simulate a projected end-of-season ERA for a pitcher at a given checkpoint.

    Blends prior-season ERA/FIP/xFIP with partial-season data.
    """
    # Use FIP/xFIP as Statcast-like predictive metrics for pitchers
    components: list[tuple[float | None, float]] = [
        (prior_era, params["w_full_season_trad"]),
        (checkpoint_era, params["w_last_30_trad"]),
        (checkpoint_era, params["w_last_14_trad"]),
        (prior_fip, params["w_full_season_statcast"]),
        (checkpoint_fip if checkpoint_fip else prior_xfip, params["w_last_30_statcast"]),
    ]

    valid = [(v, w) for v, w in components if v is not None]
    if not valid:
        return checkpoint_era
    total_w = sum(w for _, w in valid)
    if total_w == 0:
        return checkpoint_era
    return sum(v * w for v, w in valid) / total_w


def _compute_hitter_rmse(
    batting: pd.DataFrame,
    test_seasons: list[int],
    params: dict[str, float],
) -> tuple[float, int]:
    """Compute hitter wOBA projection RMSE across test seasons and checkpoints.

    Walk-forward: for each test season, uses the prior season as the "prior".
    At each PA checkpoint, simulates a blended projection and compares to
    actual end-of-season wOBA.

    Returns (RMSE, player_checkpoint_count).
    """
    errors: list[float] = []

    for season in test_seasons:
        prior_season = season - 1

        # Full-season actuals for this season (the "truth")
        actuals = batting[
            (batting["season"] == season) & (batting["PA"] >= MIN_PA_FULL_SEASON)
        ].copy()
        if actuals.empty:
            continue

        # Prior-season data
        priors = batting[batting["season"] == prior_season].copy()
        if priors.empty:
            continue

        # Build prior lookups by fangraphs_id
        prior_woba_map: dict[str, float] = {}
        prior_xwoba_map: dict[str, float] = {}
        for _, row in priors.iterrows():
            fid = str(row["fangraphs_id"])
            if pd.notna(row.get("wOBA")):
                prior_woba_map[fid] = float(row["wOBA"])
            if pd.notna(row.get("xwoba")):
                prior_xwoba_map[fid] = float(row["xwoba"])

        for _, player in actuals.iterrows():
            fid = str(player["fangraphs_id"])
            actual_woba = player.get("wOBA")
            if pd.isna(actual_woba) or actual_woba is None:
                continue
            actual_woba = float(actual_woba)

            total_pa = int(player["PA"])
            prior_woba = prior_woba_map.get(fid)
            prior_xwoba = prior_xwoba_map.get(fid)

            # Need at least prior data to make a projection
            if prior_woba is None:
                continue

            for cp_pa in HITTER_PA_CHECKPOINTS:
                if cp_pa >= total_pa:
                    continue  # Can't simulate a checkpoint beyond actual PA

                # Simulate partial-season wOBA at this checkpoint.
                # We approximate checkpoint wOBA by interpolating between
                # prior and actual with noise proportional to sample size.
                # This simulates the "partial season stats" the model would see.
                progress = cp_pa / total_pa
                # At checkpoint, observed wOBA is a noisy version of the truth
                # weighted toward prior early in the season
                checkpoint_woba = prior_woba * (1 - progress) + actual_woba * progress

                # Checkpoint xwOBA (if available)
                checkpoint_xwoba: float | None = None
                if prior_xwoba is not None:
                    actual_xwoba = player.get("xwoba")
                    if pd.notna(actual_xwoba):
                        checkpoint_xwoba = (
                            prior_xwoba * (1 - progress) + float(actual_xwoba) * progress
                        )

                projected = _simulate_hitter_woba(
                    prior_woba=prior_woba,
                    prior_xwoba=prior_xwoba,
                    checkpoint_woba=checkpoint_woba,
                    checkpoint_xwoba=checkpoint_xwoba,
                    params=params,
                    checkpoint_pa=cp_pa,
                )

                errors.append((projected - actual_woba) ** 2)

    if not errors:
        return 1.0, 0  # penalize if no data
    rmse = float(np.sqrt(np.mean(errors)))
    return rmse, len(errors)


def _compute_pitcher_rmse(
    pitching: pd.DataFrame,
    test_seasons: list[int],
    params: dict[str, float],
) -> tuple[float, int]:
    """Compute pitcher ERA projection RMSE across test seasons and checkpoints.

    Returns (RMSE, player_checkpoint_count).
    """
    errors: list[float] = []

    for season in test_seasons:
        prior_season = season - 1

        actuals = pitching[
            (pitching["season"] == season) & (pitching["IP"] >= MIN_IP_FULL_SEASON)
        ].copy()
        if actuals.empty:
            continue

        priors = pitching[pitching["season"] == prior_season].copy()
        if priors.empty:
            continue

        prior_era_map: dict[str, float] = {}
        prior_fip_map: dict[str, float] = {}
        prior_xfip_map: dict[str, float] = {}
        for _, row in priors.iterrows():
            fid = str(row["fangraphs_id"])
            if pd.notna(row.get("ERA")):
                prior_era_map[fid] = float(row["ERA"])
            if pd.notna(row.get("FIP")):
                prior_fip_map[fid] = float(row["FIP"])
            if pd.notna(row.get("xFIP")):
                prior_xfip_map[fid] = float(row["xFIP"])

        for _, player in actuals.iterrows():
            fid = str(player["fangraphs_id"])
            actual_era = player.get("ERA")
            if pd.isna(actual_era) or actual_era is None:
                continue
            actual_era = float(actual_era)

            total_ip = float(player["IP"])
            prior_era = prior_era_map.get(fid)
            prior_fip = prior_fip_map.get(fid)
            prior_xfip = prior_xfip_map.get(fid)

            if prior_era is None:
                continue

            for cp_ip in PITCHER_IP_CHECKPOINTS:
                if cp_ip >= total_ip:
                    continue

                progress = cp_ip / total_ip
                checkpoint_era = prior_era * (1 - progress) + actual_era * progress

                checkpoint_fip: float | None = None
                actual_fip = player.get("FIP")
                if prior_fip is not None and pd.notna(actual_fip):
                    checkpoint_fip = prior_fip * (1 - progress) + float(actual_fip) * progress

                projected = _simulate_pitcher_era(
                    prior_era=prior_era,
                    prior_fip=prior_fip,
                    prior_xfip=prior_xfip,
                    checkpoint_era=checkpoint_era,
                    checkpoint_fip=checkpoint_fip,
                    params=params,
                    checkpoint_ip=cp_ip,
                )

                errors.append((projected - actual_era) ** 2)

    if not errors:
        return 1.0, 0
    rmse = float(np.sqrt(np.mean(errors)))
    return rmse, len(errors)


# ---------------------------------------------------------------------------
# Objective function
# ---------------------------------------------------------------------------


class ObjectiveTracker:
    """Tracks optimization progress and logs periodically."""

    def __init__(
        self,
        batting: pd.DataFrame,
        pitching: pd.DataFrame,
        test_seasons: list[int],
        log_every: int = 50,
    ) -> None:
        self.batting = batting
        self.pitching = pitching
        self.test_seasons = test_seasons
        self.log_every = log_every
        self.iteration = 0
        self.best_value = float("inf")
        self.best_params: dict[str, float] | None = None

    def __call__(self, x: np.ndarray) -> float:
        """Evaluate the objective function for a candidate parameter vector."""
        self.iteration += 1

        # Decode and constrain parameters
        params = vector_to_params(x)
        params = _enforce_max_change(params, CURRENT_PARAMS)

        # Compute RMSE for hitters and pitchers
        hitter_rmse, hitter_n = _compute_hitter_rmse(self.batting, self.test_seasons, params)
        pitcher_rmse, pitcher_n = _compute_pitcher_rmse(self.pitching, self.test_seasons, params)

        # Combined objective
        combined = hitter_rmse * HITTER_WEIGHT + pitcher_rmse * PITCHER_WEIGHT

        # Track best
        if combined < self.best_value:
            self.best_value = combined
            self.best_params = params.copy()

        # Periodic logging
        if self.iteration % self.log_every == 0:
            logger.info(
                "Iteration %d: combined=%.6f (hitter_wOBA=%.4f [n=%d], "
                "pitcher_ERA=%.4f [n=%d]) | best=%.6f",
                self.iteration,
                combined,
                hitter_rmse,
                hitter_n,
                pitcher_rmse,
                pitcher_n,
                self.best_value,
            )
            # Log current best parameters
            if self.best_params:
                param_str = ", ".join(f"{k}={v:.4f}" for k, v in self.best_params.items())
                logger.info("  Best params: %s", param_str)

        return combined


# ---------------------------------------------------------------------------
# Validation mode runner
# ---------------------------------------------------------------------------


def run_validation_mode(
    db_path: Path,
    test_seasons: list[int],
    max_iter: int,
) -> dict[str, Any]:
    """Run walk-forward parameter optimization against historical data.

    Args:
        db_path: Path to backtest_data.sqlite.
        test_seasons: Seasons to test against (need prior season data too).
        max_iter: Maximum Nelder-Mead iterations.

    Returns:
        Optimization result dictionary.
    """
    logger.info("=" * 70)
    logger.info("VALIDATION MODE — Testing against historical data")
    logger.info("WARNING: Results are NOT for production use until April 30, 2026.")
    logger.info("=" * 70)

    engine = _get_engine(db_path)

    # Determine all seasons we need (test seasons + their priors)
    all_seasons = sorted(set(test_seasons) | {s - 1 for s in test_seasons})
    logger.info("Loading data for seasons: %s", all_seasons)

    batting = _load_batting(engine, all_seasons)
    pitching = _load_pitching(engine, all_seasons)
    statcast = _load_statcast(engine, all_seasons)
    id_map = _load_player_ids(engine, db_path)

    # Merge Statcast xwOBA onto batting for hitter projections
    batting = _merge_statcast_to_batting(batting, statcast, id_map)

    # Count qualified players in test seasons
    hitter_count = len(
        batting[(batting["season"].isin(test_seasons)) & (batting["PA"] >= MIN_PA_FULL_SEASON)][
            "fangraphs_id"
        ].unique()
    )
    pitcher_count = len(
        pitching[(pitching["season"].isin(test_seasons)) & (pitching["IP"] >= MIN_IP_FULL_SEASON)][
            "fangraphs_id"
        ].unique()
    )
    logger.info(
        "Qualified players in test seasons: %d hitters, %d pitchers",
        hitter_count,
        pitcher_count,
    )

    # Evaluate current parameters as baseline
    logger.info("Evaluating current (baseline) parameters...")
    current_hitter_rmse, _ = _compute_hitter_rmse(batting, test_seasons, CURRENT_PARAMS)
    current_pitcher_rmse, _ = _compute_pitcher_rmse(pitching, test_seasons, CURRENT_PARAMS)
    current_combined = current_hitter_rmse * HITTER_WEIGHT + current_pitcher_rmse * PITCHER_WEIGHT
    logger.info(
        "Baseline RMSE: hitter_wOBA=%.6f, pitcher_ERA=%.4f, combined=%.6f",
        current_hitter_rmse,
        current_pitcher_rmse,
        current_combined,
    )

    # Set up optimizer
    objective = ObjectiveTracker(
        batting=batting,
        pitching=pitching,
        test_seasons=test_seasons,
        log_every=50,
    )

    x0 = params_to_vector(CURRENT_PARAMS)

    logger.info("Starting Nelder-Mead optimization (max_iter=%d)...", max_iter)
    start_time = time.time()

    result = minimize(
        objective,
        x0,
        method="Nelder-Mead",
        options={
            "maxiter": max_iter,
            "maxfev": max_iter * 2,
            "xatol": 1e-6,
            "fatol": 1e-8,
            "adaptive": True,
        },
    )

    elapsed = time.time() - start_time
    logger.info(
        "Optimization complete in %.1f seconds (%d iterations, %d function evals)",
        elapsed,
        result.nit,
        result.nfev,
    )

    # Extract and constrain optimized parameters
    optimized_params = vector_to_params(result.x)
    optimized_params = _enforce_max_change(optimized_params, CURRENT_PARAMS)

    # Re-evaluate optimized parameters to get clean RMSE values
    opt_hitter_rmse, hitter_n = _compute_hitter_rmse(batting, test_seasons, optimized_params)
    opt_pitcher_rmse, pitcher_n = _compute_pitcher_rmse(pitching, test_seasons, optimized_params)
    opt_combined = opt_hitter_rmse * HITTER_WEIGHT + opt_pitcher_rmse * PITCHER_WEIGHT

    # Compute improvement percentages
    def _pct_change(old: float, new: float) -> float:
        if old == 0:
            return 0.0
        return round((old - new) / old * 100, 2)

    # Build per-parameter change report
    per_param_changes: dict[str, dict[str, float]] = {}
    for name in PARAM_NAMES:
        current_val = CURRENT_PARAMS[name]
        opt_val = optimized_params[name]
        change_pct = (
            round((opt_val - current_val) / current_val * 100, 2) if current_val != 0 else 0.0
        )
        per_param_changes[name] = {
            "current": round(current_val, 6),
            "optimized": round(opt_val, 6),
            "change_pct": change_pct,
        }

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "validation",
        "WARNING": (
            "VALIDATION ONLY — Results tested against historical data. "
            "NOT for production use until April 30, 2026."
        ),
        "seasons_analyzed": test_seasons,
        "player_count": {
            "hitters": hitter_count,
            "pitchers": pitcher_count,
        },
        "current_params": {k: round(v, 6) for k, v in CURRENT_PARAMS.items()},
        "optimized_params": {k: round(v, 6) for k, v in optimized_params.items()},
        "current_rmse": {
            "hitter_woba": round(current_hitter_rmse, 6),
            "pitcher_era": round(current_pitcher_rmse, 4),
            "combined": round(current_combined, 6),
        },
        "optimized_rmse": {
            "hitter_woba": round(opt_hitter_rmse, 6),
            "pitcher_era": round(opt_pitcher_rmse, 4),
            "combined": round(opt_combined, 6),
        },
        "improvement_pct": {
            "hitter_woba": _pct_change(current_hitter_rmse, opt_hitter_rmse),
            "pitcher_era": _pct_change(current_pitcher_rmse, opt_pitcher_rmse),
            "combined": _pct_change(current_combined, opt_combined),
        },
        "per_param_changes": per_param_changes,
        "convergence": {
            "success": bool(result.success),
            "message": result.message,
            "iterations": int(result.nit),
            "function_evaluations": int(result.nfev),
            "final_rmse": round(opt_combined, 6),
            "elapsed_seconds": round(elapsed, 1),
        },
        "evaluation_details": {
            "hitter_pa_checkpoints": HITTER_PA_CHECKPOINTS,
            "pitcher_ip_checkpoints": PITCHER_IP_CHECKPOINTS,
            "min_pa_full_season": MIN_PA_FULL_SEASON,
            "min_ip_full_season": MIN_IP_FULL_SEASON,
            "hitter_weight_in_objective": HITTER_WEIGHT,
            "pitcher_weight_in_objective": PITCHER_WEIGHT,
            "hitter_checkpoint_count": hitter_n,
            "pitcher_checkpoint_count": pitcher_n,
        },
    }

    return report


# ---------------------------------------------------------------------------
# Production mode stub
# ---------------------------------------------------------------------------


def run_production_mode(db_path: Path) -> dict:
    """Load projection_log from app database and optimize against actual weekly points.

    ENABLED AFTER APRIL 30, 2026 ONLY.
    """
    today = date.today()
    if today < date(2026, 4, 30):
        raise RuntimeError(
            "Production mode is not available until April 30, 2026. "
            "Use --mode validation to test against historical data."
        )
    # TODO: Implementation when projection_log data is available.
    # Steps:
    #   1. Load projection_log entries from fantasy_baseball.db
    #   2. Load actual weekly fantasy point outcomes
    #   3. Build objective: RMSE between projected and actual weekly points
    #   4. Run Nelder-Mead optimization with same constraints
    #   5. Return report in same format as validation mode
    raise NotImplementedError(
        "Production mode will be implemented when projection_log data is available."
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _save_report(report: dict[str, Any], output_dir: Path) -> Path:
    """Save the optimization report as JSON and return the file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"tuning_{timestamp}.json"
    filepath = output_dir / filename

    with open(filepath, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info("Report saved to %s", filepath)
    return filepath


def _print_summary(report: dict[str, Any]) -> None:
    """Print a formatted summary of the optimization results to console."""
    mode = report["mode"]
    warning = report.get("WARNING", "")

    print("\n" + "=" * 70)
    print(f"  PARAMETER OPTIMIZATION RESULTS — {mode.upper()} MODE")
    print("=" * 70)

    if warning:
        print(f"\n  *** {warning} ***\n")

    print(f"  Seasons analyzed: {report['seasons_analyzed']}")
    pc = report["player_count"]
    print(f"  Players: {pc['hitters']} hitters, {pc['pitchers']} pitchers")

    print("\n  --- RMSE Comparison ---")
    curr = report["current_rmse"]
    opt = report["optimized_rmse"]
    imp = report["improvement_pct"]
    print(f"  {'Metric':<20} {'Current':>10} {'Optimized':>10} {'Improvement':>12}")
    print(f"  {'-' * 52}")
    print(
        f"  {'Hitter wOBA':<20} {curr['hitter_woba']:>10.6f} "
        f"{opt['hitter_woba']:>10.6f} {imp['hitter_woba']:>+11.2f}%"
    )
    print(
        f"  {'Pitcher ERA':<20} {curr['pitcher_era']:>10.4f} "
        f"{opt['pitcher_era']:>10.4f} {imp['pitcher_era']:>+11.2f}%"
    )
    print(
        f"  {'Combined':<20} {curr['combined']:>10.6f} "
        f"{opt['combined']:>10.6f} {imp['combined']:>+11.2f}%"
    )

    print("\n  --- Parameter Changes ---")
    print(f"  {'Parameter':<28} {'Current':>10} {'Optimized':>10} {'Change':>10}")
    print(f"  {'-' * 58}")
    for name, changes in report["per_param_changes"].items():
        print(
            f"  {name:<28} {changes['current']:>10.4f} "
            f"{changes['optimized']:>10.4f} {changes['change_pct']:>+9.1f}%"
        )

    conv = report["convergence"]
    print("\n  --- Convergence ---")
    print(f"  Success: {conv['success']}")
    print(f"  Message: {conv['message']}")
    print(f"  Iterations: {conv['iterations']}")
    print(f"  Function evaluations: {conv['function_evaluations']}")
    print(f"  Elapsed: {conv['elapsed_seconds']}s")

    print("\n" + "=" * 70)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Automated parameter tuning for the fantasy baseball projection engine. "
            "Uses scipy.optimize (Nelder-Mead) to find optimal blend weights and "
            "thresholds by minimizing projection RMSE against historical outcomes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python -m scripts.optimize_parameters\n"
            "  uv run python -m scripts.optimize_parameters --seasons 2024,2025\n"
            "  uv run python -m scripts.optimize_parameters --max-iter 1000\n"
            "  uv run python -m scripts.optimize_parameters --mode production\n"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["validation", "production"],
        default="validation",
        help="Optimization mode (default: validation). "
        "Production mode requires data from after April 30, 2026.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_BACKTEST_DB,
        metavar="PATH",
        help=f"Path to SQLite database (default: {DEFAULT_BACKTEST_DB.name})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=f"Output directory for JSON reports (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--seasons",
        type=str,
        default="2024,2025",
        metavar="YEARS",
        help="Comma-separated test seasons for validation (default: 2024,2025)",
    )
    parser.add_argument(
        "--max-iter",
        type=int,
        default=500,
        metavar="N",
        help="Maximum Nelder-Mead iterations (default: 500)",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the parameter optimization CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    args = parse_args()

    if args.mode == "production":
        try:
            report = run_production_mode(args.db_path)
        except (RuntimeError, NotImplementedError) as e:
            logger.error(str(e))
            sys.exit(1)
    elif args.mode == "validation":
        test_seasons = [int(s.strip()) for s in args.seasons.split(",")]
        if not test_seasons:
            logger.error("No test seasons specified.")
            sys.exit(1)

        logger.info(
            "Starting parameter optimization: mode=%s, seasons=%s, max_iter=%d, db=%s",
            args.mode,
            test_seasons,
            args.max_iter,
            args.db_path,
        )

        try:
            report = run_validation_mode(
                db_path=args.db_path,
                test_seasons=test_seasons,
                max_iter=args.max_iter,
            )
        except FileNotFoundError as e:
            logger.error(str(e))
            logger.error(
                "Run 'uv run python -m scripts.data_pipeline' first to create "
                "the backtest database."
            )
            sys.exit(1)
        except Exception:
            logger.exception("Optimization failed unexpectedly.")
            sys.exit(1)
    else:
        logger.error("Unknown mode: %s", args.mode)
        sys.exit(1)

    # Save and display results
    filepath = _save_report(report, args.output_dir)
    _print_summary(report)
    print(f"\n  Report saved to: {filepath}\n")


if __name__ == "__main__":
    main()
