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

import httpx
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


SAVANT_GAMEFEED_URL = "https://baseballsavant.mlb.com/gf?game_pk={pk}"


def _fetch_savant_gamefeed(game_pk: int) -> dict | None:
    """Pull the Baseball Savant per-game JSON gamefeed.

    Returns the parsed dict, or None on failure. Much faster + more reliable than
    pybaseball.statcast_single_game for fresh games — the CSV-search endpoint
    pybaseball uses lags hours behind the gamefeed JSON endpoint, especially
    for Sunday games or late West Coast slots.
    """
    url = SAVANT_GAMEFEED_URL.format(pk=game_pk)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning(
                "Savant gamefeed attempt %d/%d failed: %s",
                attempt, MAX_RETRIES, e,
            )
            if attempt == MAX_RETRIES:
                return None
            time.sleep(RETRY_DELAY_S)
    return None


def _gf_safe(d: dict, key: str) -> Any:
    val = d.get(key)
    if val is None or val == "":
        return None
    return val


def _gf_float(d: dict, key: str, ndigits: int | None = None) -> float | None:
    """Coerce a gamefeed value to float, optionally rounded."""
    v = d.get(key)
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return round(f, ndigits) if ndigits is not None else f
    except (TypeError, ValueError):
        return None


def _xba_to_float(v: str | float | None) -> float | None:
    """Savant returns xBA as a string like '.410' or '1.000'. Coerce to float."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except ValueError:
        return None


def _is_barrel(launch_speed: float | None, launch_angle: float | None) -> bool:
    """Statcast-style barrel approximation when the gamefeed doesn't ship the
    explicit `launch_speed_angle == 6` classifier. Uses the standard
    "EV ≥ 98 mph with launch angle between 26° and 30° at the floor, expanding
    with higher EV" rule. Close enough for highlight purposes.
    """
    if launch_speed is None or launch_angle is None:
        return False
    if launch_speed < 98:
        return False
    # Permissive expansion: at EV=98 angle 26-30; at EV=99 angle 25-31; etc.
    expand = max(0, int(launch_speed - 98))
    return (26 - expand) <= launch_angle <= (30 + expand)


def _highlights_from_gamefeed(gf: dict) -> dict[str, list]:
    """Build the same `statcast_highlights` payload from Savant's gamefeed JSON.

    Same shape as `_statcast_highlights` so the prompt template doesn't change.
    Uses xBA in place of xwOBA (gamefeed doesn't expose xwOBA on every event).
    """
    if not gf:
        return {}

    # All pitch-level events live in team_home + team_away lists.
    # team_batting/team_fielding tell us who's on offense vs defense.
    pitches: list[dict] = []
    pitches.extend(gf.get("team_home") or [])
    pitches.extend(gf.get("team_away") or [])

    stl_hitting = [p for p in pitches if p.get("team_batting") == STL_TEAM_ABBR]
    stl_pitching = [p for p in pitches if p.get("team_fielding") == STL_TEAM_ABBR]

    # In-play events with launch metrics. EV list is the authoritative ball-in-play set.
    ev_events = gf.get("exit_velocity") or []
    stl_in_play = [e for e in ev_events if e.get("team_batting") == STL_TEAM_ABBR]
    sd_in_play = [e for e in ev_events if e.get("team_fielding") == STL_TEAM_ABBR]

    h: dict[str, list] = {}

    # ---- Hitter highlights (STL hitting in-play) ----
    if stl_in_play:
        hardest = sorted(
            (x for x in stl_in_play if _gf_float(x, "launch_speed") is not None),
            key=lambda x: _gf_float(x, "launch_speed") or 0,
            reverse=True,
        )[:3]
        h["hardest_hit"] = [
            {
                "batter": _gf_safe(x, "batter_name"),
                "ev_mph": _gf_float(x, "launch_speed", 1),
                "la_deg": _gf_float(x, "launch_angle", 1),
                "xba": _xba_to_float(x.get("xba")),
                "outcome": _gf_safe(x, "events") or _gf_safe(x, "result"),
            }
            for x in hardest
        ]

        # Best xBA on contact (proxy for xwOBA — gamefeed doesn't expose xwOBA)
        with_xba = [(x, _xba_to_float(x.get("xba"))) for x in stl_in_play]
        with_xba = [(x, v) for x, v in with_xba if v is not None]
        best_xba = sorted(with_xba, key=lambda t: t[1], reverse=True)[:3]
        if best_xba:
            h["best_xba"] = [
                {
                    "batter": _gf_safe(x, "batter_name"),
                    "xba": v,
                    "ev_mph": _gf_float(x, "launch_speed", 1),
                    "outcome": _gf_safe(x, "events") or _gf_safe(x, "result"),
                }
                for x, v in best_xba
            ]

        # Barrels (approximated via EV + LA since gamefeed lacks the explicit classifier)
        barrels = [
            x for x in stl_in_play
            if _is_barrel(_gf_float(x, "launch_speed"), _gf_float(x, "launch_angle"))
        ]
        if barrels:
            h["barrels"] = [
                {
                    "batter": _gf_safe(x, "batter_name"),
                    "ev_mph": _gf_float(x, "launch_speed", 1),
                    "la_deg": _gf_float(x, "launch_angle", 1),
                    "outcome": _gf_safe(x, "events") or _gf_safe(x, "result"),
                }
                for x in barrels
            ]

    # ---- Pitcher highlights (STL pitching events) ----
    if stl_pitching:
        # Top velocity (any pitch, ranked by start_speed)
        with_velo = [(p, _gf_float(p, "start_speed")) for p in stl_pitching]
        with_velo = [(p, v) for p, v in with_velo if v is not None]
        top = sorted(with_velo, key=lambda t: t[1], reverse=True)[:3]
        if top:
            h["top_pitches"] = [
                {
                    "pitcher": _gf_safe(p, "pitcher_name"),
                    "velo_mph": v,
                    "pitch_type": _gf_safe(p, "pitch_name"),
                    "outcome": _gf_safe(p, "description") or _gf_safe(p, "events"),
                }
                for p, v in top
            ]

        # Top whiffs (swinging strikes), top 3 by velocity
        whiffs = [
            p for p in stl_pitching
            if p.get("pitch_call") == "swinging_strike" or p.get("is_strike_swinging")
        ]
        if whiffs:
            top_whiffs = sorted(
                whiffs, key=lambda p: _gf_float(p, "start_speed") or 0, reverse=True
            )[:3]
            h["top_whiffs"] = [
                {
                    "pitcher": _gf_safe(p, "pitcher_name"),
                    "velo_mph": _gf_float(p, "start_speed", 1),
                    "pitch_type": _gf_safe(p, "pitch_name"),
                    "spin_rpm": _gf_float(p, "spin_rate", 0),
                }
                for p in top_whiffs
            ]

        # Best putaway pitches (K-ending)
        ks = [p for p in stl_pitching if p.get("events") == "Strikeout"]
        if ks:
            top_ks = sorted(
                ks, key=lambda p: _gf_float(p, "start_speed") or 0, reverse=True
            )[:3]
            h["best_putaways"] = [
                {
                    "pitcher": _gf_safe(p, "pitcher_name"),
                    "pitch_type": _gf_safe(p, "pitch_name"),
                    "velo_mph": _gf_float(p, "start_speed", 1),
                    "result": _gf_safe(p, "pitch_call") or _gf_safe(p, "description"),
                }
                for p in top_ks
            ]

        # Lowest xBA allowed on contact (best contact-suppression)
        with_xba_allowed = [(x, _xba_to_float(x.get("xba"))) for x in sd_in_play]
        with_xba_allowed = [(x, v) for x, v in with_xba_allowed if v is not None]
        if with_xba_allowed:
            suppressed = sorted(with_xba_allowed, key=lambda t: t[1])[:3]
            h["lowest_xba_allowed"] = [
                {
                    "pitcher": _gf_safe(x, "pitcher_name"),
                    "pitch_type": _gf_safe(x, "pitch_name"),
                    "velo_mph": _gf_float(x, "start_speed", 1),
                    "xba": v,
                    "outcome": _gf_safe(x, "events") or _gf_safe(x, "result"),
                }
                for x, v in suppressed
            ]

    return h


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
    # Primary source: Savant's per-game JSON gamefeed. Populated within minutes
    # of game end — much faster than the CSV-search endpoint pybaseball uses.
    gf = _fetch_savant_gamefeed(game_pk)
    if gf:
        highlights = _highlights_from_gamefeed(gf)
        if highlights:
            payload["statcast_highlights"] = highlights
            log.info("Statcast highlights from Savant gamefeed: %s",
                     ", ".join(f"{k}={len(v)}" for k, v in highlights.items()))

    # Fallback: pybaseball single-game CSV (sometimes has data the gamefeed misses,
    # or vice versa). Only try this if the gamefeed produced no usable highlights.
    if not payload["statcast_highlights"]:
        try:
            df = _retry(pybaseball.statcast_single_game, game_pk)
            if df is not None and not df.empty:
                payload["statcast_highlights"] = _statcast_highlights(df, pid_to_name)
        except Exception as e:
            log.warning("pybaseball fallback failed: %s", e)

    if not payload["statcast_highlights"]:
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
