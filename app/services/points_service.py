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
from app.services.projection_service import (
    HitterProjection,
    PitcherProjection,
    project_hitter,
    project_pitcher,
)

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


def calculate_projected_batter_points(proj: HitterProjection) -> float:
    """Convert a HitterProjection into projected ROS fantasy points.

    The projection service gives us projected_hr, projected_r, projected_rbi,
    projected_sb, projected_avg, projected_obp, projected_slg.

    For points we need counting stats. We estimate:
    - Remaining PA from the projection's confidence and pace
    - H from AVG * AB (AB ≈ PA * 0.88)
    - 2B, 3B estimated from typical ratios to H
    - BB estimated from OBP, H, HBP, PA
    - K estimated from typical K rate or league average
    """
    # This is an approximation since projections store rate+counting stats
    # Use the counting stats directly where available
    stats = {
        "R": proj.projected_r,
        "HR": proj.projected_hr,
        "RBI": proj.projected_rbi,
        "SB": proj.projected_sb,
    }

    # Estimate remaining counting stats from rate stats
    # Assume ~600 PA for a full season, scale by confidence
    estimated_pa = 600 * proj.confidence_score if proj.confidence_score > 0 else 300
    ab = estimated_pa * 0.88  # rough AB/PA ratio
    h = proj.projected_avg * ab if proj.projected_avg else 0

    # Estimate hit distribution from typical MLB ratios
    # Roughly: 2B = 25% of non-HR hits, 3B = 3% of non-HR hits
    non_hr_hits = max(h - proj.projected_hr, 0)
    stats["2B"] = non_hr_hits * 0.25
    stats["3B"] = non_hr_hits * 0.03
    stats["H"] = h

    # Estimate BB from OBP: OBP ≈ (H + BB + HBP) / PA
    # BB ≈ OBP * PA - H - HBP (estimate HBP ≈ PA * 0.01)
    hbp_est = estimated_pa * 0.01
    bb_est = max((proj.projected_obp or 0.320) * estimated_pa - h - hbp_est, 0)
    stats["BB"] = bb_est
    stats["HBP"] = hbp_est

    # Estimate K: K ≈ AB * (1 - AVG) * K_rate_factor
    # Typical K rate is ~22% of PA
    stats["K"] = estimated_pa * 0.22

    # CS: estimate from SB at ~25% caught rate
    stats["CS"] = proj.projected_sb * 0.25 if proj.projected_sb else 0

    return calculate_batter_points(stats)


def calculate_projected_pitcher_points(proj: PitcherProjection, is_reliever: bool = False) -> float:
    """Convert a PitcherProjection into projected ROS fantasy points.

    Uses projected_w, projected_sv, projected_k, projected_era, projected_whip.
    """
    # Estimate IP from pace: starters ~180 IP, relievers ~65 IP
    if is_reliever:
        estimated_ip = 65 * proj.confidence_score if proj.confidence_score > 0 else 30
    else:
        estimated_ip = 180 * proj.confidence_score if proj.confidence_score > 0 else 90

    stats = {
        "IP": estimated_ip,
        "K": proj.projected_k,
        "SV": proj.projected_sv,
        "W": proj.projected_w,
    }

    # Estimate counting stats from rate stats
    # H = WHIP * IP - BB; ER = ERA * IP / 9
    era = proj.projected_era or 4.00
    whip = proj.projected_whip or 1.25
    stats["ER"] = era * estimated_ip / 9
    total_baserunners = whip * estimated_ip
    stats["BB"] = estimated_ip * 3.0 / 9  # ~3 BB/9 average
    stats["H"] = max(total_baserunners - stats["BB"], 0)

    # HLD: estimate from appearances if reliever
    if is_reliever and proj.projected_sv == 0:
        # Setup men average ~20-25 holds per season
        stats["HLD"] = 20 * proj.confidence_score if proj.confidence_score > 0 else 10

    # QS: estimate from ERA for starters
    # Roughly: if ERA < 4.00, QS rate ~55-65% of starts
    if not is_reliever:
        estimated_starts = estimated_ip / 6  # ~6 IP/start
        if era < 3.50:
            qs_rate = 0.65
        elif era < 4.00:
            qs_rate = 0.55
        elif era < 4.50:
            qs_rate = 0.40
        else:
            qs_rate = 0.25
        stats["QS"] = estimated_starts * qs_rate

    # HBP: estimate ~0.3 per 9 IP
    stats["HBP"] = estimated_ip * 0.3 / 9

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

    # Calculate actual points for all players
    summaries: list[PlayerPointsSummary] = []

    for player in hitters:
        summary = await calculate_player_actual_points(session, player, season, period)
        if summary and summary.player_type == "hitter":
            # Add projected points
            proj = await project_hitter(session, player, season)
            if proj:
                summary.projected_ros_points = round(
                    calculate_projected_batter_points(proj), 1
                )
            summaries.append(summary)

    for player in pitchers:
        summary = await calculate_player_actual_points(session, player, season, period)
        if summary and summary.player_type == "pitcher":
            proj = await project_pitcher(session, player, season)
            if proj:
                summary.projected_ros_points = round(
                    calculate_projected_pitcher_points(proj, is_reliever=summary.is_reliever), 1
                )
            summaries.append(summary)

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
