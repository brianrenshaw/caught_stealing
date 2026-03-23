"""Player comparison routes.

Provides the comparison page and JSON/HTML-partial API endpoints
for the side-by-side player comparison tool.
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, union

from app.config import default_season
from app.database import async_session
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.statcast_summary import StatcastSummary
from app.services.comparison_service import (
    get_player_card,
    get_player_cards_batch,
    get_stat_leaders,
    search_players_json,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _get_available_seasons(session) -> list[int]:
    batting_seasons = select(BattingStats.season).distinct()
    pitching_seasons = select(PitchingStats.season).distinct()
    statcast_seasons = select(StatcastSummary.season).distinct()
    combined = union(batting_seasons, pitching_seasons, statcast_seasons).subquery()
    result = await session.execute(select(combined.c.season).order_by(combined.c.season.desc()))
    return [row[0] for row in result.all()]


# ── Page route ──


@router.get("/compare")
async def compare_page(
    request: Request,
    ids: str | None = Query(None),
    season: int | None = Query(None),
    tab: str = Query("overview"),
):
    """Render the comparison page. Pre-populates slots if ?ids= is provided."""
    async with async_session() as session:
        available_seasons = await _get_available_seasons(session)

        if season and season in available_seasons:
            selected_season = season
        elif available_seasons:
            selected_season = available_seasons[0]
        else:
            selected_season = default_season()

        # Pre-fetch basic player info for URL-provided IDs
        initial_players = []
        if ids:
            try:
                player_ids = [int(x.strip()) for x in ids.split(",") if x.strip()][:5]
            except ValueError:
                player_ids = []

            if player_ids:
                result = await session.execute(
                    select(Player).where(Player.id.in_(player_ids))
                )
                players = result.scalars().all()
                # Preserve order from URL
                player_map = {p.id: p for p in players}
                for pid in player_ids:
                    p = player_map.get(pid)
                    if p:
                        headshot = None
                        if p.mlbam_id:
                            headshot = (
                                f"https://img.mlbstatic.com/mlb-photos/image/upload/"
                                f"d_people:generic:headshot:67:current.png/"
                                f"w_213,q_auto:best/v1/people/{p.mlbam_id}/headshot/67/current"
                            )
                        initial_players.append(
                            {
                                "id": p.id,
                                "name": p.name,
                                "team": p.team,
                                "position": p.position,
                                "headshot_url": headshot,
                            }
                        )

        return templates.TemplateResponse(
            request,
            "compare.html",
            {
                "season": selected_season,
                "available_seasons": available_seasons,
                "initial_players": initial_players,
                "active_tab": tab,
            },
        )


# ── JSON API endpoints ──


@router.get("/api/compare/player-card/{player_id}")
async def api_player_card(
    player_id: int,
    season: int | None = Query(None),
):
    """Rich JSON player card for comparison tool."""
    async with async_session() as session:
        s = season or default_season()
        card = await get_player_card(session, player_id, s)
        if not card:
            return JSONResponse({"error": "Player not found"}, status_code=404)
        return card.to_dict()


@router.get("/api/compare/search")
async def api_compare_search(
    q: str = Query("", min_length=1),
    position: str | None = Query(None),
    limit: int = Query(10, le=20),
):
    """Fast JSON search for comparison autocomplete."""
    async with async_session() as session:
        results = await search_players_json(session, q, position, limit)
        return results


@router.get("/api/compare/multi")
async def api_multi_player_cards(
    ids: str = Query(..., description="Comma-separated player IDs"),
    season: int | None = Query(None),
):
    """Batch fetch up to 5 player cards."""
    try:
        player_ids = [int(x.strip()) for x in ids.split(",") if x.strip()][:5]
    except ValueError:
        return JSONResponse({"error": "Invalid player IDs"}, status_code=400)

    async with async_session() as session:
        s = season or default_season()
        cards = await get_player_cards_batch(session, player_ids, s)
        return cards


@router.get("/api/compare/stat-leaders")
async def api_stat_leaders(
    stat: str = Query(...),
    position: str | None = Query(None),
    season: int | None = Query(None),
    limit: int = Query(10, le=30),
):
    """Top players for a given stat."""
    async with async_session() as session:
        s = season or default_season()
        leaders = await get_stat_leaders(session, stat, s, position, limit)
        return leaders


# ── HTMX partial endpoints ──


@router.get("/api/compare/stat-table")
async def api_stat_table(
    request: Request,
    ids: str = Query(...),
    season: int | None = Query(None),
    period: str = Query("full_season"),
    stat_type: str = Query("standard"),
):
    """Server-rendered stat comparison table partial."""
    try:
        player_ids = [int(x.strip()) for x in ids.split(",") if x.strip()][:5]
    except ValueError:
        return JSONResponse({"error": "Invalid player IDs"}, status_code=400)

    async with async_session() as session:
        s = season or default_season()
        cards = await get_player_cards_batch(session, player_ids, s)

        # Define which stats to show based on type
        if stat_type == "standard":
            if any(c["player"]["player_type"] == "pitcher" for c in cards):
                stat_rows = [
                    ("W", "w"), ("L", "l"), ("SV", "sv"), ("IP", "ip"),
                    ("ERA", "era"), ("WHIP", "whip"), ("K/9", "k_per_9"),
                    ("BB/9", "bb_per_9"), ("FIP", "fip"), ("WAR", "war"),
                ]
            else:
                stat_rows = [
                    ("PA", "pa"), ("AVG", "avg"), ("OBP", "obp"), ("SLG", "slg"),
                    ("OPS", "ops"), ("HR", "hr"), ("R", "r"), ("RBI", "rbi"),
                    ("SB", "sb"), ("BB", "bb"), ("SO", "so"),
                    ("wOBA", "woba"), ("wRC+", "wrc_plus"),
                ]
        elif stat_type == "advanced":
            stat_rows = [
                ("BABIP", "babip"), ("ISO", "iso"), ("BB%", "bb_pct"),
                ("K%", "k_pct"), ("WAR", "war"),
            ]
        else:  # statcast
            stat_rows = [
                ("xBA", "xba"), ("xSLG", "xslg"), ("xwOBA", "xwoba"),
                ("AvgEV", "avg_exit_velo"), ("MaxEV", "max_exit_velo"),
                ("Barrel%", "barrel_pct"), ("HardHit%", "hard_hit_pct"),
                ("SweetSpot%", "sweet_spot_pct"), ("Whiff%", "whiff_pct"),
                ("Chase%", "chase_pct"),
            ]

        # Lower-is-better stats for coloring
        lower_is_better = {"era", "whip", "bb_per_9", "fip", "xfip", "siera",
                           "k_pct", "whiff_pct", "chase_pct", "bb_per_9"}

        # Get stat values for each player
        table_data = []
        for label, key in stat_rows:
            row = {
                "label": label, "key": key, "player_values": [],
                "lower_is_better": key in lower_is_better,
            }
            for card in cards:
                source = card.get("statcast" if stat_type == "statcast" else "traditional", {})
                period_data = source.get(period, {})
                val = period_data.get(key)
                row["player_values"].append(val)
            table_data.append(row)

        # Determine leaders for coloring
        for row in table_data:
            vals = [v for v in row["player_values"] if v is not None]
            if vals:
                if row["lower_is_better"]:
                    row["best"] = min(vals)
                    row["worst"] = max(vals)
                else:
                    row["best"] = max(vals)
                    row["worst"] = min(vals)
            else:
                row["best"] = None
                row["worst"] = None

        return templates.TemplateResponse(
            request,
            "partials/compare_stat_table.html",
            {
                "cards": cards,
                "table_data": table_data,
                "period": period,
                "stat_type": stat_type,
            },
        )


@router.get("/api/compare/projections-panel")
async def api_projections_panel(
    request: Request,
    ids: str = Query(...),
    season: int | None = Query(None),
):
    """Server-rendered projections comparison partial."""
    try:
        player_ids = [int(x.strip()) for x in ids.split(",") if x.strip()][:5]
    except ValueError:
        return JSONResponse({"error": "Invalid player IDs"}, status_code=400)

    async with async_session() as session:
        s = season or default_season()
        cards = await get_player_cards_batch(session, player_ids, s)
        return templates.TemplateResponse(
            request,
            "partials/compare_projections.html",
            {"cards": cards, "season": s},
        )


@router.get("/api/compare/splits-panel")
async def api_splits_panel(
    request: Request,
    ids: str = Query(...),
    season: int | None = Query(None),
):
    """Server-rendered splits comparison partial."""
    try:
        player_ids = [int(x.strip()) for x in ids.split(",") if x.strip()][:5]
    except ValueError:
        return JSONResponse({"error": "Invalid player IDs"}, status_code=400)

    async with async_session() as session:
        s = season or default_season()
        cards = await get_player_cards_batch(session, player_ids, s)
        return templates.TemplateResponse(
            request,
            "partials/compare_splits.html",
            {"cards": cards, "season": s},
        )
