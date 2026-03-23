"""Reliever valuation model for H2H Points league.

With SV=7, HLD=4, RW=4, relievers need a dedicated model.
An elite closer earning 12.5 pts per save appearance is one of
the most efficient point sources in the league.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.league_config import (
    RELIEVER_TIER_AVOID,
    RELIEVER_TIER_ELITE_CLOSER,
    RELIEVER_TIER_HOLDS_MACHINE,
    RELIEVER_TIER_STREAMING_RP,
    RELIEVER_TIER_STRONG_CLOSER,
)
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.player_points import PlayerPoints
from app.services.mlb_service import get_schedule
from app.services.points_service import calculate_pitcher_points

logger = logging.getLogger(__name__)


@dataclass
class RelieverValue:
    """Valuation of a reliever in the H2H Points scoring system."""

    pitcher_id: int
    name: str
    team: str | None
    role: str  # closer, setup, middle, long
    save_opportunities_per_week: float
    hold_opportunities_per_week: float
    avg_points_per_appearance: float
    projected_weekly_points: float
    projected_ros_points: float
    volatility: float  # estimated std dev of points per appearance
    recommendation: str  # elite_closer, strong_closer, holds_machine, streaming_rp, avoid


@dataclass
class RelieverWeeklyOutlook:
    """Weekly outlook for a reliever."""

    pitcher_id: int
    name: str
    team: str | None
    role: str
    team_games_this_week: int
    projected_appearances: float
    projected_weekly_points: float
    avg_points_per_appearance: float
    recommendation: str


def _determine_role(ps: PitchingStats) -> str:
    """Determine a reliever's role from their stats."""
    sv = ps.sv or 0
    hld = ps.hld or 0
    g = ps.g or 1
    gs = ps.gs or 0
    ip = ps.ip or 0

    if gs > g * 0.3:
        return "starter"  # Not actually a reliever

    if sv > 0:
        return "closer"
    elif hld > 0:
        return "setup"
    elif ip / max(g, 1) > 1.5:
        return "long"
    return "middle"


def _estimate_volatility(ps: PitchingStats) -> float:
    """Estimate volatility from ERA and WHIP variance indicators.

    Higher ERA/WHIP relative to FIP suggests more volatile outcomes.
    """
    era = ps.era or 4.00
    fip = ps.fip or era
    whip = ps.whip or 1.25

    # ERA - FIP gap indicates luck/variance
    era_fip_gap = abs(era - fip)

    # High WHIP with low ERA = lucky (volatile)
    if whip > 1.30 and era < 3.50:
        return 4.0  # high volatility

    if era_fip_gap > 1.0:
        return 3.5
    elif era_fip_gap > 0.5:
        return 2.5
    return 1.5  # low volatility


async def value_reliever(
    session: AsyncSession,
    pitcher_id: int,
    season: int,
    period: str = "full_season",
) -> RelieverValue | None:
    """Calculate a reliever's value in the H2H Points scoring system."""
    result = await session.execute(
        select(PitchingStats, Player)
        .join(Player)
        .where(
            PitchingStats.player_id == pitcher_id,
            PitchingStats.season == season,
            PitchingStats.period == period,
        )
    )
    row = result.first()
    if not row:
        return None

    ps, player = row
    role = _determine_role(ps)

    if role == "starter":
        return None  # Not a reliever

    g = ps.g or 0
    if g == 0:
        return None

    # Calculate per-appearance points
    stats_dict = {
        "IP": ps.ip,
        "G": ps.g,
        "GS": ps.gs,
        "W": ps.w,
        "SV": ps.sv,
        "HLD": ps.hld,
        "H": ps.h,
        "ER": ps.er,
        "BB": ps.bb,
        "SO": ps.so,
        "QS": ps.qs,
        "HBP": ps.hbp,
    }
    total_points = calculate_pitcher_points(stats_dict, is_reliever=True)
    avg_per_app = total_points / g

    # Estimate weekly opportunities
    # Average MLB team plays ~6.2 games/week
    games_per_week = 6.2

    sv = ps.sv or 0
    hld = ps.hld or 0

    if role == "closer":
        # Closers get save opportunities in ~60% of team wins
        # Average team wins ~50% → ~3.1 wins/week → ~1.9 SV opps/week
        sv_per_game = sv / max(g, 1)
        sv_opps_per_week = sv_per_game * games_per_week * 1.5  # scale up for future opps
        hld_opps_per_week = 0.0
    elif role == "setup":
        sv_opps_per_week = 0.0
        hld_per_game = hld / max(g, 1)
        hld_opps_per_week = hld_per_game * games_per_week * 1.5
    else:
        sv_opps_per_week = 0.0
        hld_opps_per_week = 0.0

    # Estimate weekly appearances and points
    apps_per_week = min(g / 26 * 6.2, 5.0)  # ~26 weeks in season, max 5/week
    projected_weekly = avg_per_app * apps_per_week

    # Estimate ROS points from player_points table or calculate
    pp_result = await session.execute(
        select(PlayerPoints).where(
            PlayerPoints.player_id == pitcher_id,
            PlayerPoints.season == season,
            PlayerPoints.period == "full_season",
        )
    )
    pp = pp_result.scalar_one_or_none()
    projected_ros = pp.projected_ros_points if pp else projected_weekly * 20  # ~20 weeks remaining

    # Volatility
    volatility = _estimate_volatility(ps)

    # Recommendation
    if role == "closer" and avg_per_app >= 8.0 and sv >= 10:
        recommendation = RELIEVER_TIER_ELITE_CLOSER
    elif role == "closer" and avg_per_app >= 5.0:
        recommendation = RELIEVER_TIER_STRONG_CLOSER
    elif role == "setup" and hld_opps_per_week >= 2.0:
        recommendation = RELIEVER_TIER_HOLDS_MACHINE
    elif avg_per_app >= 3.0 and volatility < 3.0:
        recommendation = RELIEVER_TIER_STREAMING_RP
    else:
        recommendation = RELIEVER_TIER_AVOID

    return RelieverValue(
        pitcher_id=pitcher_id,
        name=player.name,
        team=player.team,
        role=role,
        save_opportunities_per_week=round(sv_opps_per_week, 1),
        hold_opportunities_per_week=round(hld_opps_per_week, 1),
        avg_points_per_appearance=round(avg_per_app, 1),
        projected_weekly_points=round(projected_weekly, 1),
        projected_ros_points=round(projected_ros, 1),
        volatility=round(volatility, 1),
        recommendation=recommendation,
    )


async def get_reliever_weekly_outlook(
    session: AsyncSession,
    week_start: date,
    week_end: date,
    season: int,
    limit: int = 30,
) -> list[RelieverWeeklyOutlook]:
    """Rank relievers by projected weekly points for the upcoming week.

    Considers:
    - Number of team games this week
    - Reliever's average points per appearance
    - Role (closer > setup > middle for opportunity)
    """
    # Count games per team this week
    team_games: dict[str, int] = {}
    current_date = week_start
    while current_date <= week_end:
        games = await get_schedule(current_date)
        for game in games:
            team_games[game.away_team] = team_games.get(game.away_team, 0) + 1
            team_games[game.home_team] = team_games.get(game.home_team, 0) + 1
        current_date += timedelta(days=1)

    # Get all relievers with their points data
    result = await session.execute(
        select(PlayerPoints, Player, PitchingStats)
        .join(Player, PlayerPoints.player_id == Player.id)
        .join(
            PitchingStats,
            (PitchingStats.player_id == Player.id)
            & (PitchingStats.season == season)
            & (PitchingStats.period == "full_season"),
        )
        .where(
            PlayerPoints.season == season,
            PlayerPoints.period == "full_season",
            PlayerPoints.player_type == "pitcher",
            PlayerPoints.points_per_appearance.isnot(None),
        )
    )

    outlooks: list[RelieverWeeklyOutlook] = []
    for pp, player, ps in result.all():
        role = _determine_role(ps)
        if role == "starter":
            continue

        team = player.team or ""
        games_this_week = team_games.get(team, 0)

        # Estimate appearances this week based on role and team games
        g = ps.g or 1
        apps_per_game = min(g / 162, 0.8)  # cap at 80% of games
        projected_apps = apps_per_game * games_this_week

        avg_per_app = pp.points_per_appearance or 0
        projected_weekly = avg_per_app * projected_apps

        # Role-based recommendation
        if role == "closer" and avg_per_app >= 6.0:
            rec = "must_roster"
        elif role == "setup" and avg_per_app >= 4.0:
            rec = "start"
        elif avg_per_app >= 3.0 and games_this_week >= 6:
            rec = "stream"
        else:
            rec = "bench"

        outlooks.append(
            RelieverWeeklyOutlook(
                pitcher_id=player.id,
                name=player.name,
                team=player.team,
                role=role,
                team_games_this_week=games_this_week,
                projected_appearances=round(projected_apps, 1),
                projected_weekly_points=round(projected_weekly, 1),
                avg_points_per_appearance=round(avg_per_app, 1),
                recommendation=rec,
            )
        )

    outlooks.sort(key=lambda o: o.projected_weekly_points, reverse=True)
    return outlooks[:limit]
