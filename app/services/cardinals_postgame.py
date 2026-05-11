"""Fetch postgame data for the St. Louis Cardinals' most recent MLB game.

Used by `scripts/cardinals_daily_report.py` to lead the daily Cardinals
report with concrete game-result + Statcast detail. Synchronous — called
from a CLI script, not an async route.

Returns None when there is no Cardinals game on the requested date (off
day, postponement). Returns partial data with Statcast omitted when
Baseball Savant hasn't published the game yet (typical lag is a few
hours; should be fine for the 3 AM pipeline).
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

import pandas as pd
import pybaseball
import statsapi

pybaseball.cache.enable()

log = logging.getLogger(__name__)

STL_TEAM_ID = 138
STL_TEAM_ABBR = "STL"
MAX_RETRIES = 3
RETRY_DELAY_S = 5


def _retry(func, *args, **kwargs):
    """Sync retry helper. Returns None on final failure."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log.warning(
                "%s attempt %d/%d failed: %s",
                func.__name__, attempt, MAX_RETRIES, e,
            )
            if attempt == MAX_RETRIES:
                return None
            time.sleep(RETRY_DELAY_S)
    return None


def _find_stl_game(target_date: date) -> dict | None:
    games = _retry(
        statsapi.schedule,
        date=target_date.strftime("%m/%d/%Y"),
        sportId=1,
    ) or []
    for g in games:
        if g.get("game_type") != "R":
            continue
        if g.get("home_id") == STL_TEAM_ID or g.get("away_id") == STL_TEAM_ID:
            return g
    return None


def _format_score_line(game: dict) -> str:
    home = game.get("home_name", "?")
    away = game.get("away_name", "?")
    home_score = game.get("home_score")
    away_score = game.get("away_score")
    status = game.get("status", "")
    if home_score is None or away_score is None:
        return f"{away} @ {home} ({status})"
    stl_won = (
        (game.get("home_id") == STL_TEAM_ID and home_score > away_score)
        or (game.get("away_id") == STL_TEAM_ID and away_score > home_score)
    )
    result_letter = "W" if stl_won else "L"
    return f"{away} {away_score}, {home} {home_score} (STL {result_letter})"


def _stl_batters_from_box(box: dict) -> list[dict]:
    """Extract Cardinals batter lines from a statsapi boxscore_data() dict."""
    out: list[dict] = []
    home_team_id = box.get("teamInfo", {}).get("home", {}).get("id")
    side = "home" if home_team_id == STL_TEAM_ID else "away"
    team_box = box.get(side, {})
    players = team_box.get("players", {}) or {}
    batting_order = team_box.get("battingOrder", []) or []
    order_map = {pid: i for i, pid in enumerate(batting_order)}
    for pid, p in players.items():
        stats = p.get("stats", {}).get("batting", {}) or {}
        if not stats or not stats.get("atBats"):
            continue
        out.append({
            "name": p.get("person", {}).get("fullName"),
            "position": p.get("position", {}).get("abbreviation"),
            "ab": stats.get("atBats"),
            "h": stats.get("hits"),
            "r": stats.get("runs"),
            "rbi": stats.get("rbi"),
            "bb": stats.get("baseOnBalls"),
            "k": stats.get("strikeOuts"),
            "hr": stats.get("homeRuns"),
            "avg": stats.get("avg"),
            "order": order_map.get(int(pid.replace("ID", "")), 99),
        })
    out.sort(key=lambda x: x["order"])
    return out


def _stl_pitchers_from_box(box: dict) -> list[dict]:
    out: list[dict] = []
    home_team_id = box.get("teamInfo", {}).get("home", {}).get("id")
    side = "home" if home_team_id == STL_TEAM_ID else "away"
    team_box = box.get(side, {})
    players = team_box.get("players", {}) or {}
    pitchers_order = team_box.get("pitchers", []) or []
    seen: set[int] = set()
    for raw in pitchers_order:
        pid_key = f"ID{raw}"
        p = players.get(pid_key)
        if not p:
            continue
        stats = p.get("stats", {}).get("pitching", {}) or {}
        if not stats:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        out.append({
            "name": p.get("person", {}).get("fullName"),
            "ip": stats.get("inningsPitched"),
            "h": stats.get("hits"),
            "r": stats.get("runs"),
            "er": stats.get("earnedRuns"),
            "bb": stats.get("baseOnBalls"),
            "k": stats.get("strikeOuts"),
            "hr": stats.get("homeRuns"),
            "pitches": stats.get("numberOfPitches"),
            "decision": stats.get("note", "").strip("()") or None,
        })
    return out


def _build_pid_to_name(box: dict | None) -> dict[int, str]:
    """Build MLBAM player_id → fullName lookup from both teams' boxscore players.

    Needed because pybaseball.statcast_single_game() puts the BATTER in
    `player_name` for every row — to get the pitcher's name we look up the
    `pitcher` MLBAM id against this map.
    """
    pmap: dict[int, str] = {}
    if not box:
        return pmap
    for side in ("home", "away"):
        players = ((box.get(side) or {}).get("players")) or {}
        for p in players.values():
            person = p.get("person") or {}
            pid = person.get("id")
            name = person.get("fullName")
            if pid and name:
                try:
                    pmap[int(pid)] = name
                except (TypeError, ValueError):
                    pass
    return pmap


def _pitcher_name(row: pd.Series, pid_to_name: dict[int, str]) -> str | None:
    """Resolve the pitcher's full name for a Statcast row using the boxscore map.

    `player_name` in statcast_single_game data is the batter — we use the `pitcher`
    MLBAM id column and look it up against the boxscore player map. Fall back to
    `player_name` only if the id lookup fails.
    """
    pid = row.get("pitcher") if hasattr(row, "get") else None
    if pid is not None and not (isinstance(pid, float) and pd.isna(pid)):
        try:
            return pid_to_name.get(int(pid)) or _safe(row, "player_name")
        except (TypeError, ValueError):
            pass
    return _safe(row, "player_name")


def _statcast_highlights(
    df: pd.DataFrame | None, pid_to_name: dict[int, str] | None = None
) -> dict[str, list]:
    """Aggregate Statcast pitch-level data into highlight buckets — hitters and pitchers.

    Cardinals only — filters by inning_topbot + home/away to keep STL events.
    Pitcher names are resolved via `pid_to_name` map (built from boxscore) since
    `player_name` in Statcast single-game data is the batter, not the pitcher.
    """
    if df is None or df.empty:
        return {}
    pid_to_name = pid_to_name or {}

    # When STL is home: STL hits in bot, STL pitches in top.
    # When STL is away: STL hits in top, STL pitches in bot.
    home_team = df.get("home_team")
    away_team = df.get("away_team")
    if home_team is None or away_team is None:
        return {}

    stl_home_mask = home_team == STL_TEAM_ABBR
    stl_away_mask = away_team == STL_TEAM_ABBR

    inning_topbot = df.get("inning_topbot")
    if inning_topbot is None:
        return {}
    stl_hitting = df[
        ((stl_away_mask) & (inning_topbot == "Top"))
        | ((stl_home_mask) & (inning_topbot == "Bot"))
    ].copy()
    stl_pitching = df[
        ((stl_away_mask) & (inning_topbot == "Bot"))
        | ((stl_home_mask) & (inning_topbot == "Top"))
    ].copy()

    highlights: dict[str, list] = {}

    # ---- Hitter highlights ----
    hit_events = stl_hitting[stl_hitting["type"] == "X"].copy()
    if not hit_events.empty and "launch_speed" in hit_events.columns:
        hardest = (
            hit_events.dropna(subset=["launch_speed"])
            .nlargest(3, "launch_speed")
        )
        highlights["hardest_hit"] = [
            {
                "batter": _safe(row, "player_name"),
                "ev_mph": _round(row, "launch_speed", 1),
                "la_deg": _round(row, "launch_angle", 1),
                "xba": _round(row, "estimated_ba_using_speedangle", 3),
                "xwoba": _round(row, "estimated_woba_using_speedangle", 3),
                "outcome": _safe(row, "events") or _safe(row, "description"),
            }
            for _, row in hardest.iterrows()
        ]

    if "estimated_woba_using_speedangle" in hit_events.columns:
        best_xwoba = (
            hit_events.dropna(subset=["estimated_woba_using_speedangle"])
            .nlargest(3, "estimated_woba_using_speedangle")
        )
        highlights["best_xwoba"] = [
            {
                "batter": _safe(row, "player_name"),
                "xwoba": _round(row, "estimated_woba_using_speedangle", 3),
                "ev_mph": _round(row, "launch_speed", 1),
                "outcome": _safe(row, "events") or _safe(row, "description"),
            }
            for _, row in best_xwoba.iterrows()
        ]

    if "launch_speed_angle" in hit_events.columns:
        barrels = hit_events[hit_events["launch_speed_angle"] == 6.0]
        highlights["barrels"] = [
            {
                "batter": _safe(row, "player_name"),
                "ev_mph": _round(row, "launch_speed", 1),
                "la_deg": _round(row, "launch_angle", 1),
                "outcome": _safe(row, "events") or _safe(row, "description"),
            }
            for _, row in barrels.iterrows()
        ]

    # ---- Pitcher highlights ----
    # Note: player_name is the BATTER for these rows. Use `_pitcher_name(row, pid_to_name)`
    # which looks up the `pitcher` MLBAM id against the boxscore name map.
    if not stl_pitching.empty and "release_speed" in stl_pitching.columns:
        top_pitches = (
            stl_pitching.dropna(subset=["release_speed"])
            .nlargest(3, "release_speed")
        )
        highlights["top_pitches"] = [
            {
                "pitcher": _pitcher_name(row, pid_to_name),
                "velo_mph": _round(row, "release_speed", 1),
                "pitch_type": _safe(row, "pitch_name"),
                "outcome": _safe(row, "description") or _safe(row, "events"),
            }
            for _, row in top_pitches.iterrows()
        ]

    # Top whiffs (swinging strikes), top 3 by velocity
    if "description" in stl_pitching.columns and "release_speed" in stl_pitching.columns:
        whiffs = stl_pitching[stl_pitching["description"] == "swinging_strike"]
        if not whiffs.empty:
            top_whiffs = whiffs.dropna(subset=["release_speed"]).nlargest(3, "release_speed")
            highlights["top_whiffs"] = [
                {
                    "pitcher": _pitcher_name(row, pid_to_name),
                    "velo_mph": _round(row, "release_speed", 1),
                    "pitch_type": _safe(row, "pitch_name"),
                    "spin_rpm": _round(row, "release_spin_rate", 0),
                }
                for _, row in top_whiffs.iterrows()
            ]

    # Best putaway pitches (the K-ending pitch), top 3 by velocity
    if "events" in stl_pitching.columns and "release_speed" in stl_pitching.columns:
        ks = stl_pitching[stl_pitching["events"] == "strikeout"]
        if not ks.empty:
            top_putaways = ks.dropna(subset=["release_speed"]).nlargest(3, "release_speed")
            highlights["best_putaways"] = [
                {
                    "pitcher": _pitcher_name(row, pid_to_name),
                    "pitch_type": _safe(row, "pitch_name"),
                    "velo_mph": _round(row, "release_speed", 1),
                    "result": _safe(row, "description"),  # swinging_strike / called_strike
                }
                for _, row in top_putaways.iterrows()
            ]

    # Lowest xwOBA allowed on contact (best contact-suppression pitches), top 3
    if (
        not stl_pitching.empty
        and "estimated_woba_using_speedangle" in stl_pitching.columns
    ):
        contact = stl_pitching[stl_pitching["type"] == "X"].dropna(
            subset=["estimated_woba_using_speedangle"]
        )
        if not contact.empty:
            best_suppression = contact.nsmallest(3, "estimated_woba_using_speedangle")
            highlights["lowest_xwoba_allowed"] = [
                {
                    "pitcher": _pitcher_name(row, pid_to_name),
                    "pitch_type": _safe(row, "pitch_name"),
                    "velo_mph": _round(row, "release_speed", 1),
                    "xwoba": _round(row, "estimated_woba_using_speedangle", 3),
                    "outcome": _safe(row, "events") or _safe(row, "description"),
                }
                for _, row in best_suppression.iterrows()
            ]

    return highlights


def _line_score_from_game(game_id: int) -> dict | None:
    """Pull the linescore (innings + totals) via the MLB Stats API.

    Returns a dict with `innings`, `totals`, and team labels, or None on failure.
    Note: statsapi.boxscore_data() does NOT include linescore, so we hit the
    `game_linescore` endpoint directly via statsapi.get().
    """
    data = _retry(statsapi.get, "game_linescore", {"gamePk": game_id})
    if not data or not data.get("innings"):
        return None
    innings = []
    for inn in data["innings"]:
        innings.append({
            "num": inn.get("num"),
            "away": {
                "runs": (inn.get("away") or {}).get("runs"),
                "hits": (inn.get("away") or {}).get("hits"),
                "errors": (inn.get("away") or {}).get("errors"),
            },
            "home": {
                "runs": (inn.get("home") or {}).get("runs"),
                "hits": (inn.get("home") or {}).get("hits"),
                "errors": (inn.get("home") or {}).get("errors"),
            },
        })
    teams = data.get("teams") or {}
    totals = {
        "away": {
            "R": (teams.get("away") or {}).get("runs"),
            "H": (teams.get("away") or {}).get("hits"),
            "E": (teams.get("away") or {}).get("errors"),
        },
        "home": {
            "R": (teams.get("home") or {}).get("runs"),
            "H": (teams.get("home") or {}).get("hits"),
            "E": (teams.get("home") or {}).get("errors"),
        },
    }
    return {"innings": innings, "totals": totals}


def _safe(row: pd.Series, col: str) -> Any:
    val = row.get(col) if hasattr(row, "get") else None
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return val


def _round(row: pd.Series, col: str, ndigits: int) -> float | None:
    val = _safe(row, col)
    if val is None:
        return None
    try:
        return round(float(val), ndigits)
    except (TypeError, ValueError):
        return None


def get_cardinals_postgame(target_date: date) -> dict | None:
    """Return Cardinals postgame summary for `target_date`, or None if no game.

    Output shape:
      {
        "date": "YYYY-MM-DD",
        "matchup": "STL @ LAD",
        "result": "STL 5, LAD 3 (STL W)",
        "status": "Final",
        "boxscore": { "batters": [...], "pitchers": [...] },
        "statcast_highlights": {
            "hardest_hit": [...],
            "best_xwoba": [...],
            "top_pitches": [...],
            "barrels": [...],
        }
      }
    """
    game = _find_stl_game(target_date)
    if game is None:
        log.info("No STL game found on %s", target_date.isoformat())
        return None

    matchup = f"{game.get('away_name', '?')} @ {game.get('home_name', '?')}"
    result = _format_score_line(game)
    game_pk = game["game_id"]
    payload: dict = {
        "date": target_date.isoformat(),
        "matchup": matchup,
        "result": result,
        "status": game.get("status"),
        "winning_pitcher": game.get("winning_pitcher"),
        "losing_pitcher": game.get("losing_pitcher"),
        "save_pitcher": game.get("save_pitcher"),
        "venue": game.get("venue_name"),
        "away_team": game.get("away_name"),
        "home_team": game.get("home_name"),
        "stl_is_home": game.get("home_id") == STL_TEAM_ID,
        "game_pk": game_pk,
        "savant_url": f"https://baseballsavant.mlb.com/gamefeed?date={target_date.isoformat()}&gamePk={game_pk}",
        "boxscore": {"batters": [], "pitchers": []},
        "line_score": None,
        "statcast_highlights": {},
    }

    box = _retry(statsapi.boxscore_data, game["game_id"])
    pid_to_name: dict[int, str] = {}
    if box:
        payload["boxscore"]["batters"] = _stl_batters_from_box(box)
        payload["boxscore"]["pitchers"] = _stl_pitchers_from_box(box)
        pid_to_name = _build_pid_to_name(box)
    else:
        log.warning("Boxscore unavailable for game %s", game.get("game_id"))

    line_score = _line_score_from_game(game["game_id"])
    if line_score:
        payload["line_score"] = line_score
    else:
        log.warning("Line score unavailable for game %s", game.get("game_id"))

    # statcast_single_game returns BOTH halves (STL hitting + STL pitching) with
    # correct player_name per pitch. pybaseball.statcast(team='STL') only returns
    # the half where STL is pitching, which silently drops every hitter highlight.
    df = _retry(pybaseball.statcast_single_game, game["game_id"])
    if df is not None and not df.empty:
        payload["statcast_highlights"] = _statcast_highlights(df, pid_to_name)
    else:
        log.info("Statcast data not yet available for %s; returning boxscore only", target_date.isoformat())

    return payload


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    target = date.today() - timedelta(days=1)
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    data = get_cardinals_postgame(target)
    print(json.dumps(data, indent=2, default=str))
