from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, union

from app.config import default_season
from app.database import async_session
from app.etl.pipeline import run_pipeline, run_stats_pipeline
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.roster import Roster
from app.models.statcast_summary import StatcastSummary
from app.models.sync_log import SyncLog

router = APIRouter(prefix="/api")
templates = Jinja2Templates(directory="app/templates")


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/sync")
async def sync_data(request: Request):
    """Run the ETL pipeline and return an HTMX partial with the result."""
    result = await run_pipeline()
    return templates.TemplateResponse(request, "partials/sync_result.html", {"result": result})


@router.post("/sync/stats")
async def sync_stats(request: Request, season: int | None = Query(None)):
    """Run the FanGraphs + Statcast stats pipeline.

    Args:
        season: MLB season year to fetch. Defaults to current year (or previous
                year if before April).
    """
    result = await run_stats_pipeline(season=season)
    return templates.TemplateResponse(
        request, "partials/stats_sync_result.html", {"result": result}
    )


@router.post("/sync/stats/multi")
async def sync_stats_multi(request: Request):
    """Sync stats for multiple seasons. Reads 'seasons' from form data."""
    form = await request.form()
    raw_seasons = form.getlist("seasons")
    if not raw_seasons:
        return templates.TemplateResponse(
            request,
            "partials/stats_sync_result.html",
            {"result": {"status": "error", "message": "No seasons selected"}},
        )

    seasons = sorted({int(s) for s in raw_seasons if s.isdigit()})
    results = []
    for s in seasons:
        result = await run_stats_pipeline(season=s)
        results.append(result)

    return templates.TemplateResponse(
        request,
        "partials/multi_sync_result.html",
        {"results": results, "seasons": seasons},
    )


@router.get("/sync/status")
async def sync_status():
    """Return the most recent sync log entry."""
    async with async_session() as session:
        query = select(SyncLog).order_by(SyncLog.id.desc()).limit(1)
        result = await session.execute(query)
        last_sync = result.scalar_one_or_none()

        if last_sync:
            return {
                "status": last_sync.status,
                "started_at": str(last_sync.started_at),
                "completed_at": str(last_sync.completed_at) if last_sync.completed_at else None,
                "records_processed": last_sync.records_processed,
                "error_message": last_sync.error_message,
            }
        return {"status": "never_synced"}


@router.get("/players/search")
async def search_players(
    request: Request, q: str = Query("", min_length=1), limit: int = Query(15)
):
    """Search players by name for autocomplete dropdown."""
    async with async_session() as session:
        query = select(Player).where(Player.name.ilike(f"%{q}%")).order_by(Player.name).limit(limit)
        result = await session.execute(query)
        players = result.scalars().all()
        return templates.TemplateResponse(
            request, "partials/search_results.html", {"players": players, "query": q}
        )


@router.get("/player/{player_id}")
async def player_detail(request: Request, player_id: int, season: int | None = Query(None)):
    """Return an HTML partial with a player's full stats for the modal popup."""
    async with async_session() as session:
        player = await session.get(Player, player_id)
        if not player:
            return templates.TemplateResponse(
                request, "partials/player_card.html", {"error": "Player not found"}
            )

        # Get available seasons for this player (from all stat sources)
        bat_seasons = (
            select(BattingStats.season).where(BattingStats.player_id == player_id).distinct()
        )
        pitch_seasons = (
            select(PitchingStats.season).where(PitchingStats.player_id == player_id).distinct()
        )
        sc_seasons = (
            select(StatcastSummary.season)
            .where(StatcastSummary.player_id == player_id)
            .distinct()
        )
        combined = union(bat_seasons, pitch_seasons, sc_seasons).subquery()
        seasons_result = await session.execute(
            select(combined.c.season).order_by(combined.c.season.desc())
        )
        available_seasons = [row[0] for row in seasons_result.fetchall()]

        if not season:
            season = default_season()
            # If the default season has no data, fall back to latest available
            if available_seasons and season not in available_seasons:
                season = available_seasons[0]

        batting_result = await session.execute(
            select(BattingStats).where(
                BattingStats.player_id == player_id,
                BattingStats.season == season,
                BattingStats.period == "full_season",
            )
        )
        batting = batting_result.scalar_one_or_none()

        pitching_result = await session.execute(
            select(PitchingStats).where(
                PitchingStats.player_id == player_id,
                PitchingStats.season == season,
                PitchingStats.period == "full_season",
            )
        )
        pitching = pitching_result.scalar_one_or_none()

        statcast_bat_result = await session.execute(
            select(StatcastSummary).where(
                StatcastSummary.player_id == player_id,
                StatcastSummary.season == season,
                StatcastSummary.period == "full_season",
                StatcastSummary.player_type == "batter",
            )
        )
        statcast_bat = statcast_bat_result.scalar_one_or_none()

        statcast_pitch_result = await session.execute(
            select(StatcastSummary).where(
                StatcastSummary.player_id == player_id,
                StatcastSummary.season == season,
                StatcastSummary.period == "full_season",
                StatcastSummary.player_type == "pitcher",
            )
        )
        statcast_pitch = statcast_pitch_result.scalar_one_or_none()

        return templates.TemplateResponse(
            request,
            "partials/player_card.html",
            {
                "player": player,
                "batting": batting,
                "pitching": pitching,
                "statcast_bat": statcast_bat,
                "statcast_pitch": statcast_pitch,
                "season": season,
                "available_seasons": available_seasons,
            },
        )


# ── Chart JSON API Endpoints ──


async def _get_roster_map(session) -> dict[int, dict]:
    """Build a map of player_id -> roster info for chart overlays."""
    result = await session.execute(select(Roster))
    roster_map = {}
    for r in result.scalars().all():
        roster_map[r.player_id] = {"team_name": r.team_name, "is_my_team": r.is_my_team}
    return roster_map


@router.get("/charts/statcast-scatter")
async def chart_statcast_scatter(
    season: int | None = Query(None),
    x_stat: str = Query("avg_exit_velo"),
    y_stat: str = Query("barrel_pct"),
    min_pa: int = Query(50),
):
    """Return JSON for Statcast scatter plot."""
    if not season:
        season = default_season()

    valid_stats = {
        "avg_exit_velo",
        "max_exit_velo",
        "barrel_pct",
        "hard_hit_pct",
        "xba",
        "xslg",
        "xwoba",
        "sweet_spot_pct",
        "sprint_speed",
        "whiff_pct",
        "chase_pct",
    }
    if x_stat not in valid_stats or y_stat not in valid_stats:
        return JSONResponse({"error": "Invalid stat name"}, status_code=400)

    async with async_session() as session:
        roster_map = await _get_roster_map(session)

        query = (
            select(StatcastSummary, Player)
            .join(Player)
            .where(
                StatcastSummary.season == season,
                StatcastSummary.period == "full_season",
                StatcastSummary.player_type == "batter",
            )
        )
        if min_pa > 0:
            query = query.where(StatcastSummary.pa >= min_pa)

        result = await session.execute(query)
        data = []
        for sc, player in result.all():
            x_val = getattr(sc, x_stat, None)
            y_val = getattr(sc, y_stat, None)
            if x_val is None or y_val is None:
                continue
            roster_info = roster_map.get(player.id, {})
            data.append(
                {
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team,
                    "position": player.position,
                    "x": round(x_val, 3),
                    "y": round(y_val, 3),
                    "xwoba": round(sc.xwoba, 3) if sc.xwoba else None,
                    "pa": sc.pa,
                    "is_my_team": roster_info.get("is_my_team", False),
                    "is_rostered": player.id in roster_map,
                }
            )
        return data


@router.get("/charts/batting-leaders")
async def chart_batting_leaders(
    season: int | None = Query(None),
    stat: str = Query("wrc_plus"),
    limit: int = Query(30),
    position: str | None = Query(None),
):
    """Return JSON for batting leader charts."""
    if not season:
        season = default_season()

    valid_stats = {
        "wrc_plus",
        "woba",
        "iso",
        "babip",
        "k_pct",
        "bb_pct",
        "ops",
        "avg",
        "war",
        "hr",
        "sb",
    }
    if stat not in valid_stats:
        return JSONResponse({"error": "Invalid stat name"}, status_code=400)

    async with async_session() as session:
        roster_map = await _get_roster_map(session)

        query = (
            select(BattingStats, Player)
            .join(Player)
            .where(
                BattingStats.season == season,
                BattingStats.period == "full_season",
                BattingStats.pa >= 50,
            )
        )
        if position:
            query = query.where(Player.position.ilike(f"%{position}%"))

        result = await session.execute(query)
        data = []
        for bat, player in result.all():
            val = getattr(bat, stat, None)
            if val is None:
                continue
            roster_info = roster_map.get(player.id, {})
            data.append(
                {
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team,
                    "position": player.position,
                    "value": round(val, 3),
                    "pa": bat.pa,
                    "is_my_team": roster_info.get("is_my_team", False),
                    "is_rostered": player.id in roster_map,
                }
            )

        # Sort descending for most stats, ascending for k_pct
        reverse = stat != "k_pct"
        data.sort(key=lambda x: x["value"], reverse=reverse)
        return data[:limit]


@router.get("/charts/pitching-leaders")
async def chart_pitching_leaders(
    season: int | None = Query(None),
    stat: str = Query("fip"),
    limit: int = Query(30),
):
    """Return JSON for pitching leader charts."""
    if not season:
        season = default_season()

    valid_stats = {"era", "fip", "xfip", "siera", "k_per_9", "bb_per_9", "k_bb_pct", "whip", "war"}
    if stat not in valid_stats:
        return JSONResponse({"error": "Invalid stat name"}, status_code=400)

    async with async_session() as session:
        roster_map = await _get_roster_map(session)

        query = (
            select(PitchingStats, Player)
            .join(Player)
            .where(
                PitchingStats.season == season,
                PitchingStats.period == "full_season",
                PitchingStats.ip >= 20,
            )
        )
        result = await session.execute(query)
        data = []
        for pitch, player in result.all():
            val = getattr(pitch, stat, None)
            if val is None:
                continue
            roster_info = roster_map.get(player.id, {})
            data.append(
                {
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team,
                    "position": player.position,
                    "value": round(val, 3),
                    "ip": pitch.ip,
                    "is_my_team": roster_info.get("is_my_team", False),
                    "is_rostered": player.id in roster_map,
                }
            )

        # Lower is better for ERA, FIP, xFIP, SIERA, WHIP, BB/9
        lower_is_better = {"era", "fip", "xfip", "siera", "whip", "bb_per_9"}
        reverse = stat not in lower_is_better
        data.sort(key=lambda x: x["value"], reverse=reverse)
        return data[:limit]


@router.get("/charts/distribution")
async def chart_distribution(
    season: int | None = Query(None),
    stat: str = Query("wrc_plus"),
    player_type: str = Query("batter"),
    highlight_player_id: int | None = Query(None),
):
    """Return histogram data for league-wide stat distributions."""
    if not season:
        season = default_season()

    async with async_session() as session:
        if player_type == "batter":
            query = (
                select(BattingStats, Player)
                .join(Player)
                .where(
                    BattingStats.season == season,
                    BattingStats.period == "full_season",
                    BattingStats.pa >= 50,
                )
            )
            result = await session.execute(query)
            values = []
            highlight_value = None
            highlight_name = None
            for bat, player in result.all():
                val = getattr(bat, stat, None)
                if val is None:
                    continue
                values.append(val)
                if highlight_player_id and player.id == highlight_player_id:
                    highlight_value = val
                    highlight_name = player.name
        else:
            query = (
                select(PitchingStats, Player)
                .join(Player)
                .where(
                    PitchingStats.season == season,
                    PitchingStats.period == "full_season",
                    PitchingStats.ip >= 20,
                )
            )
            result = await session.execute(query)
            values = []
            highlight_value = None
            highlight_name = None
            for pitch, player in result.all():
                val = getattr(pitch, stat, None)
                if val is None:
                    continue
                values.append(val)
                if highlight_player_id and player.id == highlight_player_id:
                    highlight_value = val
                    highlight_name = player.name

        return {
            "values": [round(v, 3) for v in values],
            "highlight_value": round(highlight_value, 3) if highlight_value else None,
            "highlight_name": highlight_name,
            "stat": stat,
            "count": len(values),
        }


@router.get("/charts/rolling")
async def chart_rolling(
    player_id: int = Query(...),
    season: int | None = Query(None),
):
    """Return rolling stat trends across periods for a player."""
    if not season:
        season = default_season()

    periods = ["full_season", "last_30", "last_14", "last_7"]
    period_labels = ["Full Season", "Last 30", "Last 14", "Last 7"]

    async with async_session() as session:
        # Batting stats across periods
        bat_data = {}
        for period in periods:
            result = await session.execute(
                select(BattingStats).where(
                    BattingStats.player_id == player_id,
                    BattingStats.season == season,
                    BattingStats.period == period,
                )
            )
            bat = result.scalar_one_or_none()
            if bat:
                for stat_name in ("wrc_plus", "woba", "avg", "obp", "slg", "iso", "babip"):
                    if stat_name not in bat_data:
                        bat_data[stat_name] = []
                    bat_data[stat_name].append(getattr(bat, stat_name, None))

        # Pitching stats across periods
        pitch_data = {}
        for period in periods:
            result = await session.execute(
                select(PitchingStats).where(
                    PitchingStats.player_id == player_id,
                    PitchingStats.season == season,
                    PitchingStats.period == period,
                )
            )
            pitch = result.scalar_one_or_none()
            if pitch:
                for stat_name in ("era", "fip", "whip", "k_per_9", "bb_per_9"):
                    if stat_name not in pitch_data:
                        pitch_data[stat_name] = []
                    pitch_data[stat_name].append(getattr(pitch, stat_name, None))

        return {
            "periods": period_labels,
            "batting": bat_data,
            "pitching": pitch_data,
        }


# ── Projection API Endpoints ──


@router.get("/projections/compare")
async def projections_compare(
    players: str = Query(..., description="Comma-separated player IDs"),
    season: int | None = Query(None),
):
    """Return projection comparison data for multiple players."""
    from app.services.projection_service import get_projections_comparison

    if not season:
        season = default_season()

    player_ids = [int(pid.strip()) for pid in players.split(",") if pid.strip().isdigit()]
    if not player_ids or len(player_ids) > 6:
        return JSONResponse({"error": "Provide 1-6 comma-separated player IDs"}, status_code=400)

    async with async_session() as session:
        result = {}
        for pid in player_ids:
            player = await session.get(Player, pid)
            if player:
                projs = await get_projections_comparison(session, pid, season)
                result[pid] = {
                    "name": player.name,
                    "team": player.team,
                    "position": player.position,
                    "projections": projs,
                }
        return result


@router.get("/projections/blend")
async def projections_blend(
    request: Request,
    player_id: int = Query(...),
    season: int | None = Query(None),
    steamer: float = Query(0.30),
    zips: float = Query(0.25),
    atc: float = Query(0.25),
    thebat: float = Query(0.20),
):
    """Return blended projection with custom weights (for HTMX slider updates)."""
    from app.services.projection_service import BlendConfig, blend_external_projections

    if not season:
        season = default_season()

    config = BlendConfig(steamer=steamer, zips=zips, atc=atc, thebat=thebat)

    async with async_session() as session:
        blended = await blend_external_projections(session, player_id, season, config)
        player = await session.get(Player, player_id)
        return templates.TemplateResponse(
            request,
            "partials/projection_blend.html",
            {
                "blended": blended,
                "player": player,
                "weights": config.normalize().weights_dict(),
            },
        )


@router.get("/projections/buysell")
async def projections_buysell(
    season: int | None = Query(None),
    limit: int = Query(20),
):
    """Return top buy-low and sell-high candidates."""
    from app.services.projection_service import get_buy_sell_candidates

    if not season:
        season = default_season()

    async with async_session() as session:
        return await get_buy_sell_candidates(session, season, limit)
