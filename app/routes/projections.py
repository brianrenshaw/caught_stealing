from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, union

from app.config import default_season
from app.database import async_session
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.player_points import PlayerPoints
from app.services.advanced_analytics_service import (
    calculate_batter_advanced_fp,
    calculate_pitcher_advanced_fp,
    get_batters_advanced_stats_bulk,
    get_pitchers_advanced_stats_bulk,
)
from app.services.projection_service import (
    get_buy_sell_candidates,
    get_projections_comparison,
    project_all_hitters,
    project_all_pitchers,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


async def _get_available_seasons(session) -> list[int]:
    """Return all seasons that have stats data, descending.

    Always includes the current default season so it appears in the picker
    even before stats data has been synced for that year.
    """
    batting_seasons = select(BattingStats.season).distinct()
    pitching_seasons = select(PitchingStats.season).distinct()
    combined = union(batting_seasons, pitching_seasons).subquery()
    result = await session.execute(select(combined.c.season).order_by(combined.c.season.desc()))
    seasons = [row[0] for row in result.fetchall()]
    current = default_season()
    if current not in seasons:
        seasons.insert(0, current)
    return seasons


@router.get("/projections")
async def projections(
    request: Request,
    position: str = Query(None),
    player_type: str = Query("hitter"),
    season: int | None = Query(None),
):
    hitter_projs = []
    pitcher_projs = []

    hitter_advanced = {}
    pitcher_advanced = {}
    hitter_adj_fp = {}
    pitcher_adj_fp = {}

    async with async_session() as session:
        available_seasons = await _get_available_seasons(session)

        # Use requested season, or fall back to latest available, or current year
        if season and season in available_seasons:
            selected_season = season
        elif available_seasons:
            selected_season = available_seasons[0]
        else:
            selected_season = default_season()

        # If the selected season has no stats data, use the most recent that does
        data_season = selected_season
        if data_season == default_season():
            # Check if there's actual data for this season
            from sqlalchemy import func as sqlfunc

            count_result = await session.execute(
                select(sqlfunc.count()).where(
                    BattingStats.season == data_season,
                    BattingStats.period == "full_season",
                )
            )
            if count_result.scalar() == 0 and available_seasons:
                # Fall back to most recent season with data
                for s in available_seasons:
                    if s != default_season():
                        data_season = s
                        break

        if player_type == "hitter" or player_type == "all":
            hitter_projs = await project_all_hitters(session, data_season)

            # Bulk-fetch advanced stats for all hitters
            hitter_ids = [p.player_id for p in hitter_projs]
            hitter_advanced = await get_batters_advanced_stats_bulk(
                hitter_ids, data_season, session
            )

            # Get baseline FP from PlayerPoints
            fp_result = await session.execute(
                select(PlayerPoints).where(
                    PlayerPoints.player_id.in_(hitter_ids),
                    PlayerPoints.season == data_season,
                    PlayerPoints.period == "full_season",
                )
            )
            hitter_fp_map = {pp.player_id: pp for pp in fp_result.scalars().all()}

            # Compute adjusted FP for each hitter
            for proj in hitter_projs:
                adv = hitter_advanced.get(proj.player_id)
                pp = hitter_fp_map.get(proj.player_id)
                baseline = pp.projected_ros_points if pp and pp.projected_ros_points else 0.0
                if adv:
                    hitter_adj_fp[proj.player_id] = calculate_batter_advanced_fp(
                        baseline, adv.woba, adv.xwoba
                    )

        if player_type == "pitcher" or player_type == "all":
            pitcher_projs = await project_all_pitchers(session, data_season)

            # Bulk-fetch advanced stats for all pitchers
            pitcher_ids = [p.player_id for p in pitcher_projs]
            pitcher_advanced = await get_pitchers_advanced_stats_bulk(
                pitcher_ids, data_season, session
            )

            # Get baseline FP from PlayerPoints
            fp_result = await session.execute(
                select(PlayerPoints).where(
                    PlayerPoints.player_id.in_(pitcher_ids),
                    PlayerPoints.season == data_season,
                    PlayerPoints.period == "full_season",
                )
            )
            pitcher_fp_map = {pp.player_id: pp for pp in fp_result.scalars().all()}

            # Compute adjusted FP for each pitcher
            for proj in pitcher_projs:
                adv = pitcher_advanced.get(proj.player_id)
                pp = pitcher_fp_map.get(proj.player_id)
                baseline = pp.projected_ros_points if pp and pp.projected_ros_points else 0.0
                is_closer = proj.position and "RP" in (proj.position or "")
                if adv:
                    pitcher_adj_fp[proj.player_id] = calculate_pitcher_advanced_fp(
                        baseline,
                        adv.era,
                        adv.xera,
                        adv.siera,
                        gmli=adv.gmli,
                        is_closer=is_closer,
                    )

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
            buy_sell = await get_buy_sell_candidates(bs_session, data_season, limit=10)
    except Exception:
        pass

    return templates.TemplateResponse(
        request,
        "projections.html",
        {
            "hitter_projs": hitter_projs,
            "pitcher_projs": pitcher_projs,
            "hitter_advanced": hitter_advanced,
            "pitcher_advanced": pitcher_advanced,
            "hitter_adj_fp": hitter_adj_fp,
            "pitcher_adj_fp": pitcher_adj_fp,
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
