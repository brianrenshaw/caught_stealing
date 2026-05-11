"""Fetch condensed postgame data for every MLB game on a given date.

Used by `scripts/mlb_daily_roundup.py` to build a daily league-wide roundup
post for Blot. Mirrors `app/services/cardinals_postgame.py` but team-agnostic:
returns one payload per regular-season game, with line score, WP/LP/SV,
top-WPA key swings, and a few cross-team Statcast highlights pulled from
the Savant gamefeed JSON.

Synchronous — called from a CLI script.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import statsapi

from app.services.bbref_boxscore import get_bbref_boxscore
from app.services.cardinals_postgame import (
    _fetch_savant_gamefeed,
    _game_context_from_gamefeed,
    _gf_float,
    _gf_safe,
    _line_score_from_game,
    _retry,
    _scoring_plays_from_gamefeed,
    _top_performers_from_gamefeed,
    _xba_to_float,
)
from app.services.play_annotations import (
    annotate_with_rbi,
    annotate_with_season_totals,
)

log = logging.getLogger(__name__)

# Common MLB team abbreviation overrides so a "{abbr} {score} @ {abbr} {score}"
# header reads naturally even when a city contains multiple teams.
TEAM_ABBR: dict[str, str] = {
    "Arizona Diamondbacks": "ARI",
    "Athletics": "ATH",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CHW",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


# Two-word short names where the final word is ambiguous on its own
# (e.g. Red Sox vs White Sox both short to "Sox").
SHORT_NAME_OVERRIDES: dict[str, str] = {
    "Boston Red Sox": "Red Sox",
    "Chicago White Sox": "White Sox",
    "Toronto Blue Jays": "Blue Jays",
    "Tampa Bay Rays": "Rays",
}


def _team_short(full_name: str) -> str:
    """Short team label for headers: 'Padres' from 'San Diego Padres'."""
    if not full_name:
        return "?"
    if full_name in SHORT_NAME_OVERRIDES:
        return SHORT_NAME_OVERRIDES[full_name]
    parts = full_name.split()
    return parts[-1] if parts else full_name


def _hardest_hit_all_teams(gf: dict, n: int = 3) -> list[dict]:
    """Top `n` batted balls by exit velocity across both teams in the game."""
    if not gf:
        return []
    ev_list = gf.get("exit_velocity") or []
    rows = [e for e in ev_list if _gf_float(e, "launch_speed") is not None]
    rows.sort(key=lambda e: _gf_float(e, "launch_speed") or 0, reverse=True)
    out: list[dict] = []
    for e in rows[:n]:
        out.append({
            "batter": _gf_safe(e, "batter_name"),
            "team_batting": _gf_safe(e, "team_batting"),
            "ev_mph": _gf_float(e, "launch_speed", 1),
            "la_deg": _gf_float(e, "launch_angle", 1),
            "xba": _xba_to_float(e.get("xba")),
            "outcome": _gf_safe(e, "events") or _gf_safe(e, "result"),
        })
    return out


def _key_swings_home_relative(gf: dict, n: int = 4) -> list[dict]:
    """Top `n` at-bats by |WPA Δ| with home-team-relative orientation.

    Mirrors `cardinals_postgame._wpa_leaders_from_gamefeed` but keeps deltas
    in MLB's native frame (positive = home team gained win probability) since
    the roundup has no STL-centric viewpoint to flip toward. Returned shape
    matches the Cardinals key_swings shape so the renderer can stay generic.
    """
    if not gf:
        return []
    wpa = (gf.get("scoreboard") or {}).get("stats", {}).get("wpa") or {}
    game_wpa = wpa.get("gameWpa") or []
    if not game_wpa:
        return []

    pitches = (gf.get("team_home") or []) + (gf.get("team_away") or [])
    ab_last_pitch: dict[int, dict] = {}
    for p in pitches:
        ab = p.get("ab_number")
        if ab is None:
            continue
        prev = ab_last_pitch.get(ab)
        if prev is None or (p.get("pitch_number") or 0) > (prev.get("pitch_number") or 0):
            ab_last_pitch[ab] = p

    top = sorted(
        game_wpa,
        key=lambda w: abs(w.get("homeTeamWinProbabilityAdded") or 0),
        reverse=True,
    )[:n]
    out: list[dict] = []
    for w in top:
        atbi = w.get("atBatIndex")
        if atbi is None:
            continue
        # Empirical offset: atBatIndex N maps to ab_number N+1 in the pitch stream.
        play = ab_last_pitch.get(atbi + 1)
        if not play or not play.get("events"):
            continue
        out.append({
            "inning_half": w.get("i"),
            "wpa_delta_pct": round(float(w.get("homeTeamWinProbabilityAdded") or 0), 1),
            "home_wp_after_pct": round(float(w.get("homeTeamWinProbability") or 0), 1),
            "batter": play.get("batter_name"),
            "pitcher": play.get("pitcher_name"),
            "team_batting": play.get("team_batting"),
            "event": play.get("events"),
            "description": (play.get("des") or "").strip(),
            "ev_mph": _gf_float(play, "launch_speed", 1),
            "pitch_velo_mph": _gf_float(play, "start_speed", 1),
            "pitch_type": play.get("pitch_name"),
        })
    return out


def _top_pitches_all_teams(gf: dict, n: int = 3) -> list[dict]:
    """Hardest `n` pitches by velocity across both teams in the game."""
    if not gf:
        return []
    pitches = (gf.get("team_home") or []) + (gf.get("team_away") or [])
    with_velo = [
        (p, _gf_float(p, "start_speed")) for p in pitches
        if _gf_float(p, "start_speed") is not None
    ]
    with_velo.sort(key=lambda t: t[1], reverse=True)
    out: list[dict] = []
    for p, v in with_velo[:n]:
        out.append({
            "pitcher": _gf_safe(p, "pitcher_name"),
            "team_fielding": _gf_safe(p, "team_fielding"),
            "batter": _gf_safe(p, "batter_name"),
            "velo_mph": v,
            "pitch_type": _gf_safe(p, "pitch_name"),
            "outcome": _gf_safe(p, "description") or _gf_safe(p, "events"),
        })
    return out


def _games_on(target_date: date) -> list[dict]:
    """Return regular-season final games on `target_date` via MLB Stats API."""
    games = _retry(
        statsapi.schedule,
        date=target_date.strftime("%m/%d/%Y"),
        sportId=1,
    ) or []
    out: list[dict] = []
    for g in games:
        if g.get("game_type") != "R":
            continue
        status = (g.get("status") or "").lower()
        if "final" not in status and "completed" not in status:
            continue
        out.append(g)
    return out


def _game_payload(game: dict) -> dict[str, Any]:
    """Build a condensed per-game payload from MLB Stats API + Savant gamefeed."""
    game_pk = game.get("game_id")
    away_full = game.get("away_name") or "?"
    home_full = game.get("home_name") or "?"
    away_abbr = TEAM_ABBR.get(away_full, _team_short(away_full).upper()[:3])
    home_abbr = TEAM_ABBR.get(home_full, _team_short(home_full).upper()[:3])

    payload: dict[str, Any] = {
        "game_pk": game_pk,
        "away_team": away_full,
        "home_team": home_full,
        "away_short": _team_short(away_full),
        "home_short": _team_short(home_full),
        "away_abbr": away_abbr,
        "home_abbr": home_abbr,
        "away_score": game.get("away_score"),
        "home_score": game.get("home_score"),
        "status": game.get("status"),
        "venue": game.get("venue_name"),
        "winning_pitcher": game.get("winning_pitcher"),
        "losing_pitcher": game.get("losing_pitcher"),
        "save_pitcher": game.get("save_pitcher") or None,
        "game_datetime": game.get("game_datetime"),
        "savant_url": (
            f"https://baseballsavant.mlb.com/gamefeed?gamePk={game_pk}"
            if game_pk else None
        ),
        "line_score": None,
        "scoring_plays": [],
        "key_swings": [],
        "game_context": {},
        "hardest_hit": [],
        "top_pitches": [],
    }

    if not game_pk:
        return payload

    ls = _line_score_from_game(game_pk)
    if ls:
        payload["line_score"] = ls

    gf = _fetch_savant_gamefeed(game_pk)
    if not gf:
        log.info("Savant gamefeed unavailable for game_pk=%s", game_pk)
        return payload

    scoring = _scoring_plays_from_gamefeed(gf)
    if scoring:
        annotate_with_season_totals(scoring)
        annotate_with_rbi(scoring)
        payload["scoring_plays"] = scoring

    key_swings = _key_swings_home_relative(gf, n=4)
    if key_swings:
        annotate_with_season_totals(key_swings)
        annotate_with_rbi(key_swings)
        payload["key_swings"] = key_swings

    ctx = _game_context_from_gamefeed(gf)
    if ctx:
        payload["game_context"] = ctx

    hh = _hardest_hit_all_teams(gf, n=3)
    if hh:
        payload["hardest_hit"] = hh

    tp = _top_pitches_all_teams(gf, n=3)
    if tp:
        payload["top_pitches"] = tp

    # MLB's curated top performers for the game — each carries a one-line
    # batting or pitching stat summary ("3-for-4, 1 HR, 2 RBI" / "6.0 IP, 1 ER,
    # 9 K, 1 BB"). Gives Claude a clean source of stat-line callouts in prose.
    performers = _top_performers_from_gamefeed(gf)
    if performers:
        # Drop the STL-only flag (Cardinals digest uses it; roundup doesn't care).
        for p in performers:
            p.pop("is_stl", None)
        payload["top_performers"] = performers

    # Baseball Reference cross-reference. Pulls the bbref play-by-play table
    # plus pitcher game_score values for both teams. The fact-checker uses the
    # PBP as a SECOND source against Savant's scoring_plays / key_swings,
    # catching cases where one source is misread.
    away_full = game.get("away_name") or ""
    home_full = game.get("home_name") or ""
    try:
        game_date = date.fromisoformat((game.get("game_date") or "")[:10])
    except (TypeError, ValueError):
        game_date = None
    # Doubleheader mapping: doubleheader == "N" → URL index 0 (single game),
    # otherwise URL index matches game_num (1 or 2).
    dh_flag = (game.get("doubleheader") or "N").upper()
    game_num = int(game.get("game_num") or 1)
    dh_index = 0 if dh_flag == "N" else game_num
    if game_date and away_full and home_full:
        bbref = get_bbref_boxscore(game_date, away_full, home_full, dh_index)
        if bbref:
            payload["bbref"] = bbref

    return payload


def get_mlb_roundup(game_date: date) -> list[dict]:
    """Return a per-game payload for every regular-season final on `game_date`.

    Empty list if no games (rare — typically only the All-Star break or the
    morning after the World Series). Order: chronological by game start time.
    """
    games = _games_on(game_date)
    if not games:
        log.info("No regular-season games on %s", game_date.isoformat())
        return []

    games.sort(key=lambda g: g.get("game_datetime") or "")

    out: list[dict] = []
    for g in games:
        try:
            out.append(_game_payload(g))
        except Exception as e:
            log.warning(
                "Game payload failed for game_pk=%s: %s",
                g.get("game_id"), e,
            )
            continue
    log.info("Built %d game payloads for %s", len(out), game_date.isoformat())
    return out


if __name__ == "__main__":
    import json
    import sys
    from datetime import timedelta

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    target = date.today() - timedelta(days=1)
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    print(json.dumps(get_mlb_roundup(target), indent=2, default=str))
