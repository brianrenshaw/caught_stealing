from datetime import date

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.database import async_session
from app.services.matchup_service import get_stacks, get_streaming_pitchers, get_two_start_pitchers

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/matchups")
async def matchups(request: Request):
    today = date.today()
    season = today.year

    async with async_session() as session:
        streaming = await get_streaming_pitchers(session, today, season, limit=10)
        stacks = await get_stacks(session, today, limit=5)
        two_start = await get_two_start_pitchers(session, season=season)

    return templates.TemplateResponse(
        request,
        "matchups.html",
        {
            "streaming_picks": streaming,
            "stacks": stacks,
            "two_start": two_start,
            "game_date": today.strftime("%A, %B %d"),
        },
    )
