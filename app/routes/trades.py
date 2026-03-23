import logging
from collections import defaultdict

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, select

from app.config import default_season
from app.database import async_session
from app.models.player import Player
from app.models.player_points import PlayerPoints
from app.models.roster import Roster
from app.services.trade_service import (
    analyze_trade_ai,
    calculate_trade_values,
    evaluate_trade,
    store_trade_values,
    suggest_trades_ai,
)

POSITION_ORDER = ["C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "BN", "IL", "NA"]


def _pos_sort_key(entry: dict) -> int:
    """Return sort index for a roster_position value."""
    pos = entry.get("roster_position", "")
    try:
        return POSITION_ORDER.index(pos)
    except ValueError:
        return len(POSITION_ORDER)

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _resolve_season(session) -> int:
    """Return default_season(), falling back to the most recent season with data."""
    season = default_season()
    check = await session.execute(
        select(PlayerPoints.season)
        .where(PlayerPoints.season == season, PlayerPoints.period == "full_season")
        .limit(1)
    )
    if check.first():
        return season
    fallback = await session.execute(
        select(PlayerPoints.season)
        .where(PlayerPoints.period == "full_season")
        .order_by(PlayerPoints.season.desc())
        .limit(1)
    )
    row = fallback.first()
    return row[0] if row else season


@router.get("/trades")
async def trades(request: Request):
    all_values = []

    async with async_session() as session:
        season = await _resolve_season(session)

        # ------------------------------------------------------------------
        # Build a roster ownership lookup: player_id -> (is_my_team, team_name)
        # ------------------------------------------------------------------
        roster_result = await session.execute(
            select(Roster.player_id, Roster.is_my_team, Roster.team_name, Roster.team_id)
        )
        roster_rows = roster_result.all()
        ownership_lookup: dict[int, tuple[bool, str, str]] = {}
        for pid, is_mine, tname, tid in roster_rows:
            ownership_lookup[pid] = (is_mine, tname, tid)

        # ------------------------------------------------------------------
        # Trade value rankings
        # ------------------------------------------------------------------
        pp_result = await session.execute(
            select(PlayerPoints, Player)
            .join(Player, PlayerPoints.player_id == Player.id)
            .where(
                PlayerPoints.season == season,
                PlayerPoints.period == "full_season",
            )
            .order_by(PlayerPoints.surplus_value.desc())
            .limit(50)
        )
        pp_rows = pp_result.all()

        if pp_rows:
            for pp, player in pp_rows:
                own = ownership_lookup.get(player.id)
                if own:
                    roster_side = "a" if own[0] else "b"
                else:
                    roster_side = None
                all_values.append({
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team,
                    "position": player.position,
                    "player_type": pp.player_type,
                    "surplus_value": round(pp.surplus_value or 0, 1),
                    "projected_points": round(pp.projected_ros_points or 0, 1),
                    "actual_points": round(pp.actual_points or 0, 1),
                    "steamer_ros_points": round(pp.steamer_ros_points or 0, 1),
                    "positional_rank": pp.positional_rank or 0,
                    "points_per_pa": round(pp.points_per_pa, 3) if pp.points_per_pa else None,
                    "points_per_ip": round(pp.points_per_ip, 2) if pp.points_per_ip else None,
                    "points_per_start": (
                        round(pp.points_per_start, 1) if pp.points_per_start else None
                    ),
                    "points_per_appearance": (
                        round(pp.points_per_appearance, 1) if pp.points_per_appearance else None
                    ),
                    "z_score_total": round(pp.surplus_value or 0, 1),  # compat with template
                    "scoring_type": "points",
                    "roster_side": roster_side,
                })
        else:
            hitter_values, pitcher_values = await calculate_trade_values(session, season)
            if hitter_values or pitcher_values:
                await store_trade_values(session, hitter_values, pitcher_values)
                await session.commit()
            all_values = sorted(
                hitter_values + pitcher_values,
                key=lambda v: v.get("surplus_value", 0),
                reverse=True,
            )[:50]
            for v in all_values:
                v["scoring_type"] = "roto"
                own = ownership_lookup.get(v.get("player_id"))
                v["roster_side"] = ("a" if own[0] else "b") if own else None

        # ------------------------------------------------------------------
        # 1. My team roster
        # ------------------------------------------------------------------
        my_stmt = (
            select(Player, Roster, PlayerPoints)
            .join(Roster, Roster.player_id == Player.id)
            .outerjoin(
                PlayerPoints,
                and_(
                    PlayerPoints.player_id == Player.id,
                    PlayerPoints.season == season,
                    PlayerPoints.period == "full_season",
                ),
            )
            .where(Roster.is_my_team.is_(True))
        )
        my_result = await session.execute(my_stmt)
        my_rows = my_result.all()

        my_roster = [
            {
                "id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "roster_position": roster.roster_position,
                "projected_points": round(pp.projected_ros_points or 0, 1) if pp else 0,
                "surplus_value": round(pp.surplus_value or 0, 1) if pp else 0,
            }
            for player, roster, pp in my_rows
        ]
        my_roster.sort(key=_pos_sort_key)

        # ------------------------------------------------------------------
        # 2. Opponent teams
        # ------------------------------------------------------------------
        opp_teams_result = await session.execute(
            select(Roster.team_id, Roster.team_name)
            .where(Roster.is_my_team.is_(False))
            .distinct()
            .order_by(Roster.team_name)
        )
        opponent_teams = [
            {"team_id": tid, "team_name": tname}
            for tid, tname in opp_teams_result.all()
        ]

        # ------------------------------------------------------------------
        # 3. Opponent rosters (dict keyed by team_id)
        # ------------------------------------------------------------------
        opp_stmt = (
            select(Player, Roster, PlayerPoints)
            .join(Roster, Roster.player_id == Player.id)
            .outerjoin(
                PlayerPoints,
                and_(
                    PlayerPoints.player_id == Player.id,
                    PlayerPoints.season == season,
                    PlayerPoints.period == "full_season",
                ),
            )
            .where(Roster.is_my_team.is_(False))
        )
        opp_result = await session.execute(opp_stmt)
        opp_rows = opp_result.all()

        opponent_rosters: dict[str, list[dict]] = defaultdict(list)
        for player, roster, pp in opp_rows:
            opponent_rosters[roster.team_id].append({
                "id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "roster_position": roster.roster_position,
                "projected_points": round(pp.projected_ros_points or 0, 1) if pp else 0,
                "surplus_value": round(pp.surplus_value or 0, 1) if pp else 0,
            })
        # Sort each opponent roster by position order
        for tid in opponent_rosters:
            opponent_rosters[tid].sort(key=_pos_sort_key)
        opponent_rosters = dict(opponent_rosters)  # convert from defaultdict

        # ------------------------------------------------------------------
        # 4. Roster ownership map for rankings
        # ------------------------------------------------------------------
        roster_ownership: dict[int, dict] = {}
        for player, roster, pp in my_rows:
            roster_ownership[player.id] = {
                "side": "a",
                "fantasy_team": roster.team_name,
            }
        for player, roster, pp in opp_rows:
            roster_ownership[player.id] = {
                "side": "b",
                "fantasy_team": roster.team_name,
            }

    return templates.TemplateResponse(
        request,
        "trades.html",
        {
            "trade_values": all_values,
            "season": season,
            "my_roster": my_roster,
            "opponent_teams": opponent_teams,
            "opponent_rosters": opponent_rosters,
            "roster_ownership": roster_ownership,
        },
    )


@router.post("/api/trades/analyze")
async def analyze_trade(
    request: Request,
    side_a: str = Form(...),
    side_b: str = Form(...),
):
    """HTMX endpoint: evaluate a trade and return a partial result."""
    # Parse comma-separated player IDs
    try:
        side_a_ids = [int(x.strip()) for x in side_a.split(",") if x.strip()]
        side_b_ids = [int(x.strip()) for x in side_b.split(",") if x.strip()]
    except ValueError:
        return templates.TemplateResponse(
            request,
            "partials/trade_result.html",
            {"error": "Invalid player IDs"},
        )

    async with async_session() as session:
        season = await _resolve_season(session)
        result = await evaluate_trade(session, side_a_ids, side_b_ids, season)

    return templates.TemplateResponse(
        request,
        "partials/trade_result.html",
        {"trade": result},
    )


@router.post("/api/trades/ai-suggest")
async def ai_suggest_trades(request: Request):
    """HTMX endpoint: AI scans all opponents' rosters and suggests trades."""
    try:
        async with async_session() as session:
            season = await _resolve_season(session)
            analysis_text = await suggest_trades_ai(session, season)
    except Exception as e:
        logger.error(f"AI trade suggestions failed: {e}", exc_info=True)
        analysis_text = ""

    return templates.TemplateResponse(
        request,
        "partials/trade_suggestions.html",
        {"analysis": analysis_text},
    )


@router.post("/api/trades/ai-analyze")
async def ai_analyze_trade(
    request: Request,
    side_a: str = Form(...),
    side_b: str = Form(...),
):
    """HTMX endpoint: AI analysis of a specific proposed trade."""
    try:
        side_a_ids = [int(x.strip()) for x in side_a.split(",") if x.strip()]
        side_b_ids = [int(x.strip()) for x in side_b.split(",") if x.strip()]
    except ValueError:
        return templates.TemplateResponse(
            request,
            "partials/trade_ai_analysis.html",
            {"analysis": ""},
        )

    try:
        async with async_session() as session:
            season = await _resolve_season(session)
            evaluation = await evaluate_trade(session, side_a_ids, side_b_ids, season)
            analysis_text = await analyze_trade_ai(session, evaluation, season)
    except Exception as e:
        logger.error(f"AI trade analysis failed: {e}", exc_info=True)
        analysis_text = ""

    return templates.TemplateResponse(
        request,
        "partials/trade_ai_analysis.html",
        {"analysis": analysis_text},
    )


def _headshot_url(player: Player) -> str | None:
    if not player.mlbam_id:
        return None
    return (
        f"https://img.mlbstatic.com/mlb-photos/image/upload/"
        f"d_people:generic:headshot:67:current.png/"
        f"w_213,q_auto:best/v1/people/{player.mlbam_id}/headshot/67/current"
    )


@router.get("/api/trades/search/my-team")
async def search_my_team(
    q: str = Query(..., min_length=1),
    position: str | None = Query(None),
    limit: int = Query(10, ge=1, le=20),
):
    """Search players on my fantasy team roster."""
    async with async_session() as session:
        stmt = (
            select(Player, Roster)
            .join(Roster, Roster.player_id == Player.id)
            .where(Roster.is_my_team.is_(True))
            .where(Player.name.ilike(f"%{q}%"))
        )
        if position:
            stmt = stmt.where(Player.position.ilike(f"%{position}%"))
        stmt = stmt.order_by(Player.name).limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

    return JSONResponse([
        {
            "id": player.id,
            "name": player.name,
            "team": player.team,
            "position": player.position,
            "headshot_url": _headshot_url(player),
            "team_name": roster.team_name,
        }
        for player, roster in rows
    ])


@router.get("/api/trades/search/opponents")
async def search_opponents(
    q: str = Query(..., min_length=1),
    position: str | None = Query(None),
    limit: int = Query(10, ge=1, le=20),
):
    """Search players on opponent fantasy team rosters."""
    async with async_session() as session:
        stmt = (
            select(Player, Roster)
            .join(Roster, Roster.player_id == Player.id)
            .where(Roster.is_my_team.is_(False))
            .where(Player.name.ilike(f"%{q}%"))
        )
        if position:
            stmt = stmt.where(Player.position.ilike(f"%{position}%"))
        stmt = stmt.order_by(Player.name).limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

    return JSONResponse([
        {
            "id": player.id,
            "name": player.name,
            "team": player.team,
            "position": player.position,
            "headshot_url": _headshot_url(player),
            "team_name": roster.team_name,
            "fantasy_team": roster.team_name,
        }
        for player, roster in rows
    ])
