"""Waiver wire recommendation engine for H2H Points league.

Scores free agents using a composite of:
  - Projected fantasy points (35%): ROS projected points in this scoring system
  - Recent performance trend (25%): last-14 Statcast metrics vs season
  - Positional need (15%): how much the position is needed (based on scarcity)
  - League scoring fit (15%): bonus for players who excel in this format
    (low-K hitters, high-SV/HLD relievers, innings-eating starters)
  - Ownership trend (10%): lower ownership = more available upside
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.league_config import K_PENALTY, REPLACEMENT_LEVEL_SLOTS
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.player_points import PlayerPoints
from app.models.statcast_summary import StatcastSummary
from app.services.projection_service import project_hitter, project_pitcher
from app.services.rankings_service import ROSTER_SPOTS

logger = logging.getLogger(__name__)


@dataclass
class WaiverRecommendation:
    player_id: int
    name: str
    team: str | None
    position: str | None
    waiver_score: float  # 0-100 composite score
    projection_score: float
    trend_score: float
    positional_need_score: float
    reasoning: str
    buy_low: bool = False
    xwoba_delta: float = 0.0
    trend: str = "stable"  # hot, cold, stable
    # Points league fields
    projected_points: float = 0.0
    points_per_pa: float | None = None
    points_per_ip: float | None = None
    scoring_fit_score: float = 0.0
    player_type: str = "hitter"


async def score_free_agents(
    session: AsyncSession, season: int, limit: int = 30
) -> list[WaiverRecommendation]:
    """Score and rank available free agents for waiver wire pickup.

    Uses projected fantasy points from the player_points table as the
    primary scoring input, with league-specific scoring fit bonuses.
    """
    # Get all players with batting stats (minimum PA to filter out inactive)
    result = await session.execute(
        select(Player)
        .join(BattingStats)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.pa >= 20,
        )
        .distinct()
    )
    hitters = result.scalars().all()

    # Also get pitchers
    pitch_result = await session.execute(
        select(Player)
        .join(PitchingStats)
        .where(
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.ip >= 10,
        )
        .distinct()
    )
    pitchers = pitch_result.scalars().all()

    # Combine unique players
    seen_ids: set[int] = set()
    all_players = []
    for p in list(hitters) + list(pitchers):
        if p.id not in seen_ids:
            seen_ids.add(p.id)
            all_players.append(p)

    # Get the max projected points for normalization
    max_pts_result = await session.execute(
        select(PlayerPoints.projected_ros_points)
        .where(
            PlayerPoints.season == season,
            PlayerPoints.period == "full_season",
        )
        .order_by(PlayerPoints.projected_ros_points.desc())
        .limit(1)
    )
    max_pts_row = max_pts_result.scalar_one_or_none()
    max_pts = max_pts_row if max_pts_row and max_pts_row > 0 else 400.0

    recommendations: list[WaiverRecommendation] = []

    for player in all_players:
        # Get player points from the pre-calculated table
        pp_result = await session.execute(
            select(PlayerPoints).where(
                PlayerPoints.player_id == player.id,
                PlayerPoints.season == season,
                PlayerPoints.period == "full_season",
            )
        )
        pp = pp_result.scalar_one_or_none()

        # Get projection for buy/sell signals
        proj = await project_hitter(session, player, season)
        player_type = "hitter"
        if not proj:
            proj = await project_pitcher(session, player, season)
            player_type = "pitcher"
        if not proj:
            continue

        # Projection score: based on projected fantasy points (0-100 scale)
        proj_pts = pp.projected_ros_points if pp else 0.0
        proj_score = min((proj_pts / max_pts) * 100, 100) if proj_pts > 0 else 0.0

        # Trend score: compare last-14 Statcast to full season
        trend_score = 50.0
        trend = "stable"
        full_sc = await session.execute(
            select(StatcastSummary).where(
                StatcastSummary.player_id == player.id,
                StatcastSummary.season == season,
                StatcastSummary.period == "full_season",
            )
        )
        full_sc_row = full_sc.scalar_one_or_none()

        recent_sc = await session.execute(
            select(StatcastSummary).where(
                StatcastSummary.player_id == player.id,
                StatcastSummary.season == season,
                StatcastSummary.period == "last_14",
            )
        )
        recent_sc_row = recent_sc.scalar_one_or_none()

        if full_sc_row and recent_sc_row and full_sc_row.xwoba and recent_sc_row.xwoba:
            delta = recent_sc_row.xwoba - full_sc_row.xwoba
            if delta > 0.030:
                trend_score = 80.0
                trend = "hot"
            elif delta > 0.015:
                trend_score = 65.0
                trend = "hot"
            elif delta < -0.030:
                trend_score = 20.0
                trend = "cold"
            elif delta < -0.015:
                trend_score = 35.0
                trend = "cold"

        # Positional scarcity score (updated for 10-team H2H league)
        pos = (player.position or "UTIL").split(",")[0].strip()
        repl_slots = REPLACEMENT_LEVEL_SLOTS.get(pos, 10)
        if repl_slots <= 10:
            pos_score = 70.0  # C, 1B, 2B, 3B, SS
        elif repl_slots <= 20:
            pos_score = 60.0  # SP, RP
        elif repl_slots <= 30:
            pos_score = 40.0  # OF
        else:
            pos_score = 30.0

        # League scoring fit bonus
        scoring_fit = 50.0  # neutral baseline
        reasons = []

        if player_type == "hitter":
            # Bonus for low-K hitters (K = -0.5 in this league)
            bat_result = await session.execute(
                select(BattingStats).where(
                    BattingStats.player_id == player.id,
                    BattingStats.season == season,
                    BattingStats.period == "full_season",
                )
            )
            bat = bat_result.scalar_one_or_none()
            if bat and bat.k_pct and bat.k_pct < 0.18:
                scoring_fit = 75.0
                reasons.append(f"Low K% ({bat.k_pct:.1%}) — premium in points format (K=-0.5)")
            elif bat and bat.bb_pct and bat.bb_pct > 0.10:
                scoring_fit = 65.0
                reasons.append(f"High BB% ({bat.bb_pct:.1%}) — walks are free points (BB=1)")
        else:
            # Bonus for relievers with saves/holds
            pitch_result2 = await session.execute(
                select(PitchingStats).where(
                    PitchingStats.player_id == player.id,
                    PitchingStats.season == season,
                    PitchingStats.period == "full_season",
                )
            )
            pitch = pitch_result2.scalar_one_or_none()
            if pitch:
                if (pitch.sv or 0) > 0:
                    scoring_fit = 85.0
                    reasons.append(f"Closer with {int(pitch.sv)} SV — saves = 7 pts each")
                elif (pitch.hld or 0) > 0:
                    scoring_fit = 75.0
                    reasons.append(f"Setup man with {int(pitch.hld)} HLD — holds = 4 pts each")
                elif (pitch.gs or 0) > 0 and (pitch.ip or 0) / max(pitch.gs, 1) > 5.5:
                    scoring_fit = 70.0
                    avg_ip = (pitch.ip or 0) / max(pitch.gs, 1)
                    reasons.append(
                        f"Innings eater ({avg_ip:.1f} IP/start) — "
                        f"each IP = 4.5 pts from outs"
                    )

        # Additional reasoning
        if trend == "hot":
            reasons.append("Recent Statcast metrics trending up")
        if hasattr(proj, "buy_low_signal") and proj.buy_low_signal:
            reasons.append(f"Buy low: xwOBA exceeds wOBA by {proj.xwoba_delta:+.3f}")
        if pos_score >= 70:
            reasons.append(f"Scarce position ({pos})")
        if proj_pts > 0:
            reasons.append(f"Projected {proj_pts:.0f} ROS points")

        reasoning = "; ".join(reasons) if reasons else "Solid production"

        # Composite score (updated weights for points league)
        composite = (
            proj_score * 0.35
            + trend_score * 0.25
            + pos_score * 0.15
            + scoring_fit * 0.15
            + 50.0 * 0.10  # ownership placeholder
        )

        buy_low = getattr(proj, "buy_low_signal", False)
        xwoba_d = getattr(proj, "xwoba_delta", 0.0)

        recommendations.append(
            WaiverRecommendation(
                player_id=player.id,
                name=player.name,
                team=player.team,
                position=player.position,
                waiver_score=round(composite, 1),
                projection_score=round(proj_score, 1),
                trend_score=round(trend_score, 1),
                positional_need_score=round(pos_score, 1),
                reasoning=reasoning,
                buy_low=buy_low,
                xwoba_delta=xwoba_d,
                trend=trend,
                projected_points=round(proj_pts, 1) if proj_pts else 0.0,
                points_per_pa=pp.points_per_pa if pp else None,
                points_per_ip=pp.points_per_ip if pp else None,
                scoring_fit_score=round(scoring_fit, 1),
                player_type=player_type,
            )
        )

    recommendations.sort(key=lambda r: r.waiver_score, reverse=True)
    return recommendations[:limit]
