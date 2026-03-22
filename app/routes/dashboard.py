from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, union
from sqlalchemy.orm import selectinload

from app.config import default_season
from app.database import async_session
from app.models.batting_stats import BattingStats
from app.models.league_team import LeagueTeam
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.roster import Roster
from app.models.statcast_summary import StatcastSummary
from app.models.stats import Stat
from app.models.sync_log import SyncLog
from app.services.yahoo_service import yahoo_service

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _get_available_seasons(session) -> list[int]:
    """Return all seasons that have stats data, descending."""
    batting_seasons = select(BattingStats.season).distinct()
    pitching_seasons = select(PitchingStats.season).distinct()
    combined = union(batting_seasons, pitching_seasons).subquery()
    result = await session.execute(select(combined.c.season).order_by(combined.c.season.desc()))
    return [row[0] for row in result.fetchall()]


async def _get_top_hitters(session, season: int, limit: int = 20) -> list[dict]:
    """Get top hitters by OPS for the given season."""
    result = await session.execute(
        select(BattingStats, Player)
        .join(Player, BattingStats.player_id == Player.id)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.pa >= 50,
        )
        .order_by(BattingStats.ops.desc())
        .limit(limit)
    )
    rows = result.all()
    hitters = []
    for stats, player in rows:
        hitters.append(
            {
                "player_id": player.id,
                "name": player.name,
                "team": player.team or "",
                "position": player.position or "",
                "pa": int(stats.pa or 0),
                "avg": stats.avg or 0,
                "obp": stats.obp or 0,
                "slg": stats.slg or 0,
                "ops": stats.ops or 0,
                "hr": int(stats.hr or 0),
                "r": int(stats.r or 0),
                "rbi": int(stats.rbi or 0),
                "sb": int(stats.sb or 0),
                "woba": stats.woba or 0,
                "wrc_plus": stats.wrc_plus or 0,
            }
        )
    return hitters


async def _get_top_pitchers(session, season: int, limit: int = 20) -> list[dict]:
    """Get top pitchers by ERA (min 20 IP) for the given season."""
    result = await session.execute(
        select(PitchingStats, Player)
        .join(Player, PitchingStats.player_id == Player.id)
        .where(
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.ip >= 20,
        )
        .order_by(PitchingStats.era.asc())
        .limit(limit)
    )
    rows = result.all()
    pitchers = []
    for stats, player in rows:
        pitchers.append(
            {
                "player_id": player.id,
                "name": player.name,
                "team": player.team or "",
                "position": player.position or "",
                "ip": round(stats.ip or 0, 1),
                "w": int(stats.w or 0),
                "l": int(getattr(stats, "l", 0) or 0),
                "sv": int(stats.sv or 0),
                "era": round(stats.era or 0, 2),
                "whip": round(stats.whip or 0, 2),
                "so": int(stats.so or 0),
                "k_per_9": round(stats.k_per_9 or 0, 1),
                "bb_per_9": round(stats.bb_per_9 or 0, 1),
                "fip": round(stats.fip or 0, 2),
            }
        )
    return pitchers


async def _get_hr_leaders(session, season: int, limit: int = 10) -> list[dict]:
    """Get HR leaders."""
    result = await session.execute(
        select(BattingStats, Player)
        .join(Player, BattingStats.player_id == Player.id)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
        )
        .order_by(BattingStats.hr.desc())
        .limit(limit)
    )
    return [
        {"player_id": p.id, "name": p.name, "team": p.team or "", "value": int(s.hr or 0)}
        for s, p in result.all()
    ]


async def _get_sb_leaders(session, season: int, limit: int = 10) -> list[dict]:
    """Get SB leaders."""
    result = await session.execute(
        select(BattingStats, Player)
        .join(Player, BattingStats.player_id == Player.id)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
        )
        .order_by(BattingStats.sb.desc())
        .limit(limit)
    )
    return [
        {"player_id": p.id, "name": p.name, "team": p.team or "", "value": int(s.sb or 0)}
        for s, p in result.all()
    ]


async def _get_avg_leaders(session, season: int, limit: int = 10) -> list[dict]:
    """Get AVG leaders (min 50 PA)."""
    result = await session.execute(
        select(BattingStats, Player)
        .join(Player, BattingStats.player_id == Player.id)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.pa >= 50,
        )
        .order_by(BattingStats.avg.desc())
        .limit(limit)
    )
    return [
        {"player_id": p.id, "name": p.name, "team": p.team or "", "value": round(s.avg or 0, 3)}
        for s, p in result.all()
    ]


async def _get_k_leaders(session, season: int, limit: int = 10) -> list[dict]:
    """Get strikeout leaders."""
    result = await session.execute(
        select(PitchingStats, Player)
        .join(Player, PitchingStats.player_id == Player.id)
        .where(
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
        )
        .order_by(PitchingStats.so.desc())
        .limit(limit)
    )
    return [
        {"player_id": p.id, "name": p.name, "team": p.team or "", "value": int(s.so or 0)}
        for s, p in result.all()
    ]


async def _get_stats_summary(session, season: int) -> dict:
    """Get aggregate counts for the stats summary bar."""
    batting_count = await session.execute(
        select(func.count())
        .select_from(BattingStats)
        .where(BattingStats.season == season, BattingStats.period == "full_season")
    )
    pitching_count = await session.execute(
        select(func.count())
        .select_from(PitchingStats)
        .where(PitchingStats.season == season, PitchingStats.period == "full_season")
    )
    statcast_count = await session.execute(
        select(func.count()).select_from(StatcastSummary).where(StatcastSummary.season == season)
    )
    return {
        "batters": batting_count.scalar() or 0,
        "pitchers": pitching_count.scalar() or 0,
        "statcast": statcast_count.scalar() or 0,
    }


@router.get("/")
async def dashboard(request: Request, season: int | None = Query(None)):
    setup_needed = not yahoo_service.is_configured()

    standings = []
    my_roster = []
    last_sync = None
    league_name = None
    streaming_picks = []
    buy_low = []
    sell_high = []
    hot_pickups = []
    top_hitters = []
    top_pitchers = []
    hr_leaders = []
    sb_leaders = []
    avg_leaders = []
    k_leaders = []
    available_seasons = []
    selected_season = default_season()
    stats_summary = {"batters": 0, "pitchers": 0, "statcast": 0}

    async with async_session() as session:
        # Get available seasons (works even without Yahoo)
        available_seasons = await _get_available_seasons(session)

        if season and season in available_seasons:
            selected_season = season
        elif available_seasons:
            selected_season = available_seasons[0]

        # Get last sync info
        result = await session.execute(
            select(SyncLog).where(SyncLog.status == "success").order_by(SyncLog.id.desc()).limit(1)
        )
        sync_log = result.scalar_one_or_none()
        if sync_log and sync_log.completed_at:
            last_sync = sync_log.completed_at.strftime("%b %d, %I:%M %p")

        if not setup_needed:
            # Get standings from LeagueTeam table
            result = await session.execute(select(LeagueTeam).order_by(LeagueTeam.rank))
            league_teams = result.scalars().all()
            standings = [
                {
                    "team_id": t.team_id,
                    "team_name": t.team_name,
                    "rank": t.rank,
                    "wins": t.wins,
                    "losses": t.losses,
                    "ties": t.ties,
                    "points_for": t.points_for,
                    "points_against": t.points_against,
                    "is_my_team": t.is_my_team,
                }
                for t in league_teams
            ]

            # Set league name
            lid = yahoo_service._query.league_id if yahoo_service._query else ""
            league_name = f"League {lid}"

            # Get my roster with player info (if available)
            result = await session.execute(
                select(Roster)
                .options(selectinload(Roster.player))
                .where(Roster.is_my_team.is_(True))
            )
            roster_entries = result.scalars().all()

            for entry in roster_entries:
                player = entry.player
                if not player:
                    continue

                stat_result = await session.execute(
                    select(Stat).where(Stat.player_id == player.id, Stat.source == "yahoo")
                )
                player_stats = {s.stat_name: s.value for s in stat_result.scalars().all()}

                my_roster.append(
                    {
                        "player_id": player.id,
                        "name": player.name,
                        "team": player.team,
                        "position": player.position or entry.roster_position,
                        "roster_position": entry.roster_position,
                        "stats": player_stats,
                    }
                )

            # Load analysis data (gracefully handle missing stats data)
            try:
                from app.services.matchup_service import get_streaming_pitchers

                streaming_picks = await get_streaming_pitchers(
                    session, season=selected_season, limit=5
                )
            except Exception:
                pass

            try:
                from app.services.rankings_service import (
                    get_buy_low_candidates,
                    get_hot_pickups,
                    get_sell_high_candidates,
                )

                buy_low = await get_buy_low_candidates(session, selected_season, limit=5)
                sell_high = await get_sell_high_candidates(session, selected_season, limit=5)
                hot_pickups = await get_hot_pickups(session, selected_season, limit=5)
            except Exception:
                pass

        # Stats leaderboards (available even without Yahoo)
        if available_seasons:
            top_hitters = await _get_top_hitters(session, selected_season)
            top_pitchers = await _get_top_pitchers(session, selected_season)
            hr_leaders = await _get_hr_leaders(session, selected_season)
            sb_leaders = await _get_sb_leaders(session, selected_season)
            avg_leaders = await _get_avg_leaders(session, selected_season)
            k_leaders = await _get_k_leaders(session, selected_season)
            stats_summary = await _get_stats_summary(session, selected_season)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "setup_needed": setup_needed,
            "standings": standings,
            "my_roster": my_roster,
            "last_sync": last_sync,
            "league_name": league_name,
            "streaming_picks": streaming_picks,
            "buy_low": buy_low,
            "sell_high": sell_high,
            "hot_pickups": hot_pickups,
            "top_hitters": top_hitters,
            "top_pitchers": top_pitchers,
            "hr_leaders": hr_leaders,
            "sb_leaders": sb_leaders,
            "avg_leaders": avg_leaders,
            "k_leaders": k_leaders,
            "selected_season": selected_season,
            "available_seasons": available_seasons,
            "stats_summary": stats_summary,
        },
    )
