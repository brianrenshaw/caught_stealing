from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, union

from app.config import default_season
from app.database import async_session
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.services.projection_service import (
    get_buy_sell_candidates,
    get_projections_comparison,
    project_all_hitters,
    project_all_pitchers,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _get_available_seasons(session) -> list[int]:
    """Return all seasons that have stats data, descending."""
    batting_seasons = select(BattingStats.season).distinct()
    pitching_seasons = select(PitchingStats.season).distinct()
    combined = union(batting_seasons, pitching_seasons).subquery()
    result = await session.execute(select(combined.c.season).order_by(combined.c.season.desc()))
    return [row[0] for row in result.fetchall()]


@router.get("/projections")
async def projections(
    request: Request,
    position: str = Query(None),
    player_type: str = Query("hitter"),
    season: int | None = Query(None),
):
    hitter_projs = []
    pitcher_projs = []

    async with async_session() as session:
        available_seasons = await _get_available_seasons(session)

        # Use requested season, or fall back to latest available, or current year
        if season and season in available_seasons:
            selected_season = season
        elif available_seasons:
            selected_season = available_seasons[0]
        else:
            selected_season = default_season()

        if player_type == "hitter" or player_type == "all":
            hitter_projs = await project_all_hitters(session, selected_season)
        if player_type == "pitcher" or player_type == "all":
            pitcher_projs = await project_all_pitchers(session, selected_season)

    # Filter by position if requested
    if position and hitter_projs:
        hitter_projs = [p for p in hitter_projs if p.position and position in p.position]
    if position and pitcher_projs:
        pitcher_projs = [p for p in pitcher_projs if p.position and position in p.position]

    # Sort by confidence descending
    hitter_projs.sort(key=lambda p: p.confidence_score, reverse=True)
    pitcher_projs.sort(key=lambda p: p.confidence_score, reverse=True)

    # Get buy/sell candidates for the signals panel
    buy_sell = {"buy_low": [], "sell_high": []}
    try:
        async with async_session() as bs_session:
            buy_sell = await get_buy_sell_candidates(bs_session, selected_season, limit=10)
    except Exception:
        pass

    return templates.TemplateResponse(
        request,
        "projections.html",
        {
            "hitter_projs": hitter_projs,
            "pitcher_projs": pitcher_projs,
            "selected_type": player_type,
            "selected_position": position,
            "selected_season": selected_season,
            "available_seasons": available_seasons,
            "buy_low": buy_sell.get("buy_low", []),
            "sell_high": buy_sell.get("sell_high", []),
        },
    )


@router.get("/projections/compare")
async def projection_compare(
    request: Request,
    players: str = Query("", description="Comma-separated player IDs"),
    season: int | None = Query(None),
):
    """Side-by-side projection comparison page."""
    async with async_session() as session:
        available_seasons = await _get_available_seasons(session)

        if season and season in available_seasons:
            selected_season = season
        elif available_seasons:
            selected_season = available_seasons[0]
        else:
            selected_season = default_season()

        player_ids = [int(p.strip()) for p in players.split(",") if p.strip().isdigit()]
        comparisons = []
        for pid in player_ids[:4]:
            player = await session.get(Player, pid)
            if player:
                projs = await get_projections_comparison(session, pid, selected_season)
                comparisons.append(
                    {
                        "player": player,
                        "projections": projs,
                    }
                )

    return templates.TemplateResponse(
        request,
        "projections_compare.html",
        {
            "comparisons": comparisons,
            "selected_season": selected_season,
            "available_seasons": available_seasons,
        },
    )
