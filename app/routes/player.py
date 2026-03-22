from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates

from app.config import default_season
from app.database import async_session
from app.services.player_service import get_comparable_players, get_player_profile

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/player/{player_id}")
async def player_profile(request: Request, player_id: int, season: int | None = Query(None)):
    """Full player profile page with all stats, projections, and analysis."""
    if not season:
        season = default_season()

    async with async_session() as session:
        profile = await get_player_profile(session, player_id, season)
        if not profile:
            return templates.TemplateResponse(
                request,
                "player.html",
                {"error": "Player not found", "season": season},
            )

        comps = await get_comparable_players(session, player_id, season)

        return templates.TemplateResponse(
            request,
            "player.html",
            {
                "profile": profile,
                "player": profile.player,
                "batting": profile.batting_stats,
                "pitching": profile.pitching_stats,
                "statcast_bat": profile.statcast_bat,
                "statcast_pitch": profile.statcast_pitch,
                "projections": profile.projections,
                "trade_value": profile.trade_value,
                "roster_info": profile.roster_info,
                "gaps": profile.gaps,
                "comps": comps,
                "season": season,
                "is_hitter": profile.is_hitter,
                "is_pitcher": profile.is_pitcher,
            },
        )
