from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import default_season
from app.database import async_session
from app.models.player import Player
from app.models.player_points import PlayerPoints
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
    all_values = []

    async with async_session() as session:
        # Try points-based rankings first (from player_points table)
        pp_result = await session.execute(
            select(PlayerPoints, Player)
            .join(Player, PlayerPoints.player_id == Player.id)
            .where(
                PlayerPoints.season == season,
                PlayerPoints.period == "full_season",
            )
            .order_by(PlayerPoints.surplus_value.desc())
            .limit(50)
        )
        pp_rows = pp_result.all()

        if pp_rows:
            # Use points-based trade values
            for pp, player in pp_rows:
                all_values.append({
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team,
                    "position": player.position,
                    "player_type": pp.player_type,
                    "surplus_value": round(pp.surplus_value or 0, 1),
                    "projected_points": round(pp.projected_ros_points or 0, 1),
                    "actual_points": round(pp.actual_points or 0, 1),
                    "positional_rank": pp.positional_rank or 0,
                    "points_per_pa": round(pp.points_per_pa, 3) if pp.points_per_pa else None,
                    "points_per_ip": round(pp.points_per_ip, 2) if pp.points_per_ip else None,
                    "points_per_start": (
                        round(pp.points_per_start, 1) if pp.points_per_start else None
                    ),
                    "points_per_appearance": (
                        round(pp.points_per_appearance, 1) if pp.points_per_appearance else None
                    ),
                    "z_score_total": round(pp.surplus_value or 0, 1),  # compat with template
                    "scoring_type": "points",
                })
        else:
            # Fallback to z-score based trade values
            hitter_values, pitcher_values = await calculate_trade_values(session, season)
            if hitter_values or pitcher_values:
                await store_trade_values(session, hitter_values, pitcher_values)
                await session.commit()
            all_values = sorted(
                hitter_values + pitcher_values,
                key=lambda v: v.get("surplus_value", 0),
                reverse=True,
            )[:50]
            for v in all_values:
                v["scoring_type"] = "roto"

    return templates.TemplateResponse(
        request,
        "trades.html",
        {"trade_values": all_values, "season": season},
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
