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
from app.models.player_points import PlayerPoints
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
    request: Request,
    q: str = Query("", min_length=1, max_length=100),
    limit: int = Query(15, le=100),
):
    """Search players by name for autocomplete dropdown."""
    async with async_session() as session:
        query = select(Player).where(Player.name.ilike(f"%{q}%")).order_by(Player.name).limit(limit)
        result = await session.execute(query)
        players = result.scalars().all()

        # Build ownership lookup
        roster_result = await session.execute(
            select(Roster.player_id, Roster.team_name, Roster.is_my_team)
        )
        ownership = {pid: (tname, mine) for pid, tname, mine in roster_result.all()}

        # Attach ownership to each player for template
        players_with_owner = []
        for p in players:
            own = ownership.get(p.id)
            players_with_owner.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "team": p.team,
                    "position": p.position,
                    "fantasy_team": own[0] if own else None,
                    "is_my_team": own[1] if own else False,
                }
            )

        return templates.TemplateResponse(
            request,
            "partials/search_results.html",
            {"players": players_with_owner, "query": q},
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
            select(StatcastSummary.season).where(StatcastSummary.player_id == player_id).distinct()
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
    highlight_player_id: int | None = Query(None),
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

        # Ensure highlighted player is in the data even if below threshold
        if highlight_player_id and not any(d["player_id"] == highlight_player_id for d in data):
            hl_result = await session.execute(
                select(StatcastSummary, Player)
                .join(Player)
                .where(
                    StatcastSummary.season == season,
                    StatcastSummary.period == "full_season",
                    StatcastSummary.player_type == "batter",
                    Player.id == highlight_player_id,
                )
            )
            row = hl_result.first()
            if row:
                sc, player = row
                x_val = getattr(sc, x_stat, None)
                y_val = getattr(sc, y_stat, None)
                if x_val is not None and y_val is not None:
                    ri = roster_map.get(player.id, {})
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
                            "is_my_team": ri.get("is_my_team", False),
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
    highlight_player_id: int | None = Query(None),
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
        trimmed = data[:limit]

        # Ensure highlighted player is included
        if highlight_player_id and not any(d["player_id"] == highlight_player_id for d in trimmed):
            hl = next((d for d in data if d["player_id"] == highlight_player_id), None)
            if hl:
                trimmed.append(hl)

        return trimmed


@router.get("/charts/pitching-leaders")
async def chart_pitching_leaders(
    season: int | None = Query(None),
    stat: str = Query("fip"),
    limit: int = Query(30),
    highlight_player_id: int | None = Query(None),
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
        trimmed = data[:limit]

        # Ensure highlighted player is included
        if highlight_player_id and not any(d["player_id"] == highlight_player_id for d in trimmed):
            hl = next((d for d in data if d["player_id"] == highlight_player_id), None)
            if hl:
                trimmed.append(hl)

        return trimmed


@router.get("/charts/luck-scatter")
async def chart_luck_scatter(
    season: int | None = Query(None),
    min_pa: int = Query(50),
    highlight_player_id: int | None = Query(None),
):
    """Return JSON for xwOBA vs actual wOBA luck chart (joins Statcast + Batting)."""
    if not season:
        season = default_season()

    async with async_session() as session:
        roster_map = await _get_roster_map(session)

        query = (
            select(StatcastSummary, BattingStats, Player)
            .join(Player, StatcastSummary.player_id == Player.id)
            .join(
                BattingStats,
                (BattingStats.player_id == StatcastSummary.player_id)
                & (BattingStats.season == StatcastSummary.season)
                & (BattingStats.period == StatcastSummary.period),
            )
            .where(
                StatcastSummary.season == season,
                StatcastSummary.period == "full_season",
                StatcastSummary.player_type == "batter",
            )
        )
        if min_pa > 0:
            query = query.where(StatcastSummary.pa >= min_pa)

        result = await session.execute(query)
        seen: set[int] = set()
        data = []
        for sc, bat, player in result.all():
            if player.id in seen:
                continue
            seen.add(player.id)
            if sc.xwoba is None or bat.woba is None:
                continue
            roster_info = roster_map.get(player.id, {})
            data.append(
                {
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team,
                    "position": player.position,
                    "x": round(sc.xwoba, 3),
                    "y": round(bat.woba, 3),
                    "pa": sc.pa,
                    "is_my_team": roster_info.get("is_my_team", False),
                    "is_rostered": player.id in roster_map,
                }
            )

        # Ensure highlighted player is included
        if highlight_player_id and not any(d["player_id"] == highlight_player_id for d in data):
            hl_result = await session.execute(
                select(StatcastSummary, BattingStats, Player)
                .join(Player, StatcastSummary.player_id == Player.id)
                .join(
                    BattingStats,
                    (BattingStats.player_id == StatcastSummary.player_id)
                    & (BattingStats.season == StatcastSummary.season)
                    & (BattingStats.period == StatcastSummary.period),
                )
                .where(
                    StatcastSummary.season == season,
                    StatcastSummary.period == "full_season",
                    Player.id == highlight_player_id,
                )
            )
            row = hl_result.first()
            if row:
                sc, bat, player = row
                if sc.xwoba is not None and bat.woba is not None:
                    ri = roster_map.get(player.id, {})
                    data.append(
                        {
                            "player_id": player.id,
                            "name": player.name,
                            "team": player.team,
                            "position": player.position,
                            "x": round(sc.xwoba, 3),
                            "y": round(bat.woba, 3),
                            "pa": sc.pa,
                            "is_my_team": ri.get("is_my_team", False),
                            "is_rostered": player.id in roster_map,
                        }
                    )

        return data


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

    statcast_stats = {
        "xwoba",
        "xba",
        "xslg",
        "barrel_pct",
        "hard_hit_pct",
        "avg_exit_velo",
        "whiff_pct",
        "chase_pct",
    }

    async with async_session() as session:
        if stat in statcast_stats:
            query = (
                select(StatcastSummary, Player)
                .join(Player)
                .where(
                    StatcastSummary.season == season,
                    StatcastSummary.period == "full_season",
                    StatcastSummary.player_type == "batter",
                    StatcastSummary.pa >= 50,
                )
            )
            result = await session.execute(query)
            values = []
            highlight_value = None
            highlight_name = None
            for sc, player in result.all():
                val = getattr(sc, stat, None)
                if val is None:
                    continue
                values.append(val)
                if highlight_player_id and player.id == highlight_player_id:
                    highlight_value = val
                    highlight_name = player.name
        elif player_type == "batter":
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


@router.get("/charts/player-spotlight")
async def chart_player_spotlight(
    player_id: int = Query(...),
    season: int | None = Query(None),
):
    """Return comprehensive spotlight data for a highlighted player.

    Combines player info, key stats, rolling trends, percentiles, and radar data.
    """
    from app.services.comparison_service import (
        HITTER_BATTING_STATS,
        HITTER_STATCAST_STATS,
        PITCHER_STATS,
        _compute_percentile,
        _get_batting_distribution,
        _get_pitching_distribution,
        _get_statcast_distribution,
    )

    if not season:
        season = default_season()

    async with async_session() as session:  # noqa: F841 (bisect imported above)
        # Player info
        player = await session.get(Player, player_id)
        if not player:
            return {"error": "Player not found"}

        # Ownership
        roster_result = await session.execute(select(Roster).where(Roster.player_id == player_id))
        roster_row = roster_result.scalar_one_or_none()
        fantasy_team = roster_row.team_name if roster_row else None
        is_my_team = roster_row.is_my_team if roster_row else False

        # Determine player type from stats
        bat_result = await session.execute(
            select(BattingStats).where(
                BattingStats.player_id == player_id,
                BattingStats.season == season,
                BattingStats.period == "full_season",
            )
        )
        bat = bat_result.scalar_one_or_none()

        pitch_result = await session.execute(
            select(PitchingStats).where(
                PitchingStats.player_id == player_id,
                PitchingStats.season == season,
                PitchingStats.period == "full_season",
            )
        )
        pitch = pitch_result.scalar_one_or_none()

        # Statcast
        sc_result = await session.execute(
            select(StatcastSummary).where(
                StatcastSummary.player_id == player_id,
                StatcastSummary.season == season,
                StatcastSummary.period == "full_season",
            )
        )
        sc = sc_result.scalar_one_or_none()

        is_hitter = bat is not None and (bat.pa or 0) > 0
        player_type = "hitter" if is_hitter else "pitcher"

        # ── Summary stats ──
        summary = []
        if is_hitter and bat:
            for label, attr, decimals, threshold in [
                ("PA", "pa", 0, None),
                ("AVG", "avg", 3, 0.260),
                ("OBP", "obp", 3, 0.320),
                ("SLG", "slg", 3, 0.400),
                ("OPS", "ops", 3, 0.750),
                ("wRC+", "wrc_plus", 0, 100),
                ("wOBA", "woba", 3, 0.320),
                ("ISO", "iso", 3, 0.150),
                ("HR", "hr", 0, None),
                ("SB", "sb", 0, None),
            ]:
                val = getattr(bat, attr, None)
                if val is not None:
                    color = "text-gray-200"
                    if threshold is not None:
                        color = "text-green-400" if val >= threshold else "text-red-400"
                    summary.append(
                        {
                            "label": label,
                            "value": val,
                            "decimals": decimals,
                            "color": color,
                        }
                    )
        elif pitch:
            for label, attr, decimals, threshold, lower in [
                ("IP", "ip", 1, None, False),
                ("ERA", "era", 2, 4.00, True),
                ("FIP", "fip", 2, 4.00, True),
                ("WHIP", "whip", 2, 1.30, True),
                ("K/9", "k_per_9", 1, 8.0, False),
                ("BB/9", "bb_per_9", 1, 3.5, True),
                ("K-BB%", "k_bb_pct", 1, 12.0, False),
                ("W", "w", 0, None, False),
                ("SV", "sv", 0, None, False),
                ("QS", "qs", 0, None, False),
            ]:
                val = getattr(pitch, attr, None)
                if val is not None:
                    color = "text-gray-200"
                    if threshold is not None:
                        if lower:
                            color = "text-green-400" if val <= threshold else "text-red-400"
                        else:
                            color = "text-green-400" if val >= threshold else "text-red-400"
                    summary.append(
                        {
                            "label": label,
                            "value": val,
                            "decimals": decimals,
                            "color": color,
                        }
                    )

        # ── Rolling trends ──
        periods = ["full_season", "last_30", "last_14", "last_7"]
        period_labels = ["Full Season", "Last 30", "Last 14", "Last 7"]
        rolling_batting = {}
        rolling_pitching = {}

        if is_hitter:
            for period in periods:
                r = await session.execute(
                    select(BattingStats).where(
                        BattingStats.player_id == player_id,
                        BattingStats.season == season,
                        BattingStats.period == period,
                    )
                )
                b = r.scalar_one_or_none()
                for stat_name in (
                    "wrc_plus",
                    "woba",
                    "avg",
                    "obp",
                    "slg",
                    "ops",
                    "iso",
                ):
                    rolling_batting.setdefault(stat_name, []).append(
                        getattr(b, stat_name, None) if b else None
                    )
        else:
            for period in periods:
                r = await session.execute(
                    select(PitchingStats).where(
                        PitchingStats.player_id == player_id,
                        PitchingStats.season == season,
                        PitchingStats.period == period,
                    )
                )
                p = r.scalar_one_or_none()
                for stat_name in ("era", "fip", "whip", "k_per_9", "bb_per_9"):
                    rolling_pitching.setdefault(stat_name, []).append(
                        getattr(p, stat_name, None) if p else None
                    )

        rolling = {
            "periods": period_labels,
            "batting": rolling_batting,
            "pitching": rolling_pitching,
        }

        # ── Percentiles ──
        percentiles = []
        if is_hitter and bat:
            bat_dist = await _get_batting_distribution(session, season)
            for display_name, attr, lower in HITTER_BATTING_STATS:
                val = getattr(bat, attr, None)
                if val is not None and attr in bat_dist:
                    pct, rank, total = _compute_percentile(val, bat_dist[attr], lower)
                    percentiles.append(
                        {
                            "display_name": display_name,
                            "attr": attr,
                            "value": round(val, 3) if isinstance(val, float) else val,
                            "percentile": pct,
                            "rank": rank,
                            "total": total,
                        }
                    )
            if sc:
                sc_dist = await _get_statcast_distribution(session, season, "batter")
                for display_name, attr, lower in HITTER_STATCAST_STATS:
                    val = getattr(sc, attr, None)
                    if val is not None and attr in sc_dist:
                        pct, rank, total = _compute_percentile(val, sc_dist[attr], lower)
                        percentiles.append(
                            {
                                "display_name": display_name,
                                "attr": attr,
                                "value": round(val, 3) if isinstance(val, float) else val,
                                "percentile": pct,
                            }
                        )
        elif pitch:
            pitch_dist = await _get_pitching_distribution(session, season)
            for display_name, attr, lower in PITCHER_STATS:
                val = getattr(pitch, attr, None)
                if val is not None and attr in pitch_dist:
                    pct, rank, total = _compute_percentile(val, pitch_dist[attr], lower)
                    percentiles.append(
                        {
                            "display_name": display_name,
                            "attr": attr,
                            "value": round(val, 3) if isinstance(val, float) else val,
                            "percentile": pct,
                        }
                    )

        # ── Radar data ──
        radar = None
        if is_hitter and bat:
            cats = ["wRC+", "OPS", "ISO", "BB%", "K% (inv)", "SB"]
            vals = [
                min((bat.wrc_plus or 0) / 150, 1.5),
                min((bat.ops or 0) / 1.0, 1.5),
                min((bat.iso or 0) / 0.250, 1.5),
                min((bat.bb_pct or 0) / 0.15, 1.5),
                max(1.0 - (bat.k_pct or 0.25) / 0.35, 0),
                min((bat.sb or 0) / 30, 1.5),
            ]
            avg_vals = [0.67, 0.75, 0.6, 0.53, 0.57, 0.33]
            radar = {
                "categories": cats,
                "values": [round(v, 2) for v in vals],
                "league_avg": avg_vals,
            }
        elif pitch:
            cats = ["K/9", "BB/9 (inv)", "ERA (inv)", "FIP (inv)", "WHIP (inv)", "IP"]
            vals = [
                min((pitch.k_per_9 or 0) / 13, 1.5),
                max(1.0 - (pitch.bb_per_9 or 3) / 6, 0),
                max(1.0 - (pitch.era or 4) / 6, 0),
                max(1.0 - (pitch.fip or 4) / 6, 0),
                max(1.0 - (pitch.whip or 1.3) / 2.0, 0),
                min((pitch.ip or 0) / 200, 1.5),
            ]
            avg_vals = [0.62, 0.50, 0.33, 0.33, 0.35, 0.40]
            radar = {
                "categories": cats,
                "values": [round(v, 2) for v in vals],
                "league_avg": avg_vals,
            }

        return {
            "player": {
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "fantasy_team": fantasy_team,
                "is_my_team": is_my_team,
            },
            "type": player_type,
            "summary": summary,
            "rolling": rolling,
            "percentiles": percentiles,
            "radar": radar,
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


# ── League Points API Endpoints ──


@router.get("/league/config")
async def league_config():
    """Return the league configuration including roster slots and scoring rules."""
    from app.league_config import LEAGUE_CONFIG

    return LEAGUE_CONFIG


@router.get("/points/calculator")
async def points_calculator(
    # Pitcher params
    IP: float = Query(0),
    K: float = Query(0),
    ER: float = Query(0),
    H: float = Query(0),
    BB: float = Query(0),
    QS: float = Query(0),
    SV: float = Query(0),
    HLD: float = Query(0),
    HBP: float = Query(0),
    # Batter params
    R: float = Query(0),
    singles: float = Query(0, alias="1B"),
    doubles: float = Query(0, alias="2B"),
    triples: float = Query(0, alias="3B"),
    HR: float = Query(0),
    RBI: float = Query(0),
    SB: float = Query(0),
    CS: float = Query(0),
    bat_BB: float = Query(0, alias="bat_BB"),
    bat_K: float = Query(0, alias="bat_K"),
    bat_HBP: float = Query(0, alias="bat_HBP"),
    # Mode
    mode: str = Query("auto"),  # "pitcher", "batter", or "auto"
):
    """Calculate fantasy points for a stat line.

    Example: /api/points/calculator?IP=7&K=8&ER=2&H=5&BB=1&QS=1
    """
    from app.services.points_service import get_points_breakdown

    if mode == "pitcher" or (mode == "auto" and IP > 0):
        stats = {
            "IP": IP,
            "K": K,
            "ER": ER,
            "H": H,
            "BB": BB,
            "QS": QS,
            "SV": SV,
            "HLD": HLD,
            "HBP": HBP,
        }
        breakdown = get_points_breakdown(stats, is_pitcher=True, is_reliever=(SV > 0 or HLD > 0))
        return {
            "mode": "pitcher",
            "stats": stats,
            "points": breakdown["total"],
            "breakdown": breakdown,
        }
    else:
        stats = {
            "R": R,
            "1B": singles,
            "2B": doubles,
            "3B": triples,
            "HR": HR,
            "RBI": RBI,
            "SB": SB,
            "CS": CS,
            "BB": bat_BB,
            "K": bat_K,
            "HBP": bat_HBP,
        }
        breakdown = get_points_breakdown(stats, is_pitcher=False)
        return {
            "mode": "batter",
            "stats": stats,
            "points": breakdown["total"],
            "breakdown": breakdown,
        }


@router.get("/points/leaders")
async def points_leaders(
    season: int | None = Query(None),
    player_type: str = Query("hitter"),
    period: str = Query("full_season"),
    limit: int = Query(20),
):
    """Points leaders for this scoring system."""
    from app.models.player import Player
    from app.models.player_points import PlayerPoints

    if not season:
        season = default_season()

    async with async_session() as session:
        result = await session.execute(
            select(PlayerPoints, Player)
            .join(Player, PlayerPoints.player_id == Player.id)
            .where(
                PlayerPoints.season == season,
                PlayerPoints.period == period,
                PlayerPoints.player_type == player_type,
            )
            .order_by(PlayerPoints.actual_points.desc())
            .limit(limit)
        )

        leaders = []
        for pp, player in result.all():
            leaders.append(
                {
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team,
                    "position": player.position,
                    "actual_points": pp.actual_points,
                    "projected_ros_points": pp.projected_ros_points,
                    "points_per_pa": pp.points_per_pa,
                    "points_per_ip": pp.points_per_ip,
                    "points_per_start": pp.points_per_start,
                    "points_per_appearance": pp.points_per_appearance,
                    "positional_rank": pp.positional_rank,
                    "surplus_value": pp.surplus_value,
                }
            )

        return leaders


@router.get("/points/per-start-leaders")
async def per_start_leaders(
    season: int | None = Query(None),
    period: str = Query("full_season"),
    limit: int = Query(20),
):
    """Starting pitchers ranked by average points per start."""
    from app.models.player import Player
    from app.models.player_points import PlayerPoints

    if not season:
        season = default_season()

    async with async_session() as session:
        result = await session.execute(
            select(PlayerPoints, Player)
            .join(Player, PlayerPoints.player_id == Player.id)
            .where(
                PlayerPoints.season == season,
                PlayerPoints.period == period,
                PlayerPoints.player_type == "pitcher",
                PlayerPoints.points_per_start.isnot(None),
            )
            .order_by(PlayerPoints.points_per_start.desc())
            .limit(limit)
        )

        return [
            {
                "player_id": player.id,
                "name": player.name,
                "team": player.team,
                "points_per_start": pp.points_per_start,
                "actual_points": pp.actual_points,
                "projected_ros_points": pp.projected_ros_points,
            }
            for pp, player in result.all()
        ]


@router.get("/points/reliever-rankings")
async def reliever_rankings(
    season: int | None = Query(None),
    limit: int = Query(30),
):
    """Relievers ranked by this scoring system's valuation."""
    from app.models.pitching_stats import PitchingStats
    from app.models.player import Player
    from app.models.player_points import PlayerPoints

    if not season:
        season = default_season()

    async with async_session() as session:
        result = await session.execute(
            select(PlayerPoints, Player, PitchingStats)
            .join(Player, PlayerPoints.player_id == Player.id)
            .join(
                PitchingStats,
                (PitchingStats.player_id == Player.id)
                & (PitchingStats.season == PlayerPoints.season)
                & (PitchingStats.period == "full_season"),
            )
            .where(
                PlayerPoints.season == season,
                PlayerPoints.period == "full_season",
                PlayerPoints.player_type == "pitcher",
                PlayerPoints.points_per_appearance.isnot(None),
            )
            .order_by(PlayerPoints.projected_ros_points.desc())
            .limit(limit)
        )

        relievers = []
        for pp, player, ps in result.all():
            sv = int(ps.sv or 0)
            hld = int(ps.hld or 0)
            role = "closer" if sv > 0 else ("setup" if hld > 0 else "middle")
            relievers.append(
                {
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team,
                    "role": role,
                    "sv": sv,
                    "hld": hld,
                    "actual_points": pp.actual_points,
                    "projected_ros_points": pp.projected_ros_points,
                    "points_per_appearance": pp.points_per_appearance,
                    "surplus_value": pp.surplus_value,
                }
            )

        return relievers


@router.get("/points/search")
async def search_player_points(
    q: str = Query("", min_length=2, max_length=100),
    player_type: str = Query("hitter"),
    season: int | None = Query(None),
):
    """Search PlayerPoints by player name. Returns JSON for table insertion.

    Used by the client-side table-sort.js to surface players not in the
    default top-N list.
    """
    selected_season = season or default_season()

    async with async_session() as session:
        result = await session.execute(
            select(PlayerPoints, Player)
            .join(Player, PlayerPoints.player_id == Player.id)
            .where(
                PlayerPoints.season == selected_season,
                PlayerPoints.period == "full_season",
                PlayerPoints.player_type == player_type,
                Player.name.ilike(f"%{q}%"),
            )
            .order_by(PlayerPoints.projected_ros_points.desc())
            .limit(15)
        )
        rows = result.all()

        # Ownership lookup
        roster_result = await session.execute(
            select(Roster.player_id, Roster.team_name, Roster.is_my_team)
        )
        ownership = {pid: (tname, mine) for pid, tname, mine in roster_result.all()}

    players = []
    for pp, player in rows:
        own = ownership.get(player.id)
        players.append(
            {
                "name": player.name,
                "team": player.team or "",
                "position": player.position or "",
                "projected_points": round(pp.projected_ros_points or 0, 1),
                "actual_points": round(pp.actual_points or 0, 1),
                "points_per_pa": round(pp.points_per_pa or 0, 3),
                "points_per_start": (
                    round(pp.points_per_start or 0, 1) if pp.points_per_start else None
                ),
                "points_per_ip": (round(pp.points_per_ip or 0, 2) if pp.points_per_ip else None),
                "points_per_appearance": (
                    round(pp.points_per_appearance or 0, 1) if pp.points_per_appearance else None
                ),
                "surplus_value": round(pp.surplus_value or 0, 1),
                "positional_rank": pp.positional_rank or 0,
                "fantasy_team": own[0].split()[0] if own else "FA",
                "is_my_team": own[1] if own else False,
            }
        )

    return players
