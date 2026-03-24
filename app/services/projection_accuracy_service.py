"""Projection accuracy tracking — generates weekly and season-level accuracy reports."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.league_week_snapshot import LeagueWeekSnapshot
from app.models.weekly_matchup import WeeklyMatchupSnapshot
from app.services.weekly_matchup_service import build_matchup_display

logger = logging.getLogger(__name__)

ANALYSIS_DIR = Path("data/content/analysis")


def _error_pct(projected: float, actual: float) -> str:
    """Return signed percentage error string like '+12.3%' or '-5.1%'."""
    if actual == 0:
        return "N/A"
    pct = ((projected - actual) / actual) * 100
    return f"{pct:+.1f}%"


def _over_under(projected: float, actual: float) -> str:
    """Return 'over' or 'under' or 'exact'."""
    diff = projected - actual
    if abs(diff) < 0.05:
        return "exact"
    return "over" if diff > 0 else "under"


def _player_highlights(projected_breakdown: dict, actual_breakdown: dict) -> list[dict]:
    """Find players with the biggest projection misses.

    Returns list of {name, proj_pts, actual_pts, diff} sorted by |diff| desc.
    """
    proj_players = projected_breakdown.get("players", [])
    actual_players = actual_breakdown.get("players", [])
    actual_by_name = {p.get("name", ""): p for p in actual_players}

    highlights = []
    for pp in proj_players:
        name = pp.get("name", "")
        proj_pts = pp.get("points", 0) or 0
        ap = actual_by_name.get(name, {})
        actual_pts = ap.get("points", 0) or 0
        if proj_pts == 0 and actual_pts == 0:
            continue
        highlights.append(
            {
                "name": name,
                "proj_pts": round(proj_pts, 1),
                "actual_pts": round(actual_pts, 1),
                "diff": round(actual_pts - proj_pts, 1),
            }
        )

    highlights.sort(key=lambda h: abs(h["diff"]), reverse=True)
    return highlights


async def generate_week_accuracy_report(
    session: AsyncSession,
    season: int,
    week: int,
) -> Path | None:
    """Generate a markdown accuracy report for a completed week.

    Returns the Path to the generated file, or None if insufficient data.
    """
    result = await session.execute(
        select(WeeklyMatchupSnapshot).where(
            WeeklyMatchupSnapshot.season == season,
            WeeklyMatchupSnapshot.week == week,
        )
    )
    snap = result.scalar_one_or_none()
    if not snap:
        logger.info(f"No snapshot found for season {season} week {week}")
        return None

    my_actual = snap.my_actual_points or 0
    opp_actual = snap.opponent_actual_points or 0
    my_yahoo = snap.my_projected_points or 0
    opp_yahoo = snap.opponent_projected_points or 0

    # Get app projection (stored column or recompute)
    my_app = snap.my_app_projected_points
    opp_app = snap.opponent_app_projected_points
    if my_app is None:
        display = build_matchup_display(snap)
        my_app = display["my_proj_total"]
        opp_app = display["opp_proj_total"]

    # Errors
    yahoo_err = abs(my_yahoo - my_actual)
    app_err = abs(my_app - my_actual)
    yahoo_opp_err = abs(opp_yahoo - opp_actual)
    app_opp_err = abs(opp_app - opp_actual)

    # Which was closer?
    if yahoo_err < app_err:
        closer = "Yahoo"
    elif app_err < yahoo_err:
        closer = "My Projection"
    else:
        closer = "Tie"

    # Actual result
    if my_actual > opp_actual:
        result_str = f"**Win** ({my_actual:.1f}–{opp_actual:.1f})"
    elif opp_actual > my_actual:
        result_str = f"**Loss** ({my_actual:.1f}–{opp_actual:.1f})"
    else:
        result_str = f"**Tie** ({my_actual:.1f}–{opp_actual:.1f})"

    # Directional accuracy
    yahoo_predicted_win = my_yahoo > opp_yahoo
    app_predicted_win = my_app > opp_app
    actual_win = my_actual > opp_actual
    yahoo_direction = "Correct" if yahoo_predicted_win == actual_win else "Wrong"
    app_direction = "Correct" if app_predicted_win == actual_win else "Wrong"

    # Player highlights
    proj_bd = json.loads(snap.my_projected_breakdown or "{}")
    actual_bd = json.loads(snap.my_actual_breakdown or "{}")
    highlights = _player_highlights(proj_bd, actual_bd)
    top_over = [h for h in highlights if h["diff"] > 0][:3]
    top_under = [h for h in highlights if h["diff"] < 0][:3]

    # Build markdown
    now = datetime.now(timezone.utc).isoformat()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = [
        "---",
        f'title: "Week {week} Projection Accuracy"',
        "type: projection-accuracy",
        f"date: {date_str}",
        f"generated_at: {now}",
        "---",
        "",
        f"# Week {week} Projection Accuracy",
        "",
        f"## Week {week}: vs {snap.opponent_team_name}",
        "",
        f"**Result:** {result_str}",
        "",
        "### My Team Score Projections",
        "",
        "| Source | Projected | Actual | Error | Over/Under |",
        "|--------|-----------|--------|-------|------------|",
        (
            f"| Yahoo | {my_yahoo:.1f} | {my_actual:.1f}"
            f" | {yahoo_err:.1f} | {_over_under(my_yahoo, my_actual)} |"
        ),
        (
            f"| My Projection | {my_app:.1f} | {my_actual:.1f}"
            f" | {app_err:.1f} | {_over_under(my_app, my_actual)} |"
        ),
        "",
        "### Opponent Score Projections",
        "",
        "| Source | Projected | Actual | Error | Over/Under |",
        "|--------|-----------|--------|-------|------------|",
        (
            f"| Yahoo | {opp_yahoo:.1f} | {opp_actual:.1f}"
            f" | {yahoo_opp_err:.1f} | {_over_under(opp_yahoo, opp_actual)} |"
        ),
        (
            f"| My Projection | {opp_app:.1f} | {opp_actual:.1f}"
            f" | {app_opp_err:.1f} | {_over_under(opp_app, opp_actual)} |"
        ),
        "",
        "### Which Projection Was Better?",
        "",
        (
            f"**Closer to actual (my team):** {closer}"
            f" (Yahoo err: {yahoo_err:.1f}, App err: {app_err:.1f})"
        ),
        "",
        f"- Yahoo predicted winner: {yahoo_direction}",
        f"- My projection predicted winner: {app_direction}",
        "",
    ]

    if top_over or top_under:
        lines.append("### Player-Level Highlights")
        lines.append("")

    if top_over:
        lines.append("**Outperformed projections:**")
        lines.append("")
        for h in top_over:
            lines.append(
                f"- **{h['name']}**: projected {h['proj_pts']}, "
                f"actual {h['actual_pts']} (+{h['diff']})"
            )
        lines.append("")

    if top_under:
        lines.append("**Underperformed projections:**")
        lines.append("")
        for h in top_under:
            lines.append(
                f"- **{h['name']}**: projected {h['proj_pts']}, "
                f"actual {h['actual_pts']} ({h['diff']})"
            )
        lines.append("")

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = ANALYSIS_DIR / f"{date_str}_projection-accuracy-wk{week}.md"
    filepath.write_text("\n".join(lines))
    logger.info(f"Generated projection accuracy report: {filepath}")
    return filepath


async def generate_season_accuracy_summary(
    session: AsyncSession,
    season: int,
) -> Path | None:
    """Generate/overwrite the cumulative season projection accuracy summary.

    Returns the Path to the generated file, or None if no data.
    """
    result = await session.execute(
        select(WeeklyMatchupSnapshot)
        .where(WeeklyMatchupSnapshot.season == season)
        .order_by(WeeklyMatchupSnapshot.week)
    )
    snapshots = result.scalars().all()

    if not snapshots:
        return None

    weeks_data = []
    yahoo_errors: list[float] = []
    app_errors: list[float] = []
    yahoo_direction_correct = 0
    app_direction_correct = 0
    total_decided = 0
    yahoo_closer = 0
    app_closer = 0

    for snap in snapshots:
        my_actual = snap.my_actual_points or 0
        opp_actual = snap.opponent_actual_points or 0

        # Skip weeks with no actual data yet
        if my_actual == 0 and opp_actual == 0:
            continue

        my_yahoo = snap.my_projected_points or 0
        opp_yahoo = snap.opponent_projected_points or 0

        my_app = snap.my_app_projected_points
        opp_app = snap.opponent_app_projected_points
        if my_app is None:
            try:
                display = build_matchup_display(snap)
                my_app = display["my_proj_total"]
                opp_app = display["opp_proj_total"]
            except Exception:
                continue

        y_err = abs(my_yahoo - my_actual)
        a_err = abs(my_app - my_actual)
        yahoo_errors.append(y_err)
        app_errors.append(a_err)

        if y_err < a_err:
            yahoo_closer += 1
        elif a_err < y_err:
            app_closer += 1

        actual_win = my_actual > opp_actual
        yahoo_win = my_yahoo > opp_yahoo
        app_win = my_app > opp_app

        if my_actual != opp_actual:
            total_decided += 1
            if yahoo_win == actual_win:
                yahoo_direction_correct += 1
            if app_win == actual_win:
                app_direction_correct += 1

        won = "W" if my_actual > opp_actual else ("L" if opp_actual > my_actual else "T")
        closer = "Yahoo" if y_err < a_err else ("Mine" if a_err < y_err else "Tie")

        weeks_data.append(
            {
                "week": snap.week,
                "opponent": snap.opponent_team_name,
                "yahoo_proj": my_yahoo,
                "app_proj": my_app,
                "actual": my_actual,
                "yahoo_err": y_err,
                "app_err": a_err,
                "closer": closer,
                "result": won,
            }
        )

    if not weeks_data:
        return None

    yahoo_mae = sum(yahoo_errors) / len(yahoo_errors)
    app_mae = sum(app_errors) / len(app_errors)
    yahoo_dir_pct = round(100 * yahoo_direction_correct / total_decided) if total_decided else 0
    app_dir_pct = round(100 * app_direction_correct / total_decided) if total_decided else 0

    now = datetime.now(timezone.utc).isoformat()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if yahoo_mae < app_mae:
        leader = "Yahoo"
        diff = app_mae - yahoo_mae
        leader_note = f"Yahoo projections more accurate by {diff:.1f} pts MAE."
    elif app_mae < yahoo_mae:
        leader = "My Projection"
        diff = yahoo_mae - app_mae
        leader_note = f"My projections more accurate by {diff:.1f} pts MAE."
    else:
        leader = "Tied"
        leader_note = "Both projection systems have identical MAE."

    lines = [
        "---",
        f'title: "{season} Season Projection Accuracy"',
        "type: projection-accuracy",
        f"date: {date_str}",
        f"generated_at: {now}",
        "---",
        "",
        f"# {season} Season Projection Accuracy",
        "",
        "## Season Summary",
        "",
        f"**Weeks tracked:** {len(weeks_data)}",
        "",
        f"**Current leader:** {leader} — {leader_note}",
        "",
        "| Metric | Yahoo | My Projection |",
        "|--------|-------|---------------|",
        f"| Mean Absolute Error (MAE) | {yahoo_mae:.1f} | {app_mae:.1f} |",
        f"| Directional Accuracy | {yahoo_dir_pct}% | {app_dir_pct}% |",
        f"| Weeks Closer | {yahoo_closer} | {app_closer} |",
        "",
        "## Week-by-Week Results",
        "",
        "| Week | Opponent | Yahoo Proj | My Proj | Actual | Yahoo Err | My Err | Closer | W/L |",
        "|------|----------|-----------|---------|--------|-----------|--------|--------|-----|",
    ]

    for w in weeks_data:
        lines.append(
            f"| {w['week']} | {w['opponent']} | {w['yahoo_proj']:.1f} | "
            f"{w['app_proj']:.1f} | {w['actual']:.1f} | {w['yahoo_err']:.1f} | "
            f"{w['app_err']:.1f} | {w['closer']} | {w['result']} |"
        )

    lines.append("")

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = ANALYSIS_DIR / f"{season}_projection-accuracy-season.md"
    filepath.write_text("\n".join(lines))
    logger.info(f"Generated season accuracy summary: {filepath}")
    return filepath


async def generate_league_accuracy_report(
    session: AsyncSession,
    season: int,
    week: int,
) -> Path | None:
    """Generate a league-wide accuracy report for a completed week.

    Shows all matchups with Yahoo projected vs actual for every team.
    """
    result = await session.execute(
        select(LeagueWeekSnapshot)
        .where(
            LeagueWeekSnapshot.season == season,
            LeagueWeekSnapshot.week == week,
        )
        .order_by(LeagueWeekSnapshot.rank)
    )
    snaps = result.scalars().all()
    if not snaps:
        return None

    # Skip if no actual data yet
    if all((s.actual_points or 0) == 0 for s in snaps):
        return None

    now = datetime.now(timezone.utc).isoformat()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Group into matchups (pairs by opponent_team_id)
    seen: set[str] = set()
    matchups: list[tuple] = []
    snap_by_id = {s.team_id: s for s in snaps}
    for s in snaps:
        if s.team_id in seen:
            continue
        opp = snap_by_id.get(s.opponent_team_id)
        if opp:
            matchups.append((s, opp))
            seen.add(s.team_id)
            seen.add(opp.team_id)

    lines = [
        "---",
        f'title: "Week {week} League Accuracy"',
        "type: league-accuracy",
        f"date: {date_str}",
        f"generated_at: {now}",
        "---",
        "",
        f"# Week {week} League-Wide Projection Accuracy",
        "",
    ]

    total_error = 0.0
    total_teams = 0
    upsets = []

    for home, away in matchups:
        h_proj = home.yahoo_projected_points or 0
        h_act = home.actual_points or 0
        a_proj = away.yahoo_projected_points or 0
        a_act = away.actual_points or 0

        h_err = abs(h_proj - h_act)
        a_err = abs(a_proj - a_act)
        total_error += h_err + a_err
        total_teams += 2

        # Check for upset
        proj_winner = home.team_name if h_proj > a_proj else away.team_name
        actual_winner = home.team_name if h_act > a_act else away.team_name
        is_upset = proj_winner != actual_winner and h_act != a_act

        lines.append(f"## {home.team_name} vs {away.team_name}")
        lines.append("")
        lines.append("| Team | Projected | Actual | Error |")
        lines.append("|------|-----------|--------|-------|")
        lines.append(f"| {home.team_name} | {h_proj:.1f} | {h_act:.1f} | {h_err:.1f} |")
        lines.append(f"| {away.team_name} | {a_proj:.1f} | {a_act:.1f} | {a_err:.1f} |")
        if is_upset:
            lines.append("")
            lines.append(f"**Upset!** {actual_winner} won despite being projected to lose.")
            upsets.append(f"{actual_winner} over {proj_winner}")
        lines.append("")

    # Summary
    avg_err = total_error / total_teams if total_teams else 0
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **League avg error:** {avg_err:.1f} pts per team")
    lines.append(f"- **Matchups:** {len(matchups)}")
    if upsets:
        lines.append(f"- **Upsets:** {', '.join(upsets)}")
    else:
        lines.append("- **Upsets:** None — all favorites won")
    lines.append("")

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = ANALYSIS_DIR / f"{date_str}_league-accuracy-wk{week}.md"
    filepath.write_text("\n".join(lines))
    logger.info(f"Generated league accuracy report: {filepath}")
    return filepath
