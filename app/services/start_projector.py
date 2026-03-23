"""Per-start fantasy points projection model.

Projects fantasy points for individual pitcher starts, factoring in
pitcher quality, opponent matchup, and park effects. This is the most
important single model for weekly H2H Points league management.

Each start is scored per league rules:
  OUT*1.5 + K*0.5 + QS*2 - H*0.75 - ER*4 - BB*0.75
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.league_config import (
    START_THRESHOLD_MUST_START,
    START_THRESHOLD_SIT,
    START_THRESHOLD_START,
    START_THRESHOLD_STREAM,
)
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.services.mlb_service import get_probable_pitchers
from app.services.points_service import calculate_pitcher_points

logger = logging.getLogger(__name__)


@dataclass
class StartProjection:
    """Projected fantasy points for a single pitching start."""

    pitcher_id: int
    pitcher_name: str
    team: str | None
    opponent: str
    park: str | None
    game_date: str
    estimated_ip: float
    estimated_k: float
    estimated_er: float
    estimated_h: float
    estimated_bb: float
    qs_probability: float
    projected_points: float
    confidence: float  # 0-1, higher with more data
    risk_level: str  # low, medium, high
    recommendation: str  # must_start, start, stream, sit, avoid


@dataclass
class PSlotStrategy:
    """Weekly P-slot allocation recommendation."""

    sp_in_p_slots: int  # how many SP to put in P slots
    rp_in_p_slots: int  # how many RP to put in P slots
    sp_projected_points: float  # total projected from SP-heavy
    rp_projected_points: float  # total projected from RP-heavy
    recommended_strategy: str  # "sp_heavy", "rp_heavy", "mixed"
    point_differential: float  # how much better the recommended strategy is
    reasoning: str


def _get_recommendation(projected_points: float) -> str:
    """Classify a start based on projected points."""
    if projected_points >= START_THRESHOLD_MUST_START:
        return "must_start"
    elif projected_points >= START_THRESHOLD_START:
        return "start"
    elif projected_points >= START_THRESHOLD_STREAM:
        return "stream"
    elif projected_points >= START_THRESHOLD_SIT:
        return "sit"
    return "avoid"


def _get_risk_level(estimated_er: float, estimated_ip: float) -> str:
    """Classify risk based on estimated ER per 9 and innings."""
    if estimated_ip == 0:
        return "high"
    er_per_9 = estimated_er * 9 / estimated_ip
    if er_per_9 < 3.5:
        return "low"
    elif er_per_9 < 4.5:
        return "medium"
    return "high"


async def _get_team_batting_stats(
    session: AsyncSession, team: str, season: int
) -> dict:
    """Get aggregate batting stats for a team to use as opponent adjustment."""
    result = await session.execute(
        select(BattingStats)
        .join(Player)
        .where(
            Player.team == team,
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.pa >= 100,
        )
    )
    players = result.scalars().all()

    if not players:
        return {"k_pct": 0.22, "bb_pct": 0.08, "avg": 0.250, "wrc_plus": 100}

    # Average the team's batting stats
    k_pcts = [p.k_pct for p in players if p.k_pct is not None]
    bb_pcts = [p.bb_pct for p in players if p.bb_pct is not None]
    avgs = [p.avg for p in players if p.avg is not None]
    wrc_pluses = [p.wrc_plus for p in players if p.wrc_plus is not None]

    return {
        "k_pct": sum(k_pcts) / len(k_pcts) if k_pcts else 0.22,
        "bb_pct": sum(bb_pcts) / len(bb_pcts) if bb_pcts else 0.08,
        "avg": sum(avgs) / len(avgs) if avgs else 0.250,
        "wrc_plus": sum(wrc_pluses) / len(wrc_pluses) if wrc_pluses else 100,
    }


async def project_start_points(
    session: AsyncSession,
    pitcher_id: int,
    opponent_team: str,
    game_date: str,
    season: int,
    park: str | None = None,
) -> StartProjection | None:
    """Project fantasy points for a single pitching start.

    Model:
    1. Estimate IP from pitcher's avg IP/start, adjusted by opponent K%
    2. Estimate K from pitcher's K/9, adjusted by opponent K%
    3. Estimate H from pitcher's H/9, adjusted by opponent AVG
    4. Estimate ER from pitcher's ERA, adjusted by opponent wRC+
    5. Estimate BB from pitcher's BB/9, adjusted by opponent BB%
    6. QS probability from IP and ER estimates
    7. Apply league scoring formula
    """
    # Get pitcher stats
    pitch_result = await session.execute(
        select(PitchingStats, Player)
        .join(Player)
        .where(
            PitchingStats.player_id == pitcher_id,
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
        )
    )
    row = pitch_result.first()
    if not row:
        return None

    ps, player = row

    if not ps.gs or ps.gs == 0 or not ps.ip:
        return None

    # Get opponent team stats
    opp_stats = await _get_team_batting_stats(session, opponent_team, season)

    # Base rates from pitcher
    ip_per_start = ps.ip / ps.gs
    k_per_9 = ps.k_per_9 or (((ps.so or 0) / ps.ip) * 9 if ps.ip else 7.0)
    bb_per_9 = ps.bb_per_9 or (((ps.bb or 0) / ps.ip) * 9 if ps.ip else 3.0)
    h_per_9 = ((ps.h or 0) / ps.ip) * 9 if ps.ip else 8.0
    era = ps.era or 4.00

    # Opponent adjustments
    league_avg_k_pct = 0.22
    league_avg_bb_pct = 0.08
    league_avg = 0.250
    league_avg_wrc = 100.0

    # K adjustment: high-K% opponent = more Ks
    k_adjustment = opp_stats["k_pct"] / league_avg_k_pct if league_avg_k_pct > 0 else 1.0

    # BB adjustment: high-BB% opponent = more BB
    bb_adjustment = opp_stats["bb_pct"] / league_avg_bb_pct if league_avg_bb_pct > 0 else 1.0

    # H adjustment: high-AVG opponent = more hits
    h_adjustment = opp_stats["avg"] / league_avg if league_avg > 0 else 1.0

    # ER adjustment: high-wRC+ opponent = more runs
    er_adjustment = opp_stats["wrc_plus"] / league_avg_wrc if league_avg_wrc > 0 else 1.0

    # IP adjustment: high-K% opponent → deeper starts
    ip_adjustment = 1.0 + (opp_stats["k_pct"] - league_avg_k_pct) * 2

    # Estimate stats for this start
    estimated_ip = max(min(ip_per_start * ip_adjustment, 8.0), 4.0)
    estimated_k = (k_per_9 * k_adjustment) * estimated_ip / 9
    estimated_bb = (bb_per_9 * bb_adjustment) * estimated_ip / 9
    estimated_h = (h_per_9 * h_adjustment) * estimated_ip / 9
    estimated_er = (era * er_adjustment) * estimated_ip / 9

    # QS probability: requires 6+ IP and 3 or fewer ER
    qs_prob = 0.0
    if estimated_ip >= 5.5 and estimated_er <= 3.2:
        qs_prob = min(0.85, 0.5 + (6.0 - max(estimated_er, 0)) * 0.15)
    elif estimated_ip >= 5.0 and estimated_er <= 2.5:
        qs_prob = 0.5

    # Calculate projected points
    stats = {
        "IP": estimated_ip,
        "K": estimated_k,
        "ER": estimated_er,
        "H": estimated_h,
        "BB": estimated_bb,
        "QS": qs_prob,  # weighted by probability
    }
    projected_points = calculate_pitcher_points(stats)

    # Confidence based on data availability
    confidence = min(
        0.5 + (ps.gs / 30) * 0.3 + (0.2 if ps.fip else 0),
        1.0,
    )

    return StartProjection(
        pitcher_id=pitcher_id,
        pitcher_name=player.name,
        team=player.team,
        opponent=opponent_team,
        park=park,
        game_date=game_date,
        estimated_ip=round(estimated_ip, 1),
        estimated_k=round(estimated_k, 1),
        estimated_er=round(estimated_er, 1),
        estimated_h=round(estimated_h, 1),
        estimated_bb=round(estimated_bb, 1),
        qs_probability=round(qs_prob, 2),
        projected_points=round(projected_points, 1),
        confidence=round(confidence, 2),
        risk_level=_get_risk_level(estimated_er, estimated_ip),
        recommendation=_get_recommendation(projected_points),
    )


async def project_week_starts(
    session: AsyncSession,
    week_start: date,
    week_end: date,
    season: int,
) -> list[StartProjection]:
    """Project all pitcher starts for an entire week.

    Returns a list of StartProjections sorted by projected_points desc.
    """
    projections: list[StartProjection] = []
    current_date = week_start

    while current_date <= week_end:
        # Get probable pitchers for this date
        probable = await get_probable_pitchers(current_date)

        for game in probable:
            # Project away pitcher
            if game.away_pitcher_id:
                # Find our player record by mlbam_id
                result = await session.execute(
                    select(Player).where(Player.mlbam_id == str(game.away_pitcher_id))
                )
                player = result.scalar_one_or_none()
                if player:
                    proj = await project_start_points(
                        session,
                        player.id,
                        game.home_team,
                        current_date.isoformat(),
                        season,
                        park=game.home_team,  # park = home team
                    )
                    if proj:
                        projections.append(proj)

            # Project home pitcher
            if game.home_pitcher_id:
                result = await session.execute(
                    select(Player).where(Player.mlbam_id == str(game.home_pitcher_id))
                )
                player = result.scalar_one_or_none()
                if player:
                    proj = await project_start_points(
                        session,
                        player.id,
                        game.away_team,
                        current_date.isoformat(),
                        season,
                        park=game.home_team,
                    )
                    if proj:
                        projections.append(proj)

        current_date += timedelta(days=1)

    # Sort by projected points descending
    projections.sort(key=lambda p: p.projected_points, reverse=True)
    return projections


async def recommend_p_slot_strategy(
    session: AsyncSession,
    week_start: date,
    week_end: date,
    season: int,
) -> PSlotStrategy:
    """Recommend how to allocate the 4 flexible P slots for the week.

    Compares:
    - All SP in P slots: projected start points for 4 extra starters
    - All RP in P slots: projected save/hold/relief points for 4 RPs
    - Mixed: various combinations
    """
    # Get week's start projections
    week_starts = await project_week_starts(session, week_start, week_end, season)

    # Get the 4 best available streaming starts (after the 2 dedicated SP slots)
    # The top starters go in SP slots, remaining are P-slot candidates
    streamable_starts = week_starts[2:6] if len(week_starts) > 2 else []
    sp_in_p_points = sum(s.projected_points for s in streamable_starts)

    # Estimate RP value for P slots (from reliever projections)
    # Average closer appearance: ~8 pts, average setup: ~6 pts
    # In a typical week (6-7 games), a closer might pitch 3-4 times
    # 4 RP in P slots * ~5 pts/appearance * ~3 appearances = ~60 pts
    # This is a rough estimate — the reliever_service provides more precision
    from app.models.player_points import PlayerPoints

    rp_result = await session.execute(
        select(PlayerPoints)
        .where(
            PlayerPoints.season == season,
            PlayerPoints.period == "full_season",
            PlayerPoints.player_type == "pitcher",
            PlayerPoints.points_per_appearance.isnot(None),
        )
        .order_by(PlayerPoints.points_per_appearance.desc())
        .limit(4)
    )
    top_rps = rp_result.scalars().all()

    # Estimate weekly RP value: avg points per appearance * estimated appearances per week
    rp_in_p_points = 0.0
    for rp in top_rps:
        weekly_apps = 3.0  # conservative estimate
        rp_in_p_points += (rp.points_per_appearance or 0) * weekly_apps

    # Determine best strategy
    if sp_in_p_points > rp_in_p_points * 1.1:
        strategy = "sp_heavy"
        reasoning = (
            f"Load P slots with starters — {sp_in_p_points:.0f} projected pts from "
            f"{len(streamable_starts)} starts vs {rp_in_p_points:.0f} from RP"
        )
        sp_count = min(4, len(streamable_starts))
        rp_count = 4 - sp_count
    elif rp_in_p_points > sp_in_p_points * 1.1:
        strategy = "rp_heavy"
        reasoning = (
            f"Load P slots with relievers — {rp_in_p_points:.0f} projected pts from "
            f"RP vs {sp_in_p_points:.0f} from streaming starts"
        )
        sp_count = 0
        rp_count = 4
    else:
        strategy = "mixed"
        sp_count = 2
        rp_count = 2
        reasoning = (
            f"Split P slots — similar projected value between "
            f"SP ({sp_in_p_points:.0f} pts) and RP ({rp_in_p_points:.0f} pts)"
        )

    return PSlotStrategy(
        sp_in_p_slots=sp_count,
        rp_in_p_slots=rp_count,
        sp_projected_points=round(sp_in_p_points, 1),
        rp_projected_points=round(rp_in_p_points, 1),
        recommended_strategy=strategy,
        point_differential=round(abs(sp_in_p_points - rp_in_p_points), 1),
        reasoning=reasoning,
    )
