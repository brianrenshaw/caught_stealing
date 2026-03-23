"""Advanced analytics service for projection adjustments and signal scoring."""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.statcast_summary import StatcastSummary

logger = logging.getLogger(__name__)


@dataclass
class AdvancedProjection:
    baseline_fp: float
    adjusted_fp: float
    adjustment_pct: float
    direction: str  # "up", "down", "neutral"
    flag_text: str


@dataclass
class BatterAdvancedStats:
    xwoba: float | None = None
    woba: float | None = None
    iso: float | None = None
    barrel_pct: float | None = None
    hard_hit_pct: float | None = None
    bb_pct: float | None = None
    k_pct: float | None = None
    sprint_speed: float | None = None
    sb_success_pct: float | None = None
    babip: float | None = None
    avg_exit_velo: float | None = None


@dataclass
class PitcherAdvancedStats:
    xera: float | None = None
    siera: float | None = None
    k_pct: float | None = None
    bb_pct: float | None = None
    k_bb_pct: float | None = None
    gb_pct: float | None = None
    hr_fb_pct: float | None = None
    whiff_pct: float | None = None
    gmli: float | None = None
    ip_per_g: float | None = None
    era: float | None = None
    lob_pct: float | None = None


def calculate_batter_advanced_fp(
    baseline_fp: float,
    woba: float | None,
    xwoba: float | None,
) -> AdvancedProjection:
    """Adjust batter projected FP based on xwOBA vs wOBA divergence."""
    if baseline_fp <= 0 or woba is None or xwoba is None:
        return AdvancedProjection(
            baseline_fp=baseline_fp,
            adjusted_fp=baseline_fp,
            adjustment_pct=0.0,
            direction="neutral",
            flag_text="",
        )

    # Delta in "points" (multiply by 1000 for the standard representation)
    delta = xwoba - woba  # positive = underperforming quality
    delta_pts = delta * 1000  # e.g., 0.030 -> 30 points

    if delta_pts >= 20:
        # Underperforming contact quality — adjust upward
        # 30-point gap ≈ 10% boost, scale linearly
        adj_pct = min((delta_pts / 30) * 0.10, 0.20)  # cap at 20%
        adjusted = baseline_fp * (1 + adj_pct)
        return AdvancedProjection(
            baseline_fp=baseline_fp,
            adjusted_fp=round(adjusted, 1),
            adjustment_pct=round(adj_pct * 100, 1),
            direction="up",
            flag_text="Underperforming Contact Quality",
        )
    elif delta_pts <= -20:
        # Overperforming contact quality — adjust downward
        adj_pct = min((abs(delta_pts) / 30) * 0.10, 0.20)
        adjusted = baseline_fp * (1 - adj_pct)
        return AdvancedProjection(
            baseline_fp=baseline_fp,
            adjusted_fp=round(adjusted, 1),
            adjustment_pct=round(-adj_pct * 100, 1),
            direction="down",
            flag_text="Overperforming Contact Quality",
        )

    return AdvancedProjection(
        baseline_fp=baseline_fp,
        adjusted_fp=baseline_fp,
        adjustment_pct=0.0,
        direction="neutral",
        flag_text="",
    )


def calculate_pitcher_advanced_fp(
    baseline_fp: float,
    era: float | None,
    xera: float | None,
    siera: float | None,
    gmli: float | None = None,
    is_closer: bool = False,
) -> AdvancedProjection:
    """Adjust pitcher projected FP based on xERA/SIERA vs ERA divergence."""
    if baseline_fp <= 0 or era is None:
        return AdvancedProjection(
            baseline_fp=baseline_fp,
            adjusted_fp=baseline_fp,
            adjustment_pct=0.0,
            direction="neutral",
            flag_text="",
        )

    # Use the best available expected ERA metric
    best_expected = None
    if xera is not None and siera is not None:
        best_expected = min(xera, siera)
    elif xera is not None:
        best_expected = xera
    elif siera is not None:
        best_expected = siera

    if best_expected is None:
        return AdvancedProjection(
            baseline_fp=baseline_fp,
            adjusted_fp=baseline_fp,
            adjustment_pct=0.0,
            direction="neutral",
            flag_text="",
        )

    gap = era - best_expected  # positive = actual ERA worse than expected

    flags = []

    if gap >= 0.75:
        # Better than results show — adjust upward
        adj_pct = min((gap / 1.5) * 0.12, 0.20)
        adjusted = baseline_fp * (1 + adj_pct)
        flags.append("Better Than Results Show")
    elif gap <= -0.75:
        # Regression risk — adjust downward
        adj_pct = min((abs(gap) / 1.5) * 0.12, 0.20)
        adjusted = baseline_fp * (1 - adj_pct)
        adj_pct = -adj_pct
        flags.append("Regression Risk")
    else:
        adjusted = baseline_fp
        adj_pct = 0.0

    # Reliever save opportunity upside
    if gmli is not None and gmli > 1.5 and not is_closer:
        flags.append("Save Opportunity Upside")

    return AdvancedProjection(
        baseline_fp=baseline_fp,
        adjusted_fp=round(adjusted, 1),
        adjustment_pct=round(adj_pct * 100, 1),
        direction="up" if adj_pct > 0 else ("down" if adj_pct < 0 else "neutral"),
        flag_text="; ".join(flags) if flags else "",
    )


async def get_batter_advanced_stats(
    player_id: int,
    season: int,
    db: AsyncSession,
) -> BatterAdvancedStats:
    """Fetch advanced stats for a batter from BattingStats + StatcastSummary."""
    stats = BatterAdvancedStats()

    # Get batting stats
    result = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id == player_id,
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.source == "fangraphs",
        )
    )
    batting = result.scalar_one_or_none()
    if batting:
        stats.woba = batting.woba
        stats.iso = batting.iso
        stats.babip = batting.babip
        stats.k_pct = batting.k_pct
        stats.bb_pct = batting.bb_pct
        # Compute SB success rate
        sb = batting.sb or 0
        cs = batting.cs or 0
        if sb + cs > 0:
            stats.sb_success_pct = round(sb / (sb + cs) * 100, 1)

    # Get statcast summary
    result = await db.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == player_id,
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
            StatcastSummary.player_type == "batter",
        )
    )
    statcast = result.scalar_one_or_none()
    if statcast:
        stats.xwoba = statcast.xwoba
        stats.barrel_pct = statcast.barrel_pct
        stats.hard_hit_pct = statcast.hard_hit_pct
        stats.sprint_speed = statcast.sprint_speed
        stats.avg_exit_velo = statcast.avg_exit_velo

    return stats


async def get_pitcher_advanced_stats(
    player_id: int,
    season: int,
    db: AsyncSession,
) -> PitcherAdvancedStats:
    """Fetch advanced stats for a pitcher from PitchingStats + StatcastSummary."""
    stats = PitcherAdvancedStats()

    # Get pitching stats
    result = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id == player_id,
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.source == "fangraphs",
        )
    )
    pitching = result.scalar_one_or_none()
    if pitching:
        stats.siera = pitching.siera
        stats.k_pct = pitching.k_pct
        stats.bb_pct = pitching.bb_pct
        stats.k_bb_pct = pitching.k_bb_pct
        stats.gb_pct = pitching.gb_pct
        stats.hr_fb_pct = pitching.hr_fb_pct
        stats.gmli = pitching.gmli
        stats.era = pitching.era
        stats.lob_pct = pitching.lob_pct
        # Compute IP/G
        if pitching.ip and pitching.g and pitching.g > 0:
            stats.ip_per_g = round(pitching.ip / pitching.g, 2)

    # Get statcast summary
    result = await db.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == player_id,
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
            StatcastSummary.player_type == "pitcher",
        )
    )
    statcast = result.scalar_one_or_none()
    if statcast:
        stats.xera = statcast.xera
        stats.whiff_pct = statcast.whiff_pct

    return stats


async def get_batters_advanced_stats_bulk(
    player_ids: list[int],
    season: int,
    db: AsyncSession,
) -> dict[int, BatterAdvancedStats]:
    """Bulk-fetch advanced stats for multiple batters."""
    if not player_ids:
        return {}

    # Fetch all batting stats in one query
    result = await db.execute(
        select(BattingStats).where(
            BattingStats.player_id.in_(player_ids),
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.source == "fangraphs",
        )
    )
    batting_map = {b.player_id: b for b in result.scalars().all()}

    # Fetch all statcast summaries in one query
    result = await db.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id.in_(player_ids),
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
            StatcastSummary.player_type == "batter",
        )
    )
    statcast_map = {s.player_id: s for s in result.scalars().all()}

    out: dict[int, BatterAdvancedStats] = {}
    for pid in player_ids:
        stats = BatterAdvancedStats()
        batting = batting_map.get(pid)
        if batting:
            stats.woba = batting.woba
            stats.iso = batting.iso
            stats.babip = batting.babip
            stats.k_pct = batting.k_pct
            stats.bb_pct = batting.bb_pct
            sb = batting.sb or 0
            cs = batting.cs or 0
            if sb + cs > 0:
                stats.sb_success_pct = round(sb / (sb + cs) * 100, 1)
        statcast = statcast_map.get(pid)
        if statcast:
            stats.xwoba = statcast.xwoba
            stats.barrel_pct = statcast.barrel_pct
            stats.hard_hit_pct = statcast.hard_hit_pct
            stats.sprint_speed = statcast.sprint_speed
            stats.avg_exit_velo = statcast.avg_exit_velo
        out[pid] = stats

    return out


async def get_pitchers_advanced_stats_bulk(
    player_ids: list[int],
    season: int,
    db: AsyncSession,
) -> dict[int, PitcherAdvancedStats]:
    """Bulk-fetch advanced stats for multiple pitchers."""
    if not player_ids:
        return {}

    result = await db.execute(
        select(PitchingStats).where(
            PitchingStats.player_id.in_(player_ids),
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.source == "fangraphs",
        )
    )
    pitching_map = {p.player_id: p for p in result.scalars().all()}

    result = await db.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id.in_(player_ids),
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
            StatcastSummary.player_type == "pitcher",
        )
    )
    statcast_map = {s.player_id: s for s in result.scalars().all()}

    out: dict[int, PitcherAdvancedStats] = {}
    for pid in player_ids:
        stats = PitcherAdvancedStats()
        pitching = pitching_map.get(pid)
        if pitching:
            stats.siera = pitching.siera
            stats.k_pct = pitching.k_pct
            stats.bb_pct = pitching.bb_pct
            stats.k_bb_pct = pitching.k_bb_pct
            stats.gb_pct = pitching.gb_pct
            stats.hr_fb_pct = pitching.hr_fb_pct
            stats.gmli = pitching.gmli
            stats.era = pitching.era
            stats.lob_pct = pitching.lob_pct
            if pitching.ip and pitching.g and pitching.g > 0:
                stats.ip_per_g = round(pitching.ip / pitching.g, 2)
        statcast = statcast_map.get(pid)
        if statcast:
            stats.xera = statcast.xera
            stats.whiff_pct = statcast.whiff_pct
        out[pid] = stats

    return out
