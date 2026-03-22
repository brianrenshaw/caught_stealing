"""Waiver wire recommendation engine.

Scores free agents using a composite of:
  - Projection value (30%): rest-of-season projected output
  - Recent performance trend (30%): last-14 Statcast metrics vs season
  - Positional need (20%): how much the position is needed (based on scarcity)
  - Ownership trend (10%): lower ownership = more available upside
  - Schedule (10%): upcoming matchups favorability
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batting_stats import BattingStats
from app.models.player import Player
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


async def score_free_agents(
    session: AsyncSession, season: int, limit: int = 30
) -> list[WaiverRecommendation]:
    """Score and rank available free agents for waiver wire pickup.

    Since we don't have Yahoo ownership data in this context, we score
    all players who aren't on a fantasy roster. In practice, this would
    be filtered against the league's free agent pool.
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
    all_players = result.scalars().all()

    recommendations: list[WaiverRecommendation] = []

    for player in all_players:
        proj = await project_hitter(session, player, season)
        if not proj:
            # Try as pitcher
            proj = await project_pitcher(session, player, season)
        if not proj:
            continue

        # Projection score: based on confidence and overall projected value
        proj_score = proj.confidence_score * 50

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

        # Positional scarcity score
        pos = (player.position or "UTIL").split(",")[0].strip()
        spots = ROSTER_SPOTS.get(pos, 12)
        # Scarcer positions get a boost (fewer roster spots = more valuable pickup)
        if spots <= 12:
            pos_score = 70.0
        elif spots <= 36:
            pos_score = 50.0
        else:
            pos_score = 30.0

        # Composite score
        composite = (
            proj_score * 0.30
            + trend_score * 0.30
            + pos_score * 0.20
            + 50.0 * 0.10  # ownership placeholder
            + 50.0 * 0.10  # schedule placeholder
        )

        # Build reasoning
        reasons = []
        if trend == "hot":
            reasons.append("Recent Statcast metrics trending up")
        if hasattr(proj, "buy_low_signal") and proj.buy_low_signal:
            reasons.append(f"Buy low: xwOBA exceeds wOBA by {proj.xwoba_delta:+.3f}")
        if pos_score >= 70:
            reasons.append(f"Scarce position ({pos})")
        if proj.confidence_score > 0.6:
            reasons.append("High projection confidence")
        reasoning = "; ".join(reasons) if reasons else "Solid production"

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
            )
        )

    recommendations.sort(key=lambda r: r.waiver_score, reverse=True)
    return recommendations[:limit]
