from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates

from app.config import default_season
from app.database import async_session
from app.services.trade_service import (
    calculate_trade_values,
    evaluate_trade,
    store_trade_values,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/trades")
async def trades(request: Request):
    season = default_season()

    async with async_session() as session:
        hitter_values, pitcher_values = await calculate_trade_values(session, season)

        # Persist so evaluate_trade can look them up
        if hitter_values or pitcher_values:
            await store_trade_values(session, hitter_values, pitcher_values)
            await session.commit()

    # Combine and sort by surplus value for the value chart
    all_values = sorted(
        hitter_values + pitcher_values,
        key=lambda v: v.get("surplus_value", 0),
        reverse=True,
    )

    return templates.TemplateResponse(
        request,
        "trades.html",
        {"trade_values": all_values[:50], "season": season},
    )


@router.post("/api/trades/analyze")
async def analyze_trade(
    request: Request,
    side_a: str = Form(...),
    side_b: str = Form(...),
):
    """HTMX endpoint: evaluate a trade and return a partial result."""
    season = default_season()

    # Parse comma-separated player IDs
    try:
        side_a_ids = [int(x.strip()) for x in side_a.split(",") if x.strip()]
        side_b_ids = [int(x.strip()) for x in side_b.split(",") if x.strip()]
    except ValueError:
        return templates.TemplateResponse(
            request,
            "partials/trade_result.html",
            {"error": "Invalid player IDs"},
        )

    async with async_session() as session:
        result = await evaluate_trade(session, side_a_ids, side_b_ids, season)

    return templates.TemplateResponse(
        request,
        "partials/trade_result.html",
        {"trade": result},
    )
