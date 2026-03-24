"""League-specific dashboard for H2H Points league management.

Organized around ACTIONABLE WEEKLY DECISIONS: pitching planner,
hitting optimizer, waiver streams, and points calculator.
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import default_season
from app.database import async_session
from app.league_config import LEAGUE_CONFIG
from app.models.batting_stats import BattingStats
from app.models.league_team import LeagueTeam
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.player_points import PlayerPoints
from app.models.roster import Roster
from app.services.yahoo_service import yahoo_service

logger = logging.getLogger(__name__)

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
        # Ownership lookup: player_id -> (fantasy_team_name, is_my_team)
        roster_result = await session.execute(
            select(Roster.player_id, Roster.team_name, Roster.is_my_team)
        )
        ownership = {pid: (tname, mine) for pid, tname, mine in roster_result.all()}

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
            own = ownership.get(player.id)
            top_hitters.append(
                {
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team or "",
                    "position": player.position or "",
                    "projected_points": round(pp.projected_ros_points or 0, 1),
                    "actual_points": round(pp.actual_points or 0, 1),
                    "points_per_pa": round(pp.points_per_pa or 0, 3),
                    "surplus_value": round(pp.surplus_value or 0, 1),
                    "positional_rank": pp.positional_rank or 0,
                    "fantasy_team": own[0] if own else None,
                    "is_my_team": own[1] if own else False,
                }
            )

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
            own = ownership.get(player.id)
            top_pitchers.append(
                {
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team or "",
                    "position": player.position or "",
                    "projected_points": round(pp.projected_ros_points or 0, 1),
                    "actual_points": round(pp.actual_points or 0, 1),
                    "points_per_start": round(pp.points_per_start or 0, 1),
                    "points_per_ip": round(pp.points_per_ip or 0, 2),
                    "surplus_value": round(pp.surplus_value or 0, 1),
                    "fantasy_team": own[0] if own else None,
                    "is_my_team": own[1] if own else False,
                }
            )

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

            own = ownership.get(player.id)
            top_relievers.append(
                {
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
                    "fantasy_team": own[0] if own else None,
                    "is_my_team": own[1] if own else False,
                }
            )

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
            own = ownership.get(player.id)
            contact_kings.append(
                {
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
                    "fantasy_team": own[0] if own else None,
                    "is_my_team": own[1] if own else False,
                }
            )

        # League standings with this week's scoreboard data
        standings_result = await session.execute(select(LeagueTeam).order_by(LeagueTeam.rank))
        standings_rows = standings_result.scalars().all()

    # Fetch current week scoreboard for projected/actual weekly points
    scoreboard_map: dict[str, dict] = {}
    try:
        from app.services.weekly_matchup_service import _parse_scoreboard

        scoreboard = await yahoo_service.get_scoreboard("current")
        for td in _parse_scoreboard(scoreboard):
            scoreboard_map[td["team_id"]] = td
    except Exception as e:
        logger.warning(f"Scoreboard fetch failed: {e}")

    standings = []
    for lt in standings_rows:
        sb = scoreboard_map.get(str(lt.team_id), {})
        standings.append(
            {
                "rank": lt.rank,
                "team_name": lt.team_name,
                "team_id": lt.team_id,
                "is_my_team": lt.is_my_team,
                "wins": lt.wins,
                "losses": lt.losses,
                "ties": lt.ties,
                "points_for": round(lt.points_for, 1),
                "points_against": round(lt.points_against, 1),
                "week_projected": round(sb.get("yahoo_projected", 0), 1),
                "week_actual": round(sb.get("actual", 0), 1),
                "opponent_name": sb.get("opponent_team_name", ""),
            }
        )

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
            "standings": standings,
        },
    )
