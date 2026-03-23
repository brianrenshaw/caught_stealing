import logging
from datetime import date

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import default_season
from app.database import async_session
from app.models.batting_stats import BattingStats
from app.services.mlb_service import get_injuries
from app.services.schedule_service import get_week_boundaries
from app.services.waiver_service import (
    analyze_roster_waivers,
    score_free_agents,
    score_free_agents_weekly,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _week_offsets() -> tuple[int, int]:
    """On Monday (waiver day), show next week and the week after."""
    if date.today().weekday() == 0:  # Monday
        return 1, 2
    return 0, 1


async def _best_season(session, season: int) -> int:
    """Fall back to most recent season with stats if requested season has none."""
    result = await session.execute(
        select(BattingStats.season).distinct().order_by(BattingStats.season.desc())
    )
    available = [r[0] for r in result.fetchall()]
    if season in available:
        return season
    return available[0] if available else season


@router.get("/waivers")
async def waivers(request: Request, period: str = "ros"):
    season = default_season()
    recommendations = []
    injuries = []

    # Compute week boundaries for dropdown labels
    w1_off, w2_off = _week_offsets()
    week1_start, week1_end = get_week_boundaries(w1_off)
    week2_start, week2_end = get_week_boundaries(w2_off)

    async with async_session() as session:
        try:
            season = await _best_season(session, season)
            injuries = await get_injuries()

            if period == "week_1":
                recommendations = await score_free_agents_weekly(
                    session, season, week1_start, week1_end, limit=30, injuries=injuries
                )
            elif period == "week_2":
                recommendations = await score_free_agents_weekly(
                    session, season, week2_start, week2_end, limit=30, injuries=injuries
                )
            else:
                recommendations = await score_free_agents(
                    session, season, limit=30, injuries=injuries
                )
        except Exception as e:
            logger.error(f"Waiver recommendations failed: {e}", exc_info=True)

    return templates.TemplateResponse(
        request,
        "waivers.html",
        {
            "recommendations": recommendations,
            "period": period,
            "week1_start": week1_start,
            "week1_end": week1_end,
            "week2_start": week2_start,
            "week2_end": week2_end,
        },
    )


@router.get("/waivers/table")
async def waivers_table(request: Request, period: str = "ros"):
    """HTMX partial — returns just the waiver table for period switching."""
    season = default_season()
    recommendations = []

    w1_off, w2_off = _week_offsets()
    week1_start, week1_end = get_week_boundaries(w1_off)
    week2_start, week2_end = get_week_boundaries(w2_off)

    async with async_session() as session:
        try:
            season = await _best_season(session, season)
            injuries = await get_injuries()

            if period == "week_1":
                recommendations = await score_free_agents_weekly(
                    session, season, week1_start, week1_end, limit=30, injuries=injuries
                )
            elif period == "week_2":
                recommendations = await score_free_agents_weekly(
                    session, season, week2_start, week2_end, limit=30, injuries=injuries
                )
            else:
                recommendations = await score_free_agents(
                    session, season, limit=30, injuries=injuries
                )
        except Exception as e:
            logger.error(f"Waiver table failed: {e}", exc_info=True)

    return templates.TemplateResponse(
        request,
        "partials/waiver_table.html",
        {
            "recommendations": recommendations,
            "period": period,
            "week1_start": week1_start,
            "week1_end": week1_end,
            "week2_start": week2_start,
            "week2_end": week2_end,
        },
    )


@router.post("/waivers/analyze")
async def analyze_waivers(request: Request, period: str = "ros"):
    """HTMX partial — returns AI-generated roster analysis."""
    season = default_season()
    analysis_text = ""

    w1_off, w2_off = _week_offsets()
    week1_start, week1_end = get_week_boundaries(w1_off)
    week2_start, week2_end = get_week_boundaries(w2_off)

    async with async_session() as session:
        try:
            season = await _best_season(session, season)
            injuries = await get_injuries()

            if period == "week_1":
                recommendations = await score_free_agents_weekly(
                    session, season, week1_start, week1_end, limit=30, injuries=injuries
                )
                analysis_text = await analyze_roster_waivers(
                    session,
                    season,
                    recommendations,
                    injuries,
                    period=period,
                    week_start=week1_start,
                    week_end=week1_end,
                )
            elif period == "week_2":
                recommendations = await score_free_agents_weekly(
                    session, season, week2_start, week2_end, limit=30, injuries=injuries
                )
                analysis_text = await analyze_roster_waivers(
                    session,
                    season,
                    recommendations,
                    injuries,
                    period=period,
                    week_start=week2_start,
                    week_end=week2_end,
                )
            else:
                recommendations = await score_free_agents(
                    session, season, limit=30, injuries=injuries
                )
                analysis_text = await analyze_roster_waivers(
                    session,
                    season,
                    recommendations,
                    injuries,
                    period="ros",
                )
        except Exception as e:
            analysis_text = f"**Analysis failed:** {e}"

    return templates.TemplateResponse(
        request,
        "partials/waiver_analysis.html",
        {
            "analysis": analysis_text,
            "period": period,
        },
    )
