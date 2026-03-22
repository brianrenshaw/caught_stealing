from datetime import date

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.database import async_session
from app.services.waiver_service import score_free_agents

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/waivers")
async def waivers(request: Request):
    season = date.today().year
    recommendations = []

    async with async_session() as session:
        try:
            recommendations = await score_free_agents(session, season, limit=30)
        except Exception:
            pass  # Will show empty state

    return templates.TemplateResponse(
        request,
        "waivers.html",
        {"recommendations": recommendations},
    )
