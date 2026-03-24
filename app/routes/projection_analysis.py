"""Projection Analysis tab — tracks Yahoo vs app projection accuracy over time."""

from __future__ import annotations

import logging
import math
from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import default_season
from app.database import async_session
from app.models.league_week_snapshot import LeagueWeekSnapshot
from app.models.weekly_matchup import WeeklyMatchupSnapshot
from app.services.weekly_matchup_service import (
    backfill_app_projected_points,
    build_matchup_display,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


@router.get("/projection-analysis")
async def projection_analysis_page(request: Request):
    """Main Projection Analysis page."""
    season = default_season()

    async with async_session() as session:
        # Backfill any snapshots missing app projection totals
        await backfill_app_projected_points(session)
        await session.commit()

        result = await session.execute(
            select(WeeklyMatchupSnapshot)
            .where(WeeklyMatchupSnapshot.season == season)
            .order_by(WeeklyMatchupSnapshot.week)
        )
        snapshots = result.scalars().all()

    weeks: list[dict] = []
    yahoo_errors: list[float] = []
    app_errors: list[float] = []
    yahoo_direction_correct = 0
    app_direction_correct = 0
    total_decided = 0
    yahoo_closer_count = 0
    app_closer_count = 0

    for snap in snapshots:
        my_actual = snap.my_actual_points or 0
        opp_actual = snap.opponent_actual_points or 0

        # Skip weeks with no actual data yet
        if my_actual == 0 and opp_actual == 0:
            continue

        my_yahoo = snap.my_projected_points or 0
        opp_yahoo = snap.opponent_projected_points or 0

        # Get app projection (stored column, fallback to recompute)
        my_app_proj = snap.my_app_projected_points
        opp_app_proj = snap.opponent_app_projected_points
        if my_app_proj is None:
            try:
                display = build_matchup_display(snap)
                my_app_proj = display["my_proj_total"]
                opp_app_proj = display["opp_proj_total"]
            except Exception:
                continue

        # Errors on my team's score
        yahoo_err = abs(my_yahoo - my_actual)
        app_err = abs(my_app_proj - my_actual)
        yahoo_errors.append(yahoo_err)
        app_errors.append(app_err)

        # Which projection was closer?
        if yahoo_err < app_err:
            yahoo_closer_count += 1
            closer = "Yahoo"
        elif app_err < yahoo_err:
            app_closer_count += 1
            closer = "Mine"
        else:
            closer = "Tie"

        # Directional accuracy (did projection predict the right winner?)
        actual_win = my_actual > opp_actual
        yahoo_predicted_win = my_yahoo > opp_yahoo
        app_predicted_win = my_app_proj > opp_app_proj

        if my_actual != opp_actual:
            total_decided += 1
            if yahoo_predicted_win == actual_win:
                yahoo_direction_correct += 1
            if app_predicted_win == actual_win:
                app_direction_correct += 1

        weeks.append(
            {
                "week": snap.week,
                "opponent": snap.opponent_team_name,
                "my_yahoo_proj": round(my_yahoo, 1),
                "my_app_proj": round(my_app_proj, 1),
                "my_actual": round(my_actual, 1),
                "yahoo_error": round(yahoo_err, 1),
                "app_error": round(app_err, 1),
                "closer": closer,
                "won": my_actual > opp_actual,
                "tied": my_actual == opp_actual,
                "opp_actual": round(opp_actual, 1),
            }
        )

    summary = {
        "weeks_played": len(weeks),
        "yahoo_mae": (round(sum(yahoo_errors) / len(yahoo_errors), 1) if yahoo_errors else 0),
        "app_mae": (round(sum(app_errors) / len(app_errors), 1) if app_errors else 0),
        "yahoo_direction_pct": (
            round(100 * yahoo_direction_correct / total_decided) if total_decided else 0
        ),
        "app_direction_pct": (
            round(100 * app_direction_correct / total_decided) if total_decided else 0
        ),
        "yahoo_closer_count": yahoo_closer_count,
        "app_closer_count": app_closer_count,
    }

    # ── League-wide projection accuracy from LeagueWeekSnapshot ──
    league_teams: list[dict] = []
    league_summary: dict = {"weeks_tracked": 0}

    async with async_session() as session:
        league_result = await session.execute(
            select(LeagueWeekSnapshot)
            .where(
                LeagueWeekSnapshot.season == season,
                LeagueWeekSnapshot.actual_points.isnot(None),
                LeagueWeekSnapshot.yahoo_projected_points.isnot(None),
            )
            .order_by(LeagueWeekSnapshot.week, LeagueWeekSnapshot.team_name)
        )
        league_snaps = league_result.scalars().all()

    if league_snaps:
        # Per-team accumulation
        team_data: dict[str, dict] = defaultdict(
            lambda: {
                "errors": [],
                "actuals": [],
                "weeks_over": 0,
                "weeks_under": 0,
                "is_my_team": False,
            }
        )

        weeks_seen: set[int] = set()
        for snap in league_snaps:
            if snap.actual_points == 0 and (snap.yahoo_projected_points or 0) == 0:
                continue
            weeks_seen.add(snap.week)
            td = team_data[snap.team_name]
            td["is_my_team"] = td["is_my_team"] or snap.is_my_team
            err = (snap.yahoo_projected_points or 0) - (snap.actual_points or 0)
            td["errors"].append(abs(err))
            td["actuals"].append(snap.actual_points or 0)
            if err > 0:
                td["weeks_over"] += 1
            elif err < 0:
                td["weeks_under"] += 1

        for name, td in sorted(
            team_data.items(),
            key=lambda x: sum(x[1]["errors"]) / len(x[1]["errors"]) if x[1]["errors"] else 999,
        ):
            errs = td["errors"]
            acts = td["actuals"]
            mae = round(sum(errs) / len(errs), 1) if errs else 0
            avg_pts = round(sum(acts) / len(acts), 1) if acts else 0
            # Standard deviation
            if len(acts) > 1:
                mean = sum(acts) / len(acts)
                variance = sum((x - mean) ** 2 for x in acts) / len(acts)
                std_dev = round(math.sqrt(variance), 1)
            else:
                std_dev = 0
            league_teams.append(
                {
                    "name": name,
                    "yahoo_mae": mae,
                    "avg_weekly_pts": avg_pts,
                    "volatility": std_dev,
                    "weeks_over": td["weeks_over"],
                    "weeks_under": td["weeks_under"],
                    "is_my_team": td["is_my_team"],
                }
            )

        all_errors = [e for td in team_data.values() for e in td["errors"]]
        league_summary = {
            "weeks_tracked": len(weeks_seen),
            "league_avg_mae": (round(sum(all_errors) / len(all_errors), 1) if all_errors else 0),
            "most_predictable": league_teams[0]["name"] if league_teams else "",
            "most_predictable_mae": league_teams[0]["yahoo_mae"] if league_teams else 0,
            "most_volatile": (
                max(league_teams, key=lambda t: t["volatility"])["name"] if league_teams else ""
            ),
            "most_volatile_std": (
                max(league_teams, key=lambda t: t["volatility"])["volatility"]
                if league_teams
                else 0
            ),
        }

    return templates.TemplateResponse(
        request,
        "projection_analysis.html",
        {
            "weeks": weeks,
            "summary": summary,
            "season": season,
            "league_teams": league_teams,
            "league_summary": league_summary,
        },
    )
