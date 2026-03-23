"""League-specific dashboard for H2H Points league management.

Organized around ACTIONABLE WEEKLY DECISIONS: pitching planner,
hitting optimizer, waiver streams, and points calculator.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import default_season
from app.database import async_session
from app.league_config import LEAGUE_CONFIG
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.player_points import PlayerPoints

router = APIRouter(prefix="/league")
templates = Jinja2Templates(directory="app/templates")


def _get_current_week() -> tuple[date, date, int]:
    """Get the current matchup week's start/end dates and week number.

    Yahoo H2H weeks run Monday-Sunday. The deadline is Monday.
    2026 season: Week 1 starts Mon 3/23 (shortened — first MLB games Wed 3/25).
    Week 2 starts Mon 3/30. Regular weeks thereafter.
    """
    today = date.today()
    # Find the Monday of this week
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)

    # Week 1 starts Monday March 23, 2026
    season_start = date(today.year, 3, 23)
    week_num = max(1, (monday - season_start).days // 7 + 1)

    return monday, sunday, week_num


@router.get("")
async def league_dashboard(request: Request, season: int | None = Query(None)):
    """Main league dashboard page."""
    selected_season = season or default_season()
    monday, sunday, week_num = _get_current_week()
    days_remaining = max(0, (sunday - date.today()).days)

    # Points leaders
    top_hitters = []
    top_pitchers = []
    top_relievers = []
    contact_kings = []

    async with async_session() as session:
        # Top hitters by projected points
        hitter_result = await session.execute(
            select(PlayerPoints, Player)
            .join(Player, PlayerPoints.player_id == Player.id)
            .where(
                PlayerPoints.season == selected_season,
                PlayerPoints.period == "full_season",
                PlayerPoints.player_type == "hitter",
            )
            .order_by(PlayerPoints.projected_ros_points.desc())
            .limit(20)
        )
        for pp, player in hitter_result.all():
            top_hitters.append({
                "player_id": player.id,
                "name": player.name,
                "team": player.team or "",
                "position": player.position or "",
                "projected_points": round(pp.projected_ros_points or 0, 1),
                "actual_points": round(pp.actual_points or 0, 1),
                "points_per_pa": round(pp.points_per_pa or 0, 3),
                "surplus_value": round(pp.surplus_value or 0, 1),
                "positional_rank": pp.positional_rank or 0,
            })

        # Top starters by points per start
        sp_result = await session.execute(
            select(PlayerPoints, Player)
            .join(Player, PlayerPoints.player_id == Player.id)
            .where(
                PlayerPoints.season == selected_season,
                PlayerPoints.period == "full_season",
                PlayerPoints.player_type == "pitcher",
                PlayerPoints.points_per_start.isnot(None),
            )
            .order_by(PlayerPoints.projected_ros_points.desc())
            .limit(20)
        )
        for pp, player in sp_result.all():
            top_pitchers.append({
                "player_id": player.id,
                "name": player.name,
                "team": player.team or "",
                "position": player.position or "",
                "projected_points": round(pp.projected_ros_points or 0, 1),
                "actual_points": round(pp.actual_points or 0, 1),
                "points_per_start": round(pp.points_per_start or 0, 1),
                "points_per_ip": round(pp.points_per_ip or 0, 2),
                "surplus_value": round(pp.surplus_value or 0, 1),
            })

        # Top relievers by points per appearance
        rp_result = await session.execute(
            select(PlayerPoints, Player)
            .join(Player, PlayerPoints.player_id == Player.id)
            .where(
                PlayerPoints.season == selected_season,
                PlayerPoints.period == "full_season",
                PlayerPoints.player_type == "pitcher",
                PlayerPoints.points_per_appearance.isnot(None),
            )
            .order_by(PlayerPoints.projected_ros_points.desc())
            .limit(20)
        )
        for pp, player in rp_result.all():
            # Get role info
            ps_result = await session.execute(
                select(PitchingStats).where(
                    PitchingStats.player_id == player.id,
                    PitchingStats.season == selected_season,
                    PitchingStats.period == "full_season",
                )
            )
            ps = ps_result.scalar_one_or_none()
            sv = int(ps.sv or 0) if ps else 0
            hld = int(ps.hld or 0) if ps else 0
            role = "Closer" if sv > 0 else ("Setup" if hld > 0 else "Middle")

            top_relievers.append({
                "player_id": player.id,
                "name": player.name,
                "team": player.team or "",
                "role": role,
                "projected_points": round(pp.projected_ros_points or 0, 1),
                "actual_points": round(pp.actual_points or 0, 1),
                "points_per_appearance": round(pp.points_per_appearance or 0, 1),
                "sv": sv,
                "hld": hld,
                "surplus_value": round(pp.surplus_value or 0, 1),
            })

        # Contact kings: best points/PA with low K%
        ck_result = await session.execute(
            select(PlayerPoints, Player, BattingStats)
            .join(Player, PlayerPoints.player_id == Player.id)
            .join(
                BattingStats,
                (BattingStats.player_id == Player.id)
                & (BattingStats.season == PlayerPoints.season)
                & (BattingStats.period == "full_season"),
            )
            .where(
                PlayerPoints.season == selected_season,
                PlayerPoints.period == "full_season",
                PlayerPoints.player_type == "hitter",
                PlayerPoints.points_per_pa.isnot(None),
                BattingStats.k_pct < 0.20,
                BattingStats.pa >= 100,
            )
            .order_by(PlayerPoints.points_per_pa.desc())
            .limit(15)
        )
        for pp, player, bs in ck_result.all():
            k_pts_lost = round((bs.so or 0) * 0.5, 1) if bs.so else 0
            contact_kings.append({
                "player_id": player.id,
                "name": player.name,
                "team": player.team or "",
                "position": player.position or "",
                "k_pct": round((bs.k_pct or 0) * 100, 1),
                "bb_pct": round((bs.bb_pct or 0) * 100, 1),
                "avg": round(bs.avg or 0, 3),
                "points_per_pa": round(pp.points_per_pa or 0, 3),
                "projected_points": round(pp.projected_ros_points or 0, 1),
                "k_points_lost": k_pts_lost,
            })

    return templates.TemplateResponse(
        request,
        "league_dashboard.html",
        {
            "league_config": LEAGUE_CONFIG,
            "week_num": week_num,
            "days_remaining": days_remaining,
            "week_start": monday.isoformat(),
            "week_end": sunday.isoformat(),
            "selected_season": selected_season,
            "top_hitters": top_hitters,
            "top_pitchers": top_pitchers,
            "top_relievers": top_relievers,
            "contact_kings": contact_kings,
        },
    )
