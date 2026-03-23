from datetime import date

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.database import async_session
from app.services.mlb_service import get_injuries
from app.services.schedule_service import get_week_boundaries
from app.services.waiver_service import (
    analyze_roster_waivers,
    score_free_agents,
    score_free_agents_weekly,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/waivers")
async def waivers(request: Request, period: str = "ros"):
    season = date.today().year
    recommendations = []
    injuries = []

    # Compute week boundaries for dropdown labels
    week1_start, week1_end = get_week_boundaries(0)
    week2_start, week2_end = get_week_boundaries(1)

    async with async_session() as session:
        try:
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
        except Exception:
            pass  # Will show empty state

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
    season = date.today().year
    recommendations = []

    week1_start, week1_end = get_week_boundaries(0)
    week2_start, week2_end = get_week_boundaries(1)

    async with async_session() as session:
        try:
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
        except Exception:
            pass

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
    season = date.today().year
    analysis_text = ""

    week1_start, week1_end = get_week_boundaries(0)
    week2_start, week2_end = get_week_boundaries(1)

    async with async_session() as session:
        try:
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
