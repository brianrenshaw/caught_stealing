"""Weekly matchup service — fetches H2H matchup data and computes category breakdowns.

Uses matchup_quality_service for Phases 1-4 of matchup adjustments.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

import statsapi as statsapi_module
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import default_season
from app.league_config import BATTING_SCORING, PITCHING_SCORING
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.roster import Roster
from app.models.weekly_matchup import WeeklyMatchupSnapshot
from app.services.matchup_quality_service import (
    GameDetail,
    compute_hitter_pitcher_mults,
    compute_park_mult,
    compute_pitcher_offense_mults,
    compute_platoon_ratios,
    get_opponent_team,
    get_opposing_pitcher_id,
    get_pitcher_handedness,
    get_pitcher_quality,
    get_player_home_park,
    get_team_abbrev,
    get_team_games,
    get_team_wrc_plus,
    get_weekly_game_details,
)
from app.services.yahoo_service import yahoo_service

# Map our DB team abbreviations to MLB Stats API team IDs
_TEAM_ID_CACHE: dict[str, int] = {}


async def _get_mlb_team_id(abbrev: str) -> int | None:
    """Look up MLB Stats API team ID from abbreviation."""
    if not _TEAM_ID_CACHE:
        try:
            data = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: statsapi_module.get("teams", {"sportId": 1}),
            )
            for t in data.get("teams", []):
                _TEAM_ID_CACHE[t["abbreviation"]] = t["id"]
            # Common aliases
            _TEAM_ID_CACHE["ARI"] = _TEAM_ID_CACHE.get("AZ", 0)
            _TEAM_ID_CACHE["AZ"] = _TEAM_ID_CACHE.get("AZ", 0)
            _TEAM_ID_CACHE["CWS"] = _TEAM_ID_CACHE.get("CHW", 0)
            _TEAM_ID_CACHE["CHW"] = _TEAM_ID_CACHE.get("CHW", 0)
            _TEAM_ID_CACHE["WSH"] = _TEAM_ID_CACHE.get("WAS", 0)
            _TEAM_ID_CACHE["WAS"] = _TEAM_ID_CACHE.get("WAS", 0)
        except Exception as e:
            logger.warning(f"Failed to load MLB team IDs: {e}")
    return _TEAM_ID_CACHE.get(abbrev)


async def _get_team_week_games(
    team_abbrev: str,
    week_start: str,
    week_end: str,
) -> int:
    """Get how many regular-season games a team plays in a date range.

    Filters out spring training (game_type='S') and other non-regular games.
    """
    team_id = await _get_mlb_team_id(team_abbrev)
    if not team_id:
        return 6  # default estimate
    try:
        games = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: statsapi_module.schedule(
                start_date=week_start,
                end_date=week_end,
                team=team_id,
                sportId=1,
            ),
        )
        if not games:
            return 6
        # Only count regular season games
        reg_games = [g for g in games if g.get("game_type") == "R"]
        return len(reg_games) if reg_games else 0
    except Exception:
        return 6


async def _get_probable_starters_for_week(
    week_start: str,
    week_end: str,
) -> dict[int, int]:
    """Get probable starter counts for the week (regular season only).

    Returns: {mlbam_id: number_of_starts}
    """
    counts: dict[int, int] = {}
    try:
        start = datetime.strptime(week_start, "%Y-%m-%d").date()
        end = datetime.strptime(week_end, "%Y-%m-%d").date()

        # Fetch full schedule for the date range to filter by game_type
        current = start
        while current <= end:
            date_str = current.strftime("%m/%d/%Y")
            schedule = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda d=date_str: statsapi_module.schedule(
                    date=d, sportId=1
                ),
            )
            for game in schedule:
                # Only count regular season games
                if game.get("game_type") != "R":
                    continue
                away_id = game.get("away_pitcher_id")
                home_id = game.get("home_pitcher_id")
                if away_id:
                    counts[int(away_id)] = counts.get(int(away_id), 0) + 1
                if home_id:
                    counts[int(home_id)] = counts.get(int(home_id), 0) + 1
            current += timedelta(days=1)
    except Exception as e:
        logger.warning(f"Failed to get probable starters: {e}")
    return counts

logger = logging.getLogger(__name__)

# Yahoo stat_id → our scoring category name mapping
# These are the standard Yahoo stat IDs for MLB
YAHOO_BATTING_STAT_MAP = {
    7: "R",
    8: "H",
    10: "2B",
    11: "3B",
    12: "HR",
    13: "RBI",
    16: "SB",
    17: "CS",
    18: "BB",
    21: "K",    # Batter strikeouts
    50: "HBP",
}

YAHOO_PITCHING_STAT_MAP = {
    28: "W",
    32: "SV",
    33: "OUT",  # Yahoo reports outs pitched
    34: "H",
    35: "BB",
    37: "ER",
    39: "K",    # Pitcher strikeouts
    42: "HLD",
    48: "QS",
    57: "CG",
    58: "SHO",
    59: "NH",
    # PG (perfect game) may not have a standard stat_id
}

# Derive singles from H - 2B - 3B - HR
# We'll handle this in the aggregation


def _decode_team_name(name) -> str:
    """Decode yfpy team name which may be bytes."""
    if isinstance(name, bytes):
        return name.decode("utf-8")
    return str(name) if name else "Unknown"


def _parse_player_weekly_stats(players: list, stat_categories: dict | None = None) -> dict:
    """Parse yfpy Player objects into aggregated stat dicts.

    Returns:
        {
            "batting": {"R": 5, "H": 12, "2B": 3, "3B": 0, "HR": 2, ...},
            "pitching": {"OUT": 120, "K": 45, "SV": 2, ...},
            "players": [{"name": "...", "points": 10.5, "stats": {...}}, ...]
        }
    """
    batting_totals: dict[str, float] = {}
    pitching_totals: dict[str, float] = {}
    player_list = []

    for player in players:
        player_name = getattr(player, "full_name", "") or ""
        if not player_name:
            name_obj = getattr(player, "name", None)
            if name_obj:
                player_name = getattr(name_obj, "full", "") or ""

        player_points = getattr(player, "player_points_value", 0.0) or 0.0
        player_stats_obj = getattr(player, "player_stats", None)
        stats_list = getattr(player_stats_obj, "stats", []) if player_stats_obj else []

        player_stat_dict = {}
        is_pitcher = False

        for stat in stats_list:
            stat_id = getattr(stat, "stat_id", None)
            value = getattr(stat, "value", 0.0) or 0.0
            if stat_id is None:
                continue

            stat_id = int(stat_id)
            value = float(value)

            if stat_id in YAHOO_BATTING_STAT_MAP:
                cat = YAHOO_BATTING_STAT_MAP[stat_id]
                batting_totals[cat] = batting_totals.get(cat, 0) + value
                player_stat_dict[cat] = value
            elif stat_id in YAHOO_PITCHING_STAT_MAP:
                cat = YAHOO_PITCHING_STAT_MAP[stat_id]
                pitching_totals[cat] = pitching_totals.get(cat, 0) + value
                player_stat_dict[cat] = value
                is_pitcher = True

        # Determine position type from stats
        position = "P" if is_pitcher else "B"
        eligible = getattr(player, "eligible_positions", None)
        if eligible:
            pos_list = (
                [getattr(p, "position", "") for p in eligible]
                if hasattr(eligible, "__iter__")
                else []
            )
            if any(p in ("SP", "RP", "P") for p in pos_list):
                position = "P"

        player_list.append({
            "name": player_name,
            "points": round(player_points, 1),
            "position": position,
            "stats": player_stat_dict,
        })

    # Derive singles for batting
    h = batting_totals.get("H", 0)
    doubles = batting_totals.get("2B", 0)
    triples = batting_totals.get("3B", 0)
    hr = batting_totals.get("HR", 0)
    batting_totals["1B"] = h - doubles - triples - hr

    return {
        "batting": batting_totals,
        "pitching": pitching_totals,
        "players": player_list,
    }


def _compute_category_points(stats: dict) -> dict:
    """Compute fantasy points per category from raw stat totals.

    Returns dict like: {"batting": {"R": {"stat": 5, "pts": 5.0}, ...}, ...}
    """
    batting = stats.get("batting", {})
    pitching = stats.get("pitching", {})

    result = {"batting": {}, "pitching": {}, "total": 0.0}

    for cat, weight in BATTING_SCORING.items():
        raw = batting.get(cat, 0)
        pts = raw * weight
        result["batting"][cat] = {"stat": round(raw, 1), "pts": round(pts, 1)}
        result["total"] += pts

    for cat, weight in PITCHING_SCORING.items():
        raw = pitching.get(cat, 0)
        pts = raw * weight
        result["pitching"][cat] = {"stat": round(raw, 1), "pts": round(pts, 1)}
        result["total"] += pts

    result["total"] = round(result["total"], 1)
    return result


def _scale_players_to_target(
    players: list[dict], target_total: float
) -> None:
    """Scale player projected points/stats so they sum to a target total.

    Modifies players in place. Used to calibrate our rate-based projections
    to Yahoo's schedule-aware team total.
    """
    raw_total = sum(p["proj_pts"] for p in players)
    if raw_total <= 0 or target_total <= 0:
        return
    scale = target_total / raw_total
    for p in players:
        p["proj_pts"] = round(p["proj_pts"] * scale, 1)
        for cat in list(p["proj_stats"].keys()):
            p["proj_stats"][cat] = round(
                p["proj_stats"].get(cat, 0) * scale, 1
            )


def build_matchup_display(snapshot: WeeklyMatchupSnapshot) -> dict:
    """Build player-centric matchup data for template rendering.

    Scales our rate-based projections to match Yahoo's schedule-aware
    team totals, so per-player numbers are realistic for the week.

    Returns:
        {
            "my_hitters": [{"name", "position", "proj_pts", "actual_pts",
                            "proj_stats": {cat: val}, "actual_stats": {cat: val}}, ...],
            "my_pitchers": [...],
            "opp_hitters": [...],
            "opp_pitchers": [...],
            "batting_categories": ["R", "1B", "2B", ...],
            "pitching_categories": ["OUT", "K", "SV", ...],
        }
    """
    my_proj = json.loads(snapshot.my_projected_breakdown or "{}")
    my_actual = json.loads(snapshot.my_actual_breakdown or "{}")
    opp_proj = json.loads(snapshot.opponent_projected_breakdown or "{}")
    opp_actual = json.loads(snapshot.opponent_actual_breakdown or "{}")

    batting_cats = list(BATTING_SCORING.keys())
    pitching_cats = list(PITCHING_SCORING.keys())

    def _build_player_rows(
        proj_data: dict, actual_data: dict
    ) -> tuple[list[dict], list[dict]]:
        proj_players = proj_data.get("players", [])
        actual_players = actual_data.get("players", [])

        # Index actual players by name for matching
        actual_by_name = {p["name"]: p for p in actual_players}

        hitters = []
        pitchers = []

        for pp in proj_players:
            name = pp.get("name", "")
            pos = pp.get("position", "B")
            proj_stats = pp.get("stats", {})
            ap = actual_by_name.get(name, {})
            actual_stats = ap.get("stats", {})

            # Compute projected and actual total points
            scoring = (
                PITCHING_SCORING if pos == "P" else BATTING_SCORING
            )
            proj_pts = sum(
                proj_stats.get(c, 0) * w for c, w in scoring.items()
            )
            actual_pts = sum(
                actual_stats.get(c, 0) * w for c, w in scoring.items()
            )

            row = {
                "name": name,
                "position": pos,
                "roster_position": pp.get("roster_position", pos),
                "proj_pts": round(proj_pts, 1),
                "actual_pts": round(
                    ap.get("points", 0) or actual_pts, 1
                ),
                "proj_stats": proj_stats,
                "actual_stats": actual_stats,
            }

            if pos == "P":
                pitchers.append(row)
            else:
                hitters.append(row)

        return hitters, pitchers

    my_h, my_p = _build_player_rows(my_proj, my_actual)
    opp_h, opp_p = _build_player_rows(opp_proj, opp_actual)

    my_proj_total = sum(p["proj_pts"] for p in my_h + my_p)
    opp_proj_total = sum(p["proj_pts"] for p in opp_h + opp_p)

    return {
        "my_hitters": my_h,
        "my_pitchers": my_p,
        "opp_hitters": opp_h,
        "opp_pitchers": opp_p,
        "my_proj_total": round(my_proj_total, 1),
        "opp_proj_total": round(opp_proj_total, 1),
        "batting_categories": batting_cats,
        "pitching_categories": pitching_cats,
    }


async def _find_current_matchup() -> dict | None:
    """Call Yahoo API to find the current week's matchup.

    Returns: {"week": int, "opponent_team_id": str, "opponent_team_name": str,
              "my_team_id": str, "my_team_name": str,
              "my_projected": float, "opp_projected": float,
              "my_actual": float, "opp_actual": float} or None
    """
    try:
        matchups = await yahoo_service.get_matchup()
        if not matchups:
            return None

        # Find the in-progress or most recent matchup
        current = None
        for m in matchups:
            status = getattr(m, "status", "")
            if status in ("midevent", "preevent", ""):
                current = m
                break
        if current is None and matchups:
            current = matchups[-1]  # fallback to last matchup

        if not current:
            return None

        week = getattr(current, "week", 0)
        teams = getattr(current, "teams", [])
        if not teams or len(teams) < 2:
            return None

        my_team = None
        opp_team = None
        for team in teams:
            if getattr(team, "is_owned_by_current_login", 0):
                my_team = team
            else:
                opp_team = team

        if not my_team or not opp_team:
            return None

        week_start = getattr(current, "week_start", "")
        week_end = getattr(current, "week_end", "")

        return {
            "week": int(week) if week else 0,
            "week_start": str(week_start) if week_start else "",
            "week_end": str(week_end) if week_end else "",
            "my_team_id": str(getattr(my_team, "team_id", "")),
            "my_team_name": _decode_team_name(getattr(my_team, "name", "")),
            "opponent_team_id": str(getattr(opp_team, "team_id", "")),
            "opponent_team_name": _decode_team_name(getattr(opp_team, "name", "")),
            "my_projected": float(getattr(my_team, "projected_points", 0) or 0),
            "opp_projected": float(getattr(opp_team, "projected_points", 0) or 0),
            "my_actual": float(getattr(my_team, "points", 0) or 0),
            "opp_actual": float(getattr(opp_team, "points", 0) or 0),
        }
    except Exception as e:
        logger.error(f"Failed to find current matchup: {e}", exc_info=True)
        return None


async def _fetch_team_player_breakdown(team_id: str, week: int | str = "current") -> dict:
    """Fetch per-player weekly stats for a team and compute category breakdown."""
    try:
        players = await yahoo_service.get_team_roster_weekly_stats(team_id, week)
        if not players:
            return {"batting": {}, "pitching": {}, "players": [], "total": 0}

        parsed = _parse_player_weekly_stats(players)
        breakdown = _compute_category_points(parsed)
        breakdown["players"] = parsed.get("players", [])
        return breakdown
    except Exception as e:
        logger.warning(f"Failed to fetch player breakdown for team {team_id}: {e}")
        return {"batting": {}, "pitching": {}, "players": [], "total": 0}


async def _find_best_stats_season(session: AsyncSession, season: int) -> int:
    """Find the best season for stats data — use requested season if available,
    otherwise fall back to the most recent season with data."""
    result = await session.execute(
        select(BattingStats.season)
        .distinct()
        .order_by(BattingStats.season.desc())
    )
    available = [r[0] for r in result.fetchall()]
    if season in available:
        return season
    return available[0] if available else season


async def _compute_team_projected_breakdown(
    session: AsyncSession,
    team_id: str,
    season: int,
    week_start: str = "",
    week_end: str = "",
) -> dict:
    """Compute projected weekly category stats from DB data.

    Schedule-aware: uses MLB API to determine actual team games for the
    week and probable pitcher starts. Falls back to estimates when
    schedule data isn't available (preseason, etc.).

    Hitters: 4 PA/game * team_games_this_week.
    SP: 6 IP per scheduled start (from probable pitchers).
    RP: ~0.7 IP/game * team_games (closers/setup appear ~60-70% of games).
    """
    full_season_games = 162  # standard MLB season length
    bench_pos = {"BN", "IL", "NA"}

    # Fall back to most recent season with data
    stats_season = await _find_best_stats_season(session, season)

    # Get schedule data for the week (shared infrastructure)
    team_game_cache: dict[str, int] = {}
    probable_starts: dict[int, int] = {}
    game_details: list[GameDetail] = []
    if week_start and week_end:
        try:
            game_details = await get_weekly_game_details(
                week_start, week_end
            )
            for gd in game_details:
                if gd.home_pitcher_id:
                    pid = int(gd.home_pitcher_id)
                    probable_starts[pid] = probable_starts.get(pid, 0) + 1
                if gd.away_pitcher_id:
                    pid = int(gd.away_pitcher_id)
                    probable_starts[pid] = probable_starts.get(pid, 0) + 1
        except Exception:
            pass

    # Get team roster
    result = await session.execute(
        select(Roster)
        .where(Roster.team_id == team_id)
        .options()
    )
    roster_entries = result.scalars().all()

    batting_totals: dict[str, float] = {}
    pitching_totals: dict[str, float] = {}
    player_list = []

    for entry in roster_entries:
        player_id = entry.player_id
        pos = entry.roster_position
        is_bench = pos in bench_pos

        # Get player info
        p_result = await session.execute(
            select(Player).where(Player.id == player_id)
        )
        player = p_result.scalar_one_or_none()
        p_name = player.name if player else "Unknown"
        p_team = player.team if player else ""
        p_mlbam = player.mlbam_id if player else None

        # Get team's games this week (cached per team)
        if p_team and p_team not in team_game_cache and week_start:
            team_game_cache[p_team] = await _get_team_week_games(
                p_team, week_start, week_end
            )
        team_games = team_game_cache.get(p_team, 6)

        is_pitcher = pos in ("SP", "RP", "P") or (
            is_bench
            and player
            and any(
                p in (player.position or "")
                for p in ["SP", "RP", "P"]
            )
        )

        # Bench/IL/NA players: include with zero stats but tagged
        if is_bench:
            player_list.append({
                "name": p_name,
                "points": 0,
                "position": "P" if is_pitcher else "B",
                "roster_position": pos,
                "stats": {},
            })
            continue

        if is_pitcher:
            # Fetch pitching stats
            ps_result = await session.execute(
                select(PitchingStats).where(
                    PitchingStats.player_id == player_id,
                    PitchingStats.season == stats_season,
                    PitchingStats.period == "full_season",
                    PitchingStats.source == "fangraphs",
                )
            )
            ps = ps_result.scalar_one_or_none()
            if not ps or not ps.ip or ps.ip <= 0:
                player_list.append({
                    "name": p_name, "points": 0,
                    "position": "P", "roster_position": pos,
                    "stats": {},
                })
                continue

            ip = ps.ip
            gs = ps.gs or 0
            g = ps.g or 1
            is_sp = gs > 0 and gs / g > 0.5

            if is_sp:
                # Use probable starter data if available
                mlbam_int = (
                    int(p_mlbam) if p_mlbam else None
                )
                starts = probable_starts.get(mlbam_int, 0)
                ip_per_gs = ip / gs if gs > 0 else 5.5
                if starts == 0:
                    # Estimate starts from team games (~1 per 5 games)
                    starts = max(round(team_games / 5, 1), 0)
                weekly_ip = starts * ip_per_gs
            else:
                # Reliever: use per-appearance IP * estimated appearances
                # Appearance rate = G / 162 (% of team games they appear in)
                # e.g., 70 G / 162 = 43% appearance rate
                ip_per_app = ip / g if g > 0 else 1.0
                app_rate = g / full_season_games
                weekly_apps = app_rate * team_games
                weekly_ip = weekly_apps * ip_per_app

            scale = weekly_ip / ip

            proj_stats = {}
            for attr, cat in [
                ("so", "K"), ("sv", "SV"), ("hld", "HLD"),
                ("w", "RW"), ("qs", "QS"), ("h", "H"),
                ("er", "ER"), ("bb", "BB"), ("hbp", "HBP"),
            ]:
                val = getattr(ps, attr, 0) or 0
                proj_stats[cat] = round(val * scale, 1)

            proj_stats["OUT"] = round(weekly_ip * 3, 1)

            # ── Phase 2: Opposing team offense adjustment ──
            team_games_list = get_team_games(p_team, game_details)
            if team_games_list:
                opp_wrc_mults = []
                for gd in team_games_list:
                    opp_full = get_opponent_team(p_team, gd)
                    opp_abbrev = get_team_abbrev(opp_full)
                    if opp_abbrev:
                        opp_wrc = await get_team_wrc_plus(
                            session, opp_abbrev, stats_season
                        )
                        opp_wrc_mults.append(
                            compute_pitcher_offense_mults(opp_wrc)
                        )

                if opp_wrc_mults:
                    for cat in ["H", "ER"]:
                        cat_mults = [
                            m.get(cat, 1.0) for m in opp_wrc_mults
                        ]
                        avg_mult = sum(cat_mults) / len(cat_mults)
                        proj_stats[cat] = round(
                            proj_stats[cat] * avg_mult, 1
                        )

            # ── Phase 3: Park factor adjustment ──
            home_park = get_player_home_park(p_team)
            venue_names = [gd.venue_name for gd in team_games_list]
            if venue_names:
                park_mult = compute_park_mult(home_park, venue_names)
                for cat in ["H", "ER"]:
                    if cat in proj_stats:
                        proj_stats[cat] = round(
                            proj_stats[cat] * park_mult, 1
                        )

            pts = 0
            for cat, weight in PITCHING_SCORING.items():
                val = proj_stats.get(cat, 0)
                pitching_totals[cat] = (
                    pitching_totals.get(cat, 0) + val
                )
                pts += val * weight

            player_list.append({
                "name": p_name, "points": round(pts, 1),
                "position": "P", "roster_position": pos,
                "stats": proj_stats,
            })
        else:
            # Fetch batting stats
            bs_result = await session.execute(
                select(BattingStats).where(
                    BattingStats.player_id == player_id,
                    BattingStats.season == stats_season,
                    BattingStats.period == "full_season",
                    BattingStats.source == "fangraphs",
                )
            )
            bs = bs_result.scalar_one_or_none()
            if not bs or not bs.pa or bs.pa <= 0:
                player_list.append({
                    "name": p_name, "points": 0,
                    "position": "B", "roster_position": pos,
                    "stats": {},
                })
                continue

            pa = bs.pa
            # Schedule-aware: PA per game * team games this week
            full_season_games = 162
            pa_per_game_player = pa / full_season_games
            weekly_pa = pa_per_game_player * team_games
            scale = weekly_pa / pa

            proj_stats = {}
            for attr, cat in [
                ("r", "R"), ("doubles", "2B"), ("triples", "3B"),
                ("hr", "HR"), ("rbi", "RBI"), ("sb", "SB"),
                ("cs", "CS"), ("bb", "BB"), ("hbp", "HBP"),
                ("so", "K"), ("h", "H"),
            ]:
                val = getattr(bs, attr, 0) or 0
                proj_stats[cat] = round(val * scale, 1)

            # Derive singles
            h = proj_stats.get("H", 0)
            d = proj_stats.get("2B", 0)
            t = proj_stats.get("3B", 0)
            hr = proj_stats.get("HR", 0)
            proj_stats["1B"] = round(h - d - t - hr, 1)

            # ── Phases 1, 3, 4: Matchup quality adjustments ──
            team_games_list = get_team_games(p_team, game_details)
            if team_games_list:
                game_mults: list[dict[str, float]] = []
                for gd in team_games_list:
                    opp_pid = get_opposing_pitcher_id(p_team, gd)

                    # Phase 4: Try platoon split first
                    platoon_used = False
                    if opp_pid:
                        hand = await get_pitcher_handedness(opp_pid)
                        if hand:
                            split_key = (
                                "vs_lhp" if hand == "L" else "vs_rhp"
                            )
                            try:
                                from app.services.splits_service import (
                                    get_splits,
                                )

                                splits = await get_splits(
                                    session, player_id, stats_season
                                )
                                split_data = splits.get(split_key)
                                if split_data:
                                    overall = {
                                        "woba": bs.woba,
                                        "avg": bs.avg,
                                        "iso": bs.iso,
                                        "k_pct": bs.k_pct,
                                        "bb_pct": bs.bb_pct,
                                    }
                                    bats_right = hand == "L"
                                    ratios = compute_platoon_ratios(
                                        split_data, overall, bats_right
                                    )
                                    if ratios:
                                        game_mults.append(ratios)
                                        platoon_used = True
                            except Exception:
                                pass

                    # Phase 1: Fall back to pitcher quality if no platoon
                    if not platoon_used:
                        if opp_pid:
                            quality = await get_pitcher_quality(
                                session, opp_pid, stats_season
                            )
                            game_mults.append(
                                compute_hitter_pitcher_mults(
                                    quality["siera"],
                                    quality["k_pct"],
                                    quality["bb_pct"],
                                )
                            )
                        else:
                            game_mults.append({})

                # Average multipliers across games
                if game_mults:
                    for cat in list(proj_stats.keys()):
                        cat_mults = [
                            m.get(cat, 1.0) for m in game_mults
                        ]
                        avg_mult = sum(cat_mults) / len(cat_mults)
                        proj_stats[cat] = round(
                            proj_stats[cat] * avg_mult, 1
                        )

            # ── Phase 3: Park factor adjustment ──
            home_park = get_player_home_park(p_team)
            venue_names = [gd.venue_name for gd in team_games_list]
            if venue_names:
                park_mult = compute_park_mult(home_park, venue_names)
                for cat in ["R", "H", "1B", "2B", "3B", "HR", "RBI"]:
                    if cat in proj_stats:
                        proj_stats[cat] = round(
                            proj_stats[cat] * park_mult, 1
                        )

            # Clamp total adjustment (safety)
            pts = 0
            for cat, weight in BATTING_SCORING.items():
                val = proj_stats.get(cat, 0)
                batting_totals[cat] = (
                    batting_totals.get(cat, 0) + val
                )
                pts += val * weight

            player_list.append({
                "name": p_name, "points": round(pts, 1),
                "position": "B", "roster_position": pos,
                "stats": proj_stats,
            })

    # Build the breakdown
    result_data = _compute_category_points({
        "batting": batting_totals,
        "pitching": pitching_totals,
    })
    result_data["players"] = player_list
    return result_data


async def get_or_create_weekly_snapshot(
    session: AsyncSession,
    season: int | None = None,
) -> WeeklyMatchupSnapshot | None:
    """Get or create the weekly matchup snapshot.

    On first access for a new week: creates snapshot with frozen projections.
    On subsequent access: updates actual points only.
    """
    if season is None:
        season = default_season()

    # Find current matchup from Yahoo
    matchup_info = await _find_current_matchup()
    if not matchup_info or not matchup_info.get("week"):
        logger.info("No current matchup found")
        return None

    week = matchup_info["week"]

    # Check for existing snapshot
    result = await session.execute(
        select(WeeklyMatchupSnapshot).where(
            WeeklyMatchupSnapshot.season == season,
            WeeklyMatchupSnapshot.week == week,
        )
    )
    snapshot = result.scalar_one_or_none()

    if snapshot:
        # Update actuals only
        await _update_snapshot_actuals(session, snapshot, matchup_info)
        return snapshot

    # Create new snapshot with frozen projections
    logger.info(f"Creating matchup snapshot for season {season}, week {week}")

    # Compute projected breakdowns from DB stats (frozen at creation)
    ws = matchup_info.get("week_start", "")
    we = matchup_info.get("week_end", "")
    my_proj_breakdown = await _compute_team_projected_breakdown(
        session, matchup_info["my_team_id"], season, ws, we
    )
    opp_proj_breakdown = await _compute_team_projected_breakdown(
        session, matchup_info["opponent_team_id"], season, ws, we
    )

    # Fetch current actuals from Yahoo
    my_actual_breakdown = await _fetch_team_player_breakdown(
        matchup_info["my_team_id"], week
    )
    opp_actual_breakdown = await _fetch_team_player_breakdown(
        matchup_info["opponent_team_id"], week
    )

    snapshot = WeeklyMatchupSnapshot(
        season=season,
        week=week,
        my_team_id=matchup_info["my_team_id"],
        my_team_name=matchup_info["my_team_name"],
        opponent_team_id=matchup_info["opponent_team_id"],
        opponent_team_name=matchup_info["opponent_team_name"],
        my_projected_points=matchup_info.get("my_projected", 0),
        opponent_projected_points=matchup_info.get("opp_projected", 0),
        my_actual_points=matchup_info.get("my_actual", 0),
        opponent_actual_points=matchup_info.get("opp_actual", 0),
        my_projected_breakdown=json.dumps(my_proj_breakdown),
        opponent_projected_breakdown=json.dumps(opp_proj_breakdown),
        my_actual_breakdown=json.dumps(my_actual_breakdown),
        opponent_actual_breakdown=json.dumps(opp_actual_breakdown),
        my_player_stats=json.dumps(
            my_actual_breakdown.get("players", [])
        ),
        opponent_player_stats=json.dumps(
            opp_actual_breakdown.get("players", [])
        ),
    )
    session.add(snapshot)
    await session.flush()

    # Immediately update with actual data
    await _update_snapshot_actuals(session, snapshot, matchup_info)

    return snapshot


async def _update_snapshot_actuals(
    session: AsyncSession,
    snapshot: WeeklyMatchupSnapshot,
    matchup_info: dict,
) -> None:
    """Refresh the actual points in an existing snapshot."""
    # Update team-level actuals from matchup info
    snapshot.my_actual_points = matchup_info.get("my_actual", 0)
    snapshot.opponent_actual_points = matchup_info.get("opp_actual", 0)

    # Fetch actual per-player breakdowns
    try:
        my_breakdown = await _fetch_team_player_breakdown(
            snapshot.my_team_id, snapshot.week
        )
        opp_breakdown = await _fetch_team_player_breakdown(
            snapshot.opponent_team_id, snapshot.week
        )

        snapshot.my_actual_breakdown = json.dumps(my_breakdown)
        snapshot.opponent_actual_breakdown = json.dumps(opp_breakdown)
        snapshot.my_player_stats = json.dumps(my_breakdown.get("players", []))
        snapshot.opponent_player_stats = json.dumps(opp_breakdown.get("players", []))

        # Update actual totals from breakdown if more accurate
        if my_breakdown.get("total"):
            snapshot.my_actual_points = my_breakdown["total"]
        if opp_breakdown.get("total"):
            snapshot.opponent_actual_points = opp_breakdown["total"]
    except Exception as e:
        logger.warning(f"Failed to update per-player actuals: {e}")

    await session.flush()


async def update_current_matchup_actuals(session: AsyncSession, season: int) -> None:
    """Called during Yahoo sync to refresh matchup actual points."""
    matchup_info = await _find_current_matchup()
    if not matchup_info or not matchup_info.get("week"):
        return

    result = await session.execute(
        select(WeeklyMatchupSnapshot).where(
            WeeklyMatchupSnapshot.season == season,
            WeeklyMatchupSnapshot.week == matchup_info["week"],
        )
    )
    snapshot = result.scalar_one_or_none()
    if snapshot:
        await _update_snapshot_actuals(session, snapshot, matchup_info)
