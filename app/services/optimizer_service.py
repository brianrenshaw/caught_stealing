"""Lineup optimizer using PuLP Integer Linear Programming.

Maximizes total projected fantasy points subject to position eligibility
and roster slot constraints. Uses H2H Points league scoring from league_config.
"""

import logging
from dataclasses import dataclass

from pulp import LpMaximize, LpProblem, LpVariable, lpSum, value
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.league_config import ROSTER_SLOTS
from app.models.player import Player
from app.models.player_points import PlayerPoints
from app.models.projection import Projection
from app.models.roster import Roster

logger = logging.getLogger(__name__)

# Use league config roster slots as default
DEFAULT_SLOTS = {
    "C": ROSTER_SLOTS["C"],
    "1B": ROSTER_SLOTS["1B"],
    "2B": ROSTER_SLOTS["2B"],
    "3B": ROSTER_SLOTS["3B"],
    "SS": ROSTER_SLOTS["SS"],
    "OF": ROSTER_SLOTS["OF"],
    "Util": ROSTER_SLOTS["Util"],
    "SP": ROSTER_SLOTS["SP"],
    "RP": ROSTER_SLOTS["RP"],
    "P": ROSTER_SLOTS["P"],
    "BN": ROSTER_SLOTS["BN"],
}

# Positions eligible for each slot
SLOT_ELIGIBILITY = {
    "C": ["C"],
    "1B": ["1B"],
    "2B": ["2B"],
    "3B": ["3B"],
    "SS": ["SS"],
    "OF": ["OF", "LF", "CF", "RF"],
    "Util": ["C", "1B", "2B", "3B", "SS", "OF", "LF", "CF", "RF", "DH"],
    "SP": ["SP"],
    "RP": ["RP"],
    "P": ["SP", "RP"],  # Flexible: can be SP or RP — key strategic lever
    "BN": ["C", "1B", "2B", "3B", "SS", "OF", "LF", "CF", "RF", "DH", "SP", "RP"],
}


@dataclass
class OptimizedLineup:
    assignments: list[dict]  # {player_id, name, position, slot, projected_points}
    total_points: float
    improvement: float  # points gained vs current lineup


def _get_player_positions(position_str: str | None) -> list[str]:
    """Parse a player's eligible positions from a comma-separated string."""
    if not position_str:
        return []
    return [p.strip() for p in position_str.split(",")]


def _is_eligible(player_positions: list[str], slot: str) -> bool:
    """Check if a player with given positions is eligible for a slot."""
    eligible = SLOT_ELIGIBILITY.get(slot, [])
    return any(p in eligible for p in player_positions)


async def optimize_lineup(
    session: AsyncSession,
    league_id: str,
    season: int,
    slots: dict[str, int] | None = None,
) -> OptimizedLineup | None:
    """Optimize lineup for the user's team using ILP.

    Finds the assignment of players to roster slots that maximizes
    total projected fantasy points.
    """
    if slots is None:
        slots = DEFAULT_SLOTS

    # Get my team's roster
    result = await session.execute(
        select(Roster, Player)
        .join(Player)
        .where(
            Roster.league_id == league_id,
            Roster.is_my_team.is_(True),
        )
    )
    roster_entries = result.all()

    if not roster_entries:
        logger.warning("No roster found for optimization")
        return None

    # Get projected points for each player from the player_points table
    players: list[dict] = []
    for roster, player in roster_entries:
        # Use pre-calculated fantasy points from points_service
        pp_result = await session.execute(
            select(PlayerPoints).where(
                PlayerPoints.player_id == player.id,
                PlayerPoints.season == season,
                PlayerPoints.period == "full_season",
            )
        )
        pp = pp_result.scalar_one_or_none()

        if pp:
            points = pp.projected_ros_points or 0.0
        else:
            # Fallback: use blended projections with simple conversion
            proj_result = await session.execute(
                select(Projection).where(
                    Projection.player_id == player.id,
                    Projection.season == season,
                    Projection.system == "blended",
                )
            )
            projections = proj_result.scalars().all()
            points = 0.0
            for proj in projections:
                if proj.stat_name in ("HR", "R", "RBI", "SB", "W", "SV", "K"):
                    points += proj.projected_value
                elif proj.stat_name == "AVG":
                    points += proj.projected_value * 100
                elif proj.stat_name == "ERA":
                    points -= proj.projected_value * 5
                elif proj.stat_name == "WHIP":
                    points -= proj.projected_value * 10

        positions = _get_player_positions(player.position)

        players.append(
            {
                "player_id": player.id,
                "name": player.name,
                "positions": positions,
                "projected_points": round(points, 1),
                "current_slot": roster.roster_position,
            }
        )

    if not players:
        return None

    # Build ILP model
    prob = LpProblem("fantasy_lineup_optimizer", LpMaximize)

    # Expand slots (e.g., OF: 3 → OF_1, OF_2, OF_3)
    expanded_slots: list[str] = []
    for slot, count in slots.items():
        if slot == "BN":
            continue  # bench players not optimized for points
        for i in range(count):
            expanded_slots.append(f"{slot}_{i + 1}")

    # Decision variables: x[player_idx][slot] = 1 if player assigned to slot
    x = {}
    for i, player in enumerate(players):
        for slot in expanded_slots:
            base_slot = slot.rsplit("_", 1)[0]
            if _is_eligible(player["positions"], base_slot):
                x[(i, slot)] = LpVariable(f"x_{i}_{slot}", cat="Binary")

    # Objective: maximize total projected points for active (non-bench) slots
    prob += lpSum(x[(i, slot)] * players[i]["projected_points"] for (i, slot) in x)

    # Constraint: each player assigned to at most one slot
    for i in range(len(players)):
        player_vars = [x[(i, slot)] for (pi, slot) in x if pi == i]
        if player_vars:
            prob += lpSum(player_vars) <= 1

    # Constraint: each slot filled by exactly one player
    for slot in expanded_slots:
        slot_vars = [x[(i, slot)] for (i, s) in x if s == slot]
        if slot_vars:
            prob += lpSum(slot_vars) == 1

    # Solve
    prob.solve()

    if prob.status != 1:
        logger.warning(f"Optimizer failed with status {prob.status}")
        return None

    # Extract assignments
    assignments = []
    for (i, slot), var in x.items():
        if value(var) == 1:
            base_slot = slot.rsplit("_", 1)[0]
            assignments.append(
                {
                    "player_id": players[i]["player_id"],
                    "name": players[i]["name"],
                    "position": ",".join(players[i]["positions"]),
                    "slot": base_slot,
                    "projected_points": players[i]["projected_points"],
                }
            )

    total = sum(a["projected_points"] for a in assignments)

    # Calculate current lineup points for comparison
    current_total = sum(
        p["projected_points"]
        for p in players
        if p["current_slot"] not in ("BN", "IL", "IL+", "NA", "DL")
    )

    assignments.sort(key=lambda a: a["projected_points"], reverse=True)

    return OptimizedLineup(
        assignments=assignments,
        total_points=round(total, 1),
        improvement=round(total - current_total, 1),
    )
