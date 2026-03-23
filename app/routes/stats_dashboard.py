from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, union

from app.config import default_season
from app.database import async_session
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.statcast_summary import StatcastSummary

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _get_available_seasons(session) -> list[int]:
    """Return all seasons that have stats data, descending."""
    batting_seasons = select(BattingStats.season).distinct()
    pitching_seasons = select(PitchingStats.season).distinct()
    statcast_seasons = select(StatcastSummary.season).distinct()
    combined = union(batting_seasons, pitching_seasons, statcast_seasons).subquery()
    result = await session.execute(select(combined.c.season).order_by(combined.c.season.desc()))
    return [row[0] for row in result.all()]


@router.get("/stats")
async def stats_dashboard(
    request: Request,
    season: int | None = Query(None),
    view: str = Query("statcast"),
):
    """Advanced stats dashboard with Plotly charts."""
    async with async_session() as session:
        available_seasons = await _get_available_seasons(session)

        if season and season in available_seasons:
            selected_season = season
        elif available_seasons:
            selected_season = available_seasons[0]
        else:
            selected_season = default_season()

        return templates.TemplateResponse(
            request,
            "stats_dashboard.html",
            {
                "season": selected_season,
                "view": view,
                "available_seasons": available_seasons,
            },
        )
