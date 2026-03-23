"""Matchup quality adjustment engine — reusable across projections, waivers, trades.

Provides four layers of projection adjustment:
- Phase 1: Opposing pitcher quality (SIERA + K%/BB%)
- Phase 2: Opposing team offense (wRC+)
- Phase 3: Park factors (neutralize + venue-specific)
- Phase 4: Platoon splits (regressed per Tango's The Book)

All functions are pure computations (no DB access) unless noted.
DB-fetching helpers are async and clearly labeled.

Sources: FanGraphs library, Tom Tango's The Book.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import statsapi as statsapi_module
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.services.matchup_service import PARK_FACTORS, TEAM_PARKS

logger = logging.getLogger(__name__)

# ── League averages ──
LEAGUE_AVG_SIERA = 4.15
LEAGUE_AVG_K_PCT = 22.0  # pitcher K%
LEAGUE_AVG_BB_PCT = 8.0  # pitcher BB%
LEAGUE_AVG_WRC_PLUS = 100

# League-average split performance (approximate, for regression prior)
# RHH vs LHP, LHH vs RHP, etc.
LEAGUE_AVG_SPLIT_WOBA = 0.315
LEAGUE_AVG_SPLIT_AVG = 0.250
LEAGUE_AVG_SPLIT_ISO = 0.155
LEAGUE_AVG_SPLIT_K_PCT = 0.22
LEAGUE_AVG_SPLIT_BB_PCT = 0.08

# Platoon regression PA (from The Book — Tango, Lichtman, Dolphin)
PLATOON_REGRESSION_PA_RHH = 2200
PLATOON_REGRESSION_PA_LHH = 1000
MIN_SPLIT_PA = 50  # below this, don't use split data at all

# Dampening factors
PHASE1_DAMPENING = 0.50  # opposing pitcher quality
PHASE2_DAMPENING = 0.35  # opposing team offense


@dataclass
class GameDetail:
    """A single game's matchup details."""

    game_date: str
    home_team: str  # full name from statsapi
    away_team: str
    venue_name: str
    home_pitcher_id: int | None = None
    away_pitcher_id: int | None = None


# ── Team name mappings ──
_TEAM_ABBREV_TO_FULL: dict[str, str] = {}
_TEAM_FULL_TO_ABBREV: dict[str, str] = {}


def _build_team_name_maps() -> None:
    """Build abbreviation ↔ full name mappings."""
    if _TEAM_ABBREV_TO_FULL:
        return
    abbrev_map = {
        "AZ": "Arizona Diamondbacks",
        "ARI": "Arizona Diamondbacks",
        "ATL": "Atlanta Braves",
        "BAL": "Baltimore Orioles",
        "BOS": "Boston Red Sox",
        "CHC": "Chicago Cubs",
        "CHW": "Chicago White Sox",
        "CWS": "Chicago White Sox",
        "CIN": "Cincinnati Reds",
        "CLE": "Cleveland Guardians",
        "COL": "Colorado Rockies",
        "DET": "Detroit Tigers",
        "HOU": "Houston Astros",
        "KC": "Kansas City Royals",
        "LAA": "Los Angeles Angels",
        "LAD": "Los Angeles Dodgers",
        "MIA": "Miami Marlins",
        "MIL": "Milwaukee Brewers",
        "MIN": "Minnesota Twins",
        "NYM": "New York Mets",
        "NYY": "New York Yankees",
        "ATH": "Oakland Athletics",
        "OAK": "Oakland Athletics",
        "PHI": "Philadelphia Phillies",
        "PIT": "Pittsburgh Pirates",
        "SD": "San Diego Padres",
        "SF": "San Francisco Giants",
        "SEA": "Seattle Mariners",
        "STL": "St. Louis Cardinals",
        "TB": "Tampa Bay Rays",
        "TEX": "Texas Rangers",
        "TOR": "Toronto Blue Jays",
        "WAS": "Washington Nationals",
        "WSH": "Washington Nationals",
    }
    _TEAM_ABBREV_TO_FULL.update(abbrev_map)
    for abbr, full in abbrev_map.items():
        _TEAM_FULL_TO_ABBREV[full] = abbr


def get_team_full_name(abbrev: str) -> str:
    _build_team_name_maps()
    return _TEAM_ABBREV_TO_FULL.get(abbrev, "")


def get_team_abbrev(full_name: str) -> str:
    _build_team_name_maps()
    return _TEAM_FULL_TO_ABBREV.get(full_name, "")


def get_player_home_park(team_abbrev: str) -> str:
    """Get a player's home park name from their team abbreviation."""
    full = get_team_full_name(team_abbrev)
    return TEAM_PARKS.get(full, "")


# ══════════════════════════════════════════════════════
# PURE FUNCTIONS — no DB access, fully testable
# ══════════════════════════════════════════════════════


def dampen(raw_ratio: float, dampening: float) -> float:
    """Dampen a ratio toward 1.0. E.g., raw=1.30, damp=0.50 → 1.15."""
    return 1.0 + (raw_ratio - 1.0) * dampening


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ── Phase 1: Opposing Pitcher Quality ──


def compute_hitter_pitcher_mults(
    pitcher_siera: float,
    pitcher_k_pct: float,
    pitcher_bb_pct: float,
) -> dict[str, float]:
    """Per-category multipliers for a hitter facing a specific pitcher.

    SIERA (park-adjusted) for run-environment stats.
    Pitcher's actual K%/BB% for skill stats.
    All dampened by PHASE1_DAMPENING, clamped [0.80, 1.20].
    """
    siera_raw = (
        LEAGUE_AVG_SIERA / pitcher_siera if pitcher_siera > 0 else 1.0
    )
    siera_m = clamp(dampen(siera_raw, PHASE1_DAMPENING), 0.80, 1.20)

    k_raw = (
        pitcher_k_pct / LEAGUE_AVG_K_PCT
        if LEAGUE_AVG_K_PCT > 0
        else 1.0
    )
    k_m = clamp(dampen(k_raw, PHASE1_DAMPENING), 0.80, 1.20)

    bb_raw = (
        pitcher_bb_pct / LEAGUE_AVG_BB_PCT
        if LEAGUE_AVG_BB_PCT > 0
        else 1.0
    )
    bb_m = clamp(dampen(bb_raw, PHASE1_DAMPENING), 0.80, 1.20)

    return {
        "R": siera_m, "H": siera_m, "1B": siera_m,
        "2B": siera_m, "3B": siera_m, "HR": siera_m,
        "RBI": siera_m, "HBP": siera_m,
        "K": k_m, "BB": bb_m,
    }


# ── Phase 2: Opposing Team Offense ──


def compute_pitcher_offense_mults(
    opp_wrc_plus: float,
) -> dict[str, float]:
    """Per-category multipliers for a pitcher facing a specific lineup.

    wRC+ (park-adjusted) for H and ER. K/BB not adjusted (pitcher-controlled).
    Dampened by PHASE2_DAMPENING, clamped [0.90, 1.15].
    """
    wrc_raw = opp_wrc_plus / LEAGUE_AVG_WRC_PLUS
    m = clamp(dampen(wrc_raw, PHASE2_DAMPENING), 0.90, 1.15)
    return {"H": m, "ER": m}


# ── Phase 3: Park Factors ──


def compute_park_mult(
    player_home_park: str,
    week_venues: list[str],
) -> float:
    """Park factor multiplier: neutralize home-park bias, apply venue factor.

    Returns a single multiplier to apply to run-environment stats.
    """
    home_pf = PARK_FACTORS.get(player_home_park, 1.0)
    home_blend = 0.5 * home_pf + 0.5 * 1.0
    if not week_venues:
        return 1.0
    avg_park = sum(
        PARK_FACTORS.get(v, 1.0) for v in week_venues
    ) / len(week_venues)
    return avg_park / home_blend


# ── Phase 4: Platoon Splits ──


def regress_split_stat(
    observed: float | None,
    split_pa: float,
    league_avg: float,
    batter_bats_right: bool,
) -> float:
    """Regress an observed split stat toward league average.

    Per Tango's The Book:
    - RHH: regress toward 2200 PA of league-average split performance
    - LHH: regress toward 1000 PA
    """
    if observed is None or split_pa < MIN_SPLIT_PA:
        return league_avg

    reg_pa = (
        PLATOON_REGRESSION_PA_RHH
        if batter_bats_right
        else PLATOON_REGRESSION_PA_LHH
    )
    return (observed * split_pa + league_avg * reg_pa) / (
        split_pa + reg_pa
    )


def compute_platoon_ratios(
    split_data: dict[str, float | None],
    overall_stats: dict[str, float | None],
    batter_bats_right: bool,
) -> dict[str, float] | None:
    """Compute regressed platoon split ratios vs overall rates.

    Returns per-stat multipliers, or None if insufficient data.
    split_data: {"pa", "avg", "iso", "woba", "k_pct", "bb_pct"}
    overall_stats: same keys from full-season BattingStats
    """
    split_pa = split_data.get("pa") or 0
    if split_pa < MIN_SPLIT_PA:
        return None

    ratios = {}

    # wOBA → R, RBI general multiplier
    split_woba = regress_split_stat(
        split_data.get("woba"), split_pa,
        LEAGUE_AVG_SPLIT_WOBA, batter_bats_right,
    )
    overall_woba = overall_stats.get("woba") or LEAGUE_AVG_SPLIT_WOBA
    if overall_woba > 0:
        ratios["R"] = split_woba / overall_woba
        ratios["RBI"] = split_woba / overall_woba

    # ISO → HR, 2B, 3B
    split_iso = regress_split_stat(
        split_data.get("iso"), split_pa,
        LEAGUE_AVG_SPLIT_ISO, batter_bats_right,
    )
    overall_iso = overall_stats.get("iso") or LEAGUE_AVG_SPLIT_ISO
    if overall_iso > 0:
        ratios["HR"] = split_iso / overall_iso
        ratios["2B"] = split_iso / overall_iso
        ratios["3B"] = split_iso / overall_iso

    # AVG → H, 1B
    split_avg = regress_split_stat(
        split_data.get("avg"), split_pa,
        LEAGUE_AVG_SPLIT_AVG, batter_bats_right,
    )
    overall_avg = overall_stats.get("avg") or LEAGUE_AVG_SPLIT_AVG
    if overall_avg > 0:
        ratios["H"] = split_avg / overall_avg
        ratios["1B"] = split_avg / overall_avg

    # K%
    split_k = regress_split_stat(
        split_data.get("k_pct"), split_pa,
        LEAGUE_AVG_SPLIT_K_PCT, batter_bats_right,
    )
    overall_k = overall_stats.get("k_pct") or LEAGUE_AVG_SPLIT_K_PCT
    if overall_k > 0:
        ratios["K"] = split_k / overall_k

    # BB%
    split_bb = regress_split_stat(
        split_data.get("bb_pct"), split_pa,
        LEAGUE_AVG_SPLIT_BB_PCT, batter_bats_right,
    )
    overall_bb = overall_stats.get("bb_pct") or LEAGUE_AVG_SPLIT_BB_PCT
    if overall_bb > 0:
        ratios["BB"] = split_bb / overall_bb

    # Clamp all ratios
    for cat in ratios:
        ratios[cat] = clamp(ratios[cat], 0.70, 1.35)

    return ratios


# ══════════════════════════════════════════════════════
# ASYNC DATA FETCHERS — require DB session
# ══════════════════════════════════════════════════════

# Caches (module-level, persist across calls within a process)
_pitcher_quality_cache: dict[int, dict] = {}
_pitcher_hand_cache: dict[int, str] = {}
_team_wrc_cache: dict[str, float] = {}


async def get_pitcher_quality(
    session: AsyncSession,
    pitcher_mlbam_id: int,
    season: int,
) -> dict:
    """Fetch SIERA, K%, BB% for a pitcher. Returns league averages if not found."""
    if pitcher_mlbam_id in _pitcher_quality_cache:
        return _pitcher_quality_cache[pitcher_mlbam_id]

    defaults = {
        "siera": LEAGUE_AVG_SIERA,
        "k_pct": LEAGUE_AVG_K_PCT,
        "bb_pct": LEAGUE_AVG_BB_PCT,
    }

    result = await session.execute(
        select(Player).where(Player.mlbam_id == str(pitcher_mlbam_id))
    )
    player = result.scalar_one_or_none()
    if not player:
        return defaults

    result = await session.execute(
        select(PitchingStats).where(
            PitchingStats.player_id == player.id,
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.source == "fangraphs",
        )
    )
    ps = result.scalar_one_or_none()
    if not ps:
        return defaults

    quality = {
        "siera": ps.siera if ps.siera else LEAGUE_AVG_SIERA,
        "k_pct": ps.k_pct if ps.k_pct else LEAGUE_AVG_K_PCT,
        "bb_pct": ps.bb_pct if ps.bb_pct else LEAGUE_AVG_BB_PCT,
    }
    _pitcher_quality_cache[pitcher_mlbam_id] = quality
    return quality


async def get_pitcher_handedness(
    mlbam_id: int,
) -> str | None:
    """Get pitcher handedness ('L' or 'R') from MLB Stats API. Cached."""
    if mlbam_id in _pitcher_hand_cache:
        return _pitcher_hand_cache[mlbam_id]

    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: statsapi_module.get(
                "people", {"personIds": mlbam_id}
            ),
        )
        for person in data.get("people", []):
            hand = person.get("pitchHand", {}).get("code")
            if hand:
                _pitcher_hand_cache[mlbam_id] = hand
                return hand
    except Exception as e:
        logger.warning(f"Failed to get handedness for {mlbam_id}: {e}")
    return None


async def get_team_wrc_plus(
    session: AsyncSession,
    team_abbrev: str,
    season: int,
) -> float:
    """Get a team's PA-weighted average wRC+."""
    if team_abbrev in _team_wrc_cache:
        return _team_wrc_cache[team_abbrev]

    result = await session.execute(
        select(BattingStats, Player.team)
        .join(Player, BattingStats.player_id == Player.id)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.source == "fangraphs",
            BattingStats.pa >= 100,
            Player.team == team_abbrev,
        )
    )
    rows = result.all()

    if not rows:
        return LEAGUE_AVG_WRC_PLUS

    total_pa = sum(bs.pa for bs, _ in rows if bs.pa)
    if total_pa == 0:
        return LEAGUE_AVG_WRC_PLUS

    weighted = sum(
        (bs.wrc_plus or 100) * (bs.pa or 0) for bs, _ in rows
    )
    avg_wrc = weighted / total_pa
    _team_wrc_cache[team_abbrev] = avg_wrc
    return avg_wrc


async def get_weekly_game_details(
    week_start: str,
    week_end: str,
) -> list[GameDetail]:
    """Fetch game details for the week (regular season only)."""
    games: list[GameDetail] = []
    try:
        start = datetime.strptime(week_start, "%Y-%m-%d").date()
        end = datetime.strptime(week_end, "%Y-%m-%d").date()
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
                if game.get("game_type") != "R":
                    continue
                games.append(
                    GameDetail(
                        game_date=current.isoformat(),
                        home_team=game.get("home_name", ""),
                        away_team=game.get("away_name", ""),
                        venue_name=game.get("venue_name", ""),
                        home_pitcher_id=game.get("home_pitcher_id"),
                        away_pitcher_id=game.get("away_pitcher_id"),
                    )
                )
            current += timedelta(days=1)
    except Exception as e:
        logger.warning(f"Failed to fetch weekly game details: {e}")
    return games


def get_team_games(
    team_abbrev: str, game_details: list[GameDetail]
) -> list[GameDetail]:
    """Filter game details to games involving a specific team."""
    full = get_team_full_name(team_abbrev)
    if not full:
        return []
    return [
        g for g in game_details
        if g.home_team == full or g.away_team == full
    ]


def get_opposing_pitcher_id(
    team_abbrev: str, game: GameDetail
) -> int | None:
    """Get the opposing pitcher's MLBAM ID for a team in a game."""
    full = get_team_full_name(team_abbrev)
    if game.home_team == full:
        return game.away_pitcher_id
    return game.home_pitcher_id


def get_opponent_team(
    team_abbrev: str, game: GameDetail
) -> str:
    """Get the opponent team's full name for a team in a game."""
    full = get_team_full_name(team_abbrev)
    if game.home_team == full:
        return game.away_team
    return game.home_team
