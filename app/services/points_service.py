"""Central fantasy points calculator for H2H Points league scoring.

This is the core scoring engine. Every other module queries this service
or the player_points table rather than recalculating points independently.

The scoring rules come from app/league_config.py (Galactic Empire league).
"""

import logging
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.league_config import (
    BATTING_SCORING,
    NUM_TEAMS,
    PITCHING_SCORING,
    REPLACEMENT_LEVEL_SLOTS,
)
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.player_points import PlayerPoints

logger = logging.getLogger(__name__)


# ── Pure Calculation Functions ──


def calculate_batter_points(stats: dict) -> float:
    """Calculate fantasy points for a batter given a stat line.

    stats dict can contain:
      R, H, 1B, 2B, 3B, HR, RBI, SB, CS, BB, HBP, K (or SO)

    If only H, 2B, 3B, HR are provided (no 1B), singles are derived:
      1B = H - 2B - 3B - HR
    """
    # Derive singles if not provided directly
    singles = stats.get("1B")
    if singles is None:
        h = stats.get("H", 0) or 0
        doubles = stats.get("2B", 0) or 0
        triples = stats.get("3B", 0) or 0
        hr = stats.get("HR", 0) or 0
        singles = max(h - doubles - triples - hr, 0)

    # K can come as "K" or "SO"
    k = stats.get("K") if stats.get("K") is not None else stats.get("SO", 0)

    points = 0.0
    points += (stats.get("R", 0) or 0) * BATTING_SCORING["R"]
    points += singles * BATTING_SCORING["1B"]
    points += (stats.get("2B", 0) or 0) * BATTING_SCORING["2B"]
    points += (stats.get("3B", 0) or 0) * BATTING_SCORING["3B"]
    points += (stats.get("HR", 0) or 0) * BATTING_SCORING["HR"]
    points += (stats.get("RBI", 0) or 0) * BATTING_SCORING["RBI"]
    points += (stats.get("SB", 0) or 0) * BATTING_SCORING["SB"]
    points += (stats.get("CS", 0) or 0) * BATTING_SCORING["CS"]
    points += (stats.get("BB", 0) or 0) * BATTING_SCORING["BB"]
    points += (stats.get("HBP", 0) or 0) * BATTING_SCORING["HBP"]
    points += (k or 0) * BATTING_SCORING["K"]

    return points


def _ip_to_outs(ip: float) -> int:
    """Convert innings pitched to outs, handling .1 and .2 fractions.

    IP is stored as e.g. 6.2 meaning 6 and 2/3 innings (20 outs).
    The decimal part represents thirds: .0=0, .1=1, .2=2 extra outs.
    """
    if ip is None or ip == 0:
        return 0
    whole = int(ip)
    frac = round((ip - whole) * 10)  # .1 -> 1, .2 -> 2
    return whole * 3 + frac


def calculate_pitcher_points(stats: dict, is_reliever: bool = False) -> float:
    """Calculate fantasy points for a pitcher given a stat line.

    stats dict can contain:
      IP (or OUT), K (or SO), SV, HLD, W, QS, CG, SHO, NH, PG,
      H, ER, BB, HBP

    IP is converted to OUT: each full inning = 3 outs.
    .1 IP = 1 extra out, .2 IP = 2 extra outs.

    Relief wins (RW): For relievers, all W count as RW.
    For starters, W are not scored (starters don't get RW points).
    """
    # Convert IP to outs if OUT not provided directly
    outs = stats.get("OUT")
    if outs is None:
        ip = stats.get("IP", 0) or 0
        outs = _ip_to_outs(ip)

    # K can come as "K" or "SO"
    k = stats.get("K") if stats.get("K") is not None else stats.get("SO", 0)

    # Relief wins: only for relievers
    rw = 0
    if is_reliever:
        rw = stats.get("RW", 0) or 0
        if rw == 0:
            # Derive from W if RW not explicitly provided
            rw = stats.get("W", 0) or 0

    points = 0.0
    points += (outs or 0) * PITCHING_SCORING["OUT"]
    points += (k or 0) * PITCHING_SCORING["K"]
    points += (stats.get("SV", 0) or 0) * PITCHING_SCORING["SV"]
    points += (stats.get("HLD", 0) or 0) * PITCHING_SCORING["HLD"]
    points += rw * PITCHING_SCORING["RW"]
    points += (stats.get("QS", 0) or 0) * PITCHING_SCORING["QS"]
    points += (stats.get("CG", 0) or 0) * PITCHING_SCORING["CG"]
    points += (stats.get("SHO", 0) or 0) * PITCHING_SCORING["SHO"]
    points += (stats.get("NH", 0) or 0) * PITCHING_SCORING["NH"]
    points += (stats.get("PG", 0) or 0) * PITCHING_SCORING["PG"]
    points += (stats.get("H", 0) or 0) * PITCHING_SCORING["H"]
    points += (stats.get("ER", 0) or 0) * PITCHING_SCORING["ER"]
    points += (stats.get("BB", 0) or 0) * PITCHING_SCORING["BB"]
    points += (stats.get("HBP", 0) or 0) * PITCHING_SCORING["HBP"]

    return points


def calculate_points_per_pa(stats: dict) -> float:
    """Points per plate appearance — the key rate stat for batters."""
    pa = stats.get("PA", 0) or 0
    if pa == 0:
        return 0.0
    return calculate_batter_points(stats) / pa


def calculate_points_per_ip(stats: dict, is_reliever: bool = False) -> float:
    """Points per inning pitched — the key rate stat for pitchers."""
    ip = stats.get("IP", 0) or 0
    if ip == 0:
        return 0.0
    return calculate_pitcher_points(stats, is_reliever=is_reliever) / ip


def calculate_points_per_start(stats: dict) -> float:
    """Average points per start for starting pitchers."""
    gs = stats.get("GS", 0) or 0
    if gs == 0:
        return 0.0
    return calculate_pitcher_points(stats, is_reliever=False) / gs


def calculate_points_per_appearance(stats: dict, is_reliever: bool = True) -> float:
    """Average points per appearance for relievers."""
    g = stats.get("G", 0) or 0
    if g == 0:
        return 0.0
    return calculate_pitcher_points(stats, is_reliever=is_reliever) / g


def get_points_breakdown(stats: dict, is_pitcher: bool, is_reliever: bool = False) -> dict:
    """Return a detailed breakdown of points by category.

    Useful for the points calculator widget and trade analysis.
    """
    if is_pitcher:
        outs = stats.get("OUT")
        if outs is None:
            ip = stats.get("IP", 0) or 0
            outs = _ip_to_outs(ip)

        k = stats.get("K") if stats.get("K") is not None else stats.get("SO", 0)
        rw = 0
        if is_reliever:
            rw = stats.get("RW", 0) or stats.get("W", 0) or 0

        breakdown = {
            "outs": (outs or 0) * PITCHING_SCORING["OUT"],
            "k": (k or 0) * PITCHING_SCORING["K"],
            "sv": (stats.get("SV", 0) or 0) * PITCHING_SCORING["SV"],
            "hld": (stats.get("HLD", 0) or 0) * PITCHING_SCORING["HLD"],
            "rw": rw * PITCHING_SCORING["RW"],
            "qs": (stats.get("QS", 0) or 0) * PITCHING_SCORING["QS"],
            "h": (stats.get("H", 0) or 0) * PITCHING_SCORING["H"],
            "er": (stats.get("ER", 0) or 0) * PITCHING_SCORING["ER"],
            "bb": (stats.get("BB", 0) or 0) * PITCHING_SCORING["BB"],
            "hbp": (stats.get("HBP", 0) or 0) * PITCHING_SCORING["HBP"],
        }
        breakdown["total"] = sum(breakdown.values())
        return breakdown
    else:
        singles = stats.get("1B")
        if singles is None:
            h = stats.get("H", 0) or 0
            doubles = stats.get("2B", 0) or 0
            triples = stats.get("3B", 0) or 0
            hr = stats.get("HR", 0) or 0
            singles = max(h - doubles - triples - hr, 0)

        k = stats.get("K") if stats.get("K") is not None else stats.get("SO", 0)

        breakdown = {
            "r": (stats.get("R", 0) or 0) * BATTING_SCORING["R"],
            "1b": singles * BATTING_SCORING["1B"],
            "2b": (stats.get("2B", 0) or 0) * BATTING_SCORING["2B"],
            "3b": (stats.get("3B", 0) or 0) * BATTING_SCORING["3B"],
            "hr": (stats.get("HR", 0) or 0) * BATTING_SCORING["HR"],
            "rbi": (stats.get("RBI", 0) or 0) * BATTING_SCORING["RBI"],
            "sb": (stats.get("SB", 0) or 0) * BATTING_SCORING["SB"],
            "cs": (stats.get("CS", 0) or 0) * BATTING_SCORING["CS"],
            "bb": (stats.get("BB", 0) or 0) * BATTING_SCORING["BB"],
            "hbp": (stats.get("HBP", 0) or 0) * BATTING_SCORING["HBP"],
            "k": (k or 0) * BATTING_SCORING["K"],
        }
        breakdown["total"] = sum(breakdown.values())
        return breakdown


# ── Projection-to-Points Conversion ──
#
# Uses the same scaling approach as the weekly dashboard
# (weekly_matchup_service.py): take actual counting stats, scale
# proportionally to remaining games, apply league scoring weights.

# Stat attribute → scoring category mapping (matches weekly dashboard)
_BATTER_STAT_MAP = [
    ("r", "R"), ("h", "H"), ("doubles", "2B"), ("triples", "3B"),
    ("hr", "HR"), ("rbi", "RBI"), ("sb", "SB"), ("cs", "CS"),
    ("bb", "BB"), ("hbp", "HBP"), ("so", "K"),
]

_PITCHER_STAT_MAP = [
    ("ip", "IP"), ("so", "K"), ("sv", "SV"), ("hld", "HLD"),
    ("w", "W"), ("qs", "QS"), ("h", "H"), ("er", "ER"),
    ("bb", "BB"), ("hbp", "HBP"),
]


def _estimate_remaining_games_batter(pa: float | None) -> int:
    """Estimate remaining MLB games for ROS projection.

    During season: 162 - estimated games played.
    Offseason (full season played): 162 (project full next season from rates).
    """
    if not pa or pa == 0:
        return 162
    games_played = pa / 4.5
    remaining = 162 - games_played
    if remaining < 30:
        # Season essentially complete — project full next season from rates
        return 162
    return round(remaining)


def _estimate_remaining_scale_pitcher(ps) -> float:
    """Estimate scale factor for remaining season pitcher projection.

    Returns a multiplier to apply to full-season counting stats.
    Offseason: 1.0 (project full season from rates).
    """
    gs = ps.gs or 0
    g = ps.g or 0
    is_starter = gs > 0 and gs >= g * 0.5

    if is_starter:
        total_expected = 32  # typical starter makes ~32 starts
        remaining = max(total_expected - gs, 0)
        if remaining < 3:
            return 1.0  # offseason — project full season
        return remaining / max(gs, 1)
    else:
        total_expected = 65  # typical reliever ~65 appearances
        remaining = max(total_expected - g, 0)
        if remaining < 5:
            return 1.0  # offseason — project full season
        return remaining / max(g, 1)


def project_batter_ros_points(bs) -> float:
    """Project ROS fantasy points for a batter from actual BattingStats.

    Uses the same method as the weekly dashboard: scale actual counting
    stats proportionally, derive singles, apply league scoring weights.
    """
    remaining_games = _estimate_remaining_games_batter(bs.pa)
    scale = remaining_games / 162

    stats = {}
    for attr, cat in _BATTER_STAT_MAP:
        stats[cat] = (getattr(bs, attr, 0) or 0) * scale

    # Derive singles (same as weekly dashboard line 721)
    h = stats.get("H", 0)
    d = stats.get("2B", 0)
    t = stats.get("3B", 0)
    hr = stats.get("HR", 0)
    stats["1B"] = max(h - d - t - hr, 0)

    return calculate_batter_points(stats)


def project_pitcher_ros_points(ps, is_reliever: bool = False) -> float:
    """Project ROS fantasy points for a pitcher from actual PitchingStats.

    Uses the same method as the weekly dashboard: scale actual counting
    stats proportionally, apply league scoring weights.
    """
    scale = _estimate_remaining_scale_pitcher(ps)

    stats = {}
    for attr, cat in _PITCHER_STAT_MAP:
        stats[cat] = (getattr(ps, attr, 0) or 0) * scale

    return calculate_pitcher_points(stats, is_reliever=is_reliever)


# Keep old functions as aliases for any other callers
def calculate_projected_batter_points(proj) -> float:
    """Legacy wrapper — prefer project_batter_ros_points(BattingStats)."""
    # If called with a BattingStats object directly, use new method
    if hasattr(proj, "pa") and hasattr(proj, "doubles"):
        return project_batter_ros_points(proj)
    # Fallback for HitterProjection — use counting stats directly
    stats = {
        "R": proj.projected_r or 0,
        "HR": proj.projected_hr or 0,
        "RBI": proj.projected_rbi or 0,
        "SB": proj.projected_sb or 0,
        "CS": (proj.projected_sb or 0) * 0.25,
    }
    return calculate_batter_points(stats)


def calculate_projected_pitcher_points(proj, is_reliever: bool = False) -> float:
    """Legacy wrapper — prefer project_pitcher_ros_points(PitchingStats)."""
    if hasattr(proj, "gs") and hasattr(proj, "ip"):
        return project_pitcher_ros_points(proj, is_reliever=is_reliever)
    stats = {
        "K": proj.projected_k or 0,
        "SV": proj.projected_sv or 0,
        "W": proj.projected_w or 0,
    }
    return calculate_pitcher_points(stats, is_reliever=is_reliever)


# ── Database-Backed Stat Line Extraction ──


def _batting_stats_to_dict(bs: BattingStats) -> dict:
    """Convert a BattingStats ORM object to a dict for the points calculator."""
    return {
        "PA": bs.pa,
        "AB": bs.ab,
        "H": bs.h,
        "2B": bs.doubles,
        "3B": bs.triples,
        "HR": bs.hr,
        "R": bs.r,
        "RBI": bs.rbi,
        "SB": bs.sb,
        "CS": bs.cs,
        "BB": bs.bb,
        "SO": bs.so,
        "HBP": bs.hbp,
    }


def _pitching_stats_to_dict(ps: PitchingStats) -> dict:
    """Convert a PitchingStats ORM object to a dict for the points calculator."""
    return {
        "IP": ps.ip,
        "G": ps.g,
        "GS": ps.gs,
        "W": ps.w,
        "L": ps.l,
        "SV": ps.sv,
        "HLD": ps.hld,
        "H": ps.h,
        "ER": ps.er,
        "HR": ps.hr,
        "BB": ps.bb,
        "SO": ps.so,
        "QS": ps.qs,
        "HBP": ps.hbp,
    }


def _is_reliever(ps: PitchingStats) -> bool:
    """Determine if a pitcher is a reliever based on GS/G ratio."""
    gs = ps.gs or 0
    g = ps.g or 1
    return gs < g * 0.3


# ── Batch Points Calculation ──


@dataclass
class PlayerPointsSummary:
    """Summary of a player's fantasy points for ranking/display."""

    player_id: int
    player_name: str
    team: str | None
    position: str | None
    player_type: str  # "hitter" or "pitcher"
    actual_points: float
    projected_ros_points: float
    points_per_pa: float | None  # hitters
    points_per_ip: float | None  # pitchers
    points_per_start: float | None  # starters
    points_per_appearance: float | None  # relievers
    is_reliever: bool = False
    steamer_ros_points: float | None = None


async def calculate_player_actual_points(
    session: AsyncSession,
    player: Player,
    season: int,
    period: str = "full_season",
) -> PlayerPointsSummary | None:
    """Calculate actual fantasy points for a single player from their stats."""
    # Check batting stats
    bat_result = await session.execute(
        select(BattingStats).where(
            BattingStats.player_id == player.id,
            BattingStats.season == season,
            BattingStats.period == period,
        )
    )
    bat = bat_result.scalar_one_or_none()

    # Check pitching stats
    pitch_result = await session.execute(
        select(PitchingStats).where(
            PitchingStats.player_id == player.id,
            PitchingStats.season == season,
            PitchingStats.period == period,
        )
    )
    pitch = pitch_result.scalar_one_or_none()

    if not bat and not pitch:
        return None

    # Determine player type — pitchers can also bat, but we categorize by primary role
    is_pitcher = pitch is not None and (pitch.ip or 0) > 0
    is_hitter = bat is not None and (bat.pa or 0) > 0

    if is_pitcher:
        stats = _pitching_stats_to_dict(pitch)
        reliever = _is_reliever(pitch)
        actual_pts = calculate_pitcher_points(stats, is_reliever=reliever)
        return PlayerPointsSummary(
            player_id=player.id,
            player_name=player.name,
            team=player.team,
            position=player.position,
            player_type="pitcher",
            actual_points=round(actual_pts, 1),
            projected_ros_points=0.0,  # filled in separately
            points_per_pa=None,
            points_per_ip=round(calculate_points_per_ip(stats, is_reliever=reliever), 2)
            if (pitch.ip or 0) > 0
            else None,
            points_per_start=round(calculate_points_per_start(stats), 1)
            if not reliever and (pitch.gs or 0) > 0
            else None,
            points_per_appearance=round(
                calculate_points_per_appearance(stats, is_reliever=reliever), 1
            )
            if reliever and (pitch.g or 0) > 0
            else None,
            is_reliever=reliever,
        )
    elif is_hitter:
        stats = _batting_stats_to_dict(bat)
        actual_pts = calculate_batter_points(stats)
        return PlayerPointsSummary(
            player_id=player.id,
            player_name=player.name,
            team=player.team,
            position=player.position,
            player_type="hitter",
            actual_points=round(actual_pts, 1),
            projected_ros_points=0.0,
            points_per_pa=round(calculate_points_per_pa(stats), 3)
            if (bat.pa or 0) > 0
            else None,
            points_per_ip=None,
            points_per_start=None,
            points_per_appearance=None,
        )

    return None


async def calculate_all_player_points(
    session: AsyncSession,
    season: int,
    period: str = "full_season",
) -> list[PlayerPointsSummary]:
    """Calculate actual + projected points for all players and store in DB.

    This is the main batch function that populates the player_points table.
    """
    # Get all players with stats
    hitter_result = await session.execute(
        select(Player)
        .join(BattingStats)
        .where(
            BattingStats.season == season,
            BattingStats.period == period,
            BattingStats.pa >= 30,
        )
        .distinct()
    )
    hitters = hitter_result.scalars().all()

    pitcher_result = await session.execute(
        select(Player)
        .join(PitchingStats)
        .where(
            PitchingStats.season == season,
            PitchingStats.period == period,
            PitchingStats.ip >= 10,
        )
        .distinct()
    )
    pitchers = pitcher_result.scalars().all()

    # Build projection maps ONCE before the loops
    consensus_map = await _build_projection_points_map(session, "consensus")
    steamer_map = await _build_projection_points_map(session, "steamer_ros")
    consensus_rate_map = await _build_consensus_rate_map(session)

    # Calculate actual points for all players
    summaries: list[PlayerPointsSummary] = []

    for player in hitters:
        summary = await calculate_player_actual_points(session, player, season, period)
        if summary and summary.player_type == "hitter":
            # Use consensus projection (with pace-based fallback)
            consensus_pts = consensus_map.get(player.id)
            if consensus_pts is not None:
                summary.projected_ros_points = consensus_pts
            else:
                # Fallback to pace-based for players without consensus projection
                bs_result = await session.execute(
                    select(BattingStats).where(
                        BattingStats.player_id == player.id,
                        BattingStats.season == season,
                        BattingStats.period == "full_season",
                    )
                )
                bs = bs_result.scalar_one_or_none()
                if bs:
                    summary.projected_ros_points = round(
                        project_batter_ros_points(bs), 1
                    )

            # Use consensus rate stats if available, else keep actual-based
            con_rates = consensus_rate_map.get(player.id)
            if con_rates and "points_per_pa" in con_rates:
                summary.points_per_pa = round(con_rates["points_per_pa"], 3)

            summaries.append(summary)

    for player in pitchers:
        summary = await calculate_player_actual_points(session, player, season, period)
        if summary and summary.player_type == "pitcher":
            # Use consensus projection (with pace-based fallback)
            consensus_pts = consensus_map.get(player.id)
            if consensus_pts is not None:
                summary.projected_ros_points = consensus_pts
            else:
                # Fallback to pace-based for players without consensus projection
                ps_result = await session.execute(
                    select(PitchingStats).where(
                        PitchingStats.player_id == player.id,
                        PitchingStats.season == season,
                        PitchingStats.period == "full_season",
                    )
                )
                ps = ps_result.scalar_one_or_none()
                if ps:
                    summary.projected_ros_points = round(
                        project_pitcher_ros_points(ps, is_reliever=summary.is_reliever), 1
                    )

            # Use consensus rate stats if available, else keep actual-based
            con_rates = consensus_rate_map.get(player.id)
            if con_rates:
                if "points_per_ip" in con_rates:
                    summary.points_per_ip = round(con_rates["points_per_ip"], 2)
                if "points_per_start" in con_rates and not summary.is_reliever:
                    summary.points_per_start = con_rates["points_per_start"]
                if "points_per_appearance" in con_rates and summary.is_reliever:
                    summary.points_per_appearance = con_rates["points_per_appearance"]

            summaries.append(summary)

    # Early season: if no players had actual stats, populate from consensus alone
    if not summaries and consensus_map:
        logger.info(
            "No actual stats found — populating PlayerPoints from consensus projections"
        )
        # Get all players who have consensus projections
        from app.models.roster import Roster

        rostered_result = await session.execute(select(Player).join(Roster).distinct())
        rostered_players = rostered_result.scalars().all()
        # Also include any player with consensus data
        all_consensus_pids = set(consensus_map.keys())
        rostered_pids = {p.id for p in rostered_players}
        target_pids = rostered_pids | all_consensus_pids

        # Get player objects for all targets
        if target_pids:
            player_result = await session.execute(
                select(Player).where(Player.id.in_(target_pids))
            )
            all_players = player_result.scalars().all()
        else:
            all_players = []

        for player in all_players:
            con_pts = consensus_map.get(player.id)
            if con_pts is None:
                continue
            con_rates = consensus_rate_map.get(player.id, {})
            is_pitcher = con_rates.get("is_pitcher", False)
            is_reliever = con_rates.get("is_reliever", False)
            summary = PlayerPointsSummary(
                player_id=player.id,
                player_name=player.name,
                team=player.team,
                position=player.position,
                player_type="pitcher" if is_pitcher else "hitter",
                actual_points=0.0,
                projected_ros_points=con_pts,
                points_per_pa=con_rates.get("points_per_pa") if not is_pitcher else None,
                points_per_ip=con_rates.get("points_per_ip") if is_pitcher else None,
                points_per_start=con_rates.get("points_per_start") if is_pitcher and not is_reliever else None,
                points_per_appearance=con_rates.get("points_per_appearance") if is_reliever else None,
                is_reliever=is_reliever,
            )
            summaries.append(summary)

    # Attach Steamer ROS points if available
    for s in summaries:
        s.steamer_ros_points = steamer_map.get(s.player_id)

    # Calculate positional ranks and surplus value
    summaries = _calculate_rankings_and_surplus(summaries)

    # Store in database
    await _store_player_points(session, summaries, season, period)

    logger.info(
        f"Calculated points for {len(summaries)} players "
        f"({sum(1 for s in summaries if s.player_type == 'hitter')} hitters, "
        f"{sum(1 for s in summaries if s.player_type == 'pitcher')} pitchers) "
        f"for {season} {period}"
    )

    return summaries


async def _build_projection_points_map(
    session: AsyncSession, system: str = "consensus"
) -> dict[int, float]:
    """Build a mapping of player_id -> ROS fantasy points from a projection system.

    Reads projections from the projections table for the given system
    and converts counting stats to league-specific fantasy points.
    """
    from app.models.projection import Projection

    result = await session.execute(
        select(Projection).where(Projection.system == system)
    )
    rows = result.scalars().all()

    if not rows:
        return {}

    # Group projections by player_id
    player_stats: dict[int, dict[str, float]] = {}
    player_types: dict[int, str] = {}
    for proj in rows:
        if proj.player_id not in player_stats:
            player_stats[proj.player_id] = {}
        player_stats[proj.player_id][proj.stat_name] = proj.projected_value
        # Track player type from the stats present
        if proj.stat_name == "PA":
            player_types[proj.player_id] = "hitter"
        elif proj.stat_name == "IP":
            player_types[proj.player_id] = "pitcher"

    # Calculate fantasy points for each player
    points_map: dict[int, float] = {}
    for pid, stats in player_stats.items():
        ptype = player_types.get(pid)
        if ptype == "hitter":
            pts = calculate_batter_points(stats)
        elif ptype == "pitcher":
            is_reliever = (stats.get("GS", 0) or 0) < (stats.get("G", 0) or 0) * 0.3
            pts = calculate_pitcher_points(stats, is_reliever=is_reliever)
        else:
            continue
        points_map[pid] = round(pts, 1)

    logger.info(f"Built {system} points map for {len(points_map)} players")
    return points_map


async def _build_steamer_points_map(session: AsyncSession) -> dict[int, float]:
    """Build a mapping of player_id -> Steamer ROS fantasy points (backward compat)."""
    return await _build_projection_points_map(session, "steamer_ros")


async def _build_consensus_rate_map(
    session: AsyncSession,
) -> dict[int, dict[str, float]]:
    """Build mapping of player_id -> rate stats from consensus projections.

    Returns dict like {player_id: {"points_per_pa": 0.5, "points_per_ip": 2.1, ...}}.
    Uses consensus counting stats (PA, IP, GS, G) to derive rate stats.
    """
    from app.models.projection import Projection

    result = await session.execute(
        select(Projection).where(Projection.system == "consensus")
    )
    rows = result.scalars().all()

    if not rows:
        return {}

    # Group projections by player_id
    player_stats: dict[int, dict[str, float]] = {}
    player_types: dict[int, str] = {}
    for proj in rows:
        if proj.player_id not in player_stats:
            player_stats[proj.player_id] = {}
        player_stats[proj.player_id][proj.stat_name] = proj.projected_value
        if proj.stat_name == "PA":
            player_types[proj.player_id] = "hitter"
        elif proj.stat_name == "IP":
            player_types[proj.player_id] = "pitcher"

    rate_map: dict[int, dict[str, float]] = {}
    for pid, stats in player_stats.items():
        ptype = player_types.get(pid)
        rates: dict[str, float] = {}

        if ptype == "hitter":
            pa = stats.get("PA", 0) or 0
            if pa > 0:
                pts = calculate_batter_points(stats)
                rates["points_per_pa"] = round(pts / pa, 4)
            rates["is_pitcher"] = False
            rates["is_reliever"] = False

        elif ptype == "pitcher":
            ip = stats.get("IP", 0) or 0
            gs = stats.get("GS", 0) or 0
            g = stats.get("G", 0) or 0
            is_reliever = gs < (g * 0.3) if g > 0 else False
            pts = calculate_pitcher_points(stats, is_reliever=is_reliever)

            if ip > 0:
                rates["points_per_ip"] = round(pts / ip, 4)
            if gs > 0 and not is_reliever:
                rates["points_per_start"] = round(pts / gs, 1)
            if g > 0 and is_reliever:
                rates["points_per_appearance"] = round(pts / g, 1)
            rates["is_pitcher"] = True
            rates["is_reliever"] = is_reliever

        if rates:
            rate_map[pid] = rates

    logger.info(f"Built consensus rate map for {len(rate_map)} players")
    return rate_map


def _calculate_rankings_and_surplus(
    summaries: list[PlayerPointsSummary],
) -> list[PlayerPointsSummary]:
    """Calculate positional ranks and surplus value (points above replacement)."""
    # Group by position for ranking
    position_groups: dict[str, list[PlayerPointsSummary]] = {}

    for s in summaries:
        if s.player_type == "hitter":
            # A player can be eligible at multiple positions
            positions = (s.position or "Util").split(",")
            for pos in positions:
                pos = pos.strip()
                if pos not in position_groups:
                    position_groups[pos] = []
                position_groups[pos].append(s)
        else:
            # Pitchers: SP or RP
            if s.is_reliever:
                position_groups.setdefault("RP", []).append(s)
            else:
                position_groups.setdefault("SP", []).append(s)

    # Sort each group by projected ROS points and assign ranks
    replacement_levels: dict[str, float] = {}
    for pos, players in position_groups.items():
        players.sort(key=lambda x: x.projected_ros_points, reverse=True)

        # Determine replacement level
        slots = REPLACEMENT_LEVEL_SLOTS.get(pos, NUM_TEAMS)
        repl_idx = min(slots, len(players) - 1) if len(players) > 0 else 0
        if repl_idx < len(players):
            replacement_levels[pos] = players[repl_idx].projected_ros_points
        else:
            replacement_levels[pos] = 0.0

    # Assign best positional rank and surplus value to each player
    # Track which summaries we've already ranked to avoid duplicates
    ranked_ids: set[int] = set()
    for s in summaries:
        if s.player_id in ranked_ids:
            continue
        ranked_ids.add(s.player_id)

        best_rank = 999
        best_surplus = -9999.0

        if s.player_type == "hitter":
            positions = (s.position or "Util").split(",")
            for pos in positions:
                pos = pos.strip()
                if pos in position_groups:
                    group = position_groups[pos]
                    for rank, p in enumerate(group, 1):
                        if p.player_id == s.player_id:
                            if rank < best_rank:
                                best_rank = rank
                            repl = replacement_levels.get(pos, 0)
                            surplus = s.projected_ros_points - repl
                            if surplus > best_surplus:
                                best_surplus = surplus
                            break
        else:
            pos = "RP" if s.is_reliever else "SP"
            if pos in position_groups:
                group = position_groups[pos]
                for rank, p in enumerate(group, 1):
                    if p.player_id == s.player_id:
                        best_rank = rank
                        repl = replacement_levels.get(pos, 0)
                        best_surplus = s.projected_ros_points - repl
                        break

        # Use a default of 0 for positional rank if not found
        s_positional_rank = best_rank if best_rank < 999 else None
        s_surplus = best_surplus if best_surplus > -9999 else 0.0

        # Store as attributes we'll read when persisting
        s._positional_rank = s_positional_rank  # type: ignore[attr-defined]
        s._surplus_value = round(s_surplus, 1)  # type: ignore[attr-defined]

    return summaries


async def _store_player_points(
    session: AsyncSession,
    summaries: list[PlayerPointsSummary],
    season: int,
    period: str,
) -> None:
    """Persist calculated points to the player_points table."""
    # Clear existing entries for this season/period
    await session.execute(
        delete(PlayerPoints).where(
            PlayerPoints.season == season,
            PlayerPoints.period == period,
        )
    )

    for s in summaries:
        pos_rank = getattr(s, "_positional_rank", None)
        surplus = getattr(s, "_surplus_value", None)

        session.add(
            PlayerPoints(
                player_id=s.player_id,
                season=season,
                period=period,
                player_type=s.player_type,
                actual_points=s.actual_points,
                projected_ros_points=s.projected_ros_points,
                steamer_ros_points=s.steamer_ros_points,
                points_per_pa=s.points_per_pa,
                points_per_ip=s.points_per_ip,
                points_per_start=s.points_per_start,
                points_per_appearance=s.points_per_appearance,
                positional_rank=pos_rank,
                surplus_value=surplus,
            )
        )

    await session.flush()


# ── Utility Functions ──


async def get_player_points_from_db(
    session: AsyncSession,
    player_id: int,
    season: int,
    period: str = "full_season",
) -> PlayerPoints | None:
    """Retrieve stored player points from the database."""
    result = await session.execute(
        select(PlayerPoints).where(
            PlayerPoints.player_id == player_id,
            PlayerPoints.season == season,
            PlayerPoints.period == period,
        )
    )
    return result.scalar_one_or_none()


async def get_points_leaders(
    session: AsyncSession,
    season: int,
    player_type: str = "hitter",
    period: str = "full_season",
    limit: int = 20,
) -> list[PlayerPoints]:
    """Get top players by actual fantasy points."""
    result = await session.execute(
        select(PlayerPoints)
        .where(
            PlayerPoints.season == season,
            PlayerPoints.period == period,
            PlayerPoints.player_type == player_type,
        )
        .order_by(PlayerPoints.actual_points.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
