from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates

from app.config import default_season

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/stats")
async def stats_dashboard(
    request: Request,
    season: int | None = Query(None),
    view: str = Query("statcast"),
):
    """Advanced stats dashboard with Plotly charts."""
    if not season:
        season = default_season()

    return templates.TemplateResponse(
        request,
        "stats_dashboard.html",
        {
            "season": season,
            "view": view,
        },
    )
