"""Trade value calculator using fantasy points surplus value and z-score methodology.

Supports both H2H Points league evaluation (default) and 5x5 roto z-score evaluation.
The points-based evaluation uses projected fantasy points and surplus value from the
player_points table, providing league-specific trade analysis.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.league_config import BATTING_SCORING, PITCHING_SCORING
from app.models.player import Player
from app.models.player_points import PlayerPoints
from app.models.trade_value import TradeValue
from app.services.points_service import get_points_breakdown
from app.services.projection_service import (
    project_all_hitters,
    project_all_pitchers,
)
from app.services.rankings_service import ROSTER_SPOTS

logger = logging.getLogger(__name__)

# 5x5 roto categories
HITTER_CATS = ["projected_hr", "projected_r", "projected_rbi", "projected_sb", "projected_avg"]
PITCHER_CATS = ["projected_w", "projected_sv", "projected_k", "projected_era", "projected_whip"]
LOWER_IS_BETTER = {"projected_era", "projected_whip"}


@dataclass
class TradeEvaluation:
    """Result of evaluating a trade between two sides."""

    side_a_players: list[dict]
    side_b_players: list[dict]
    side_a_total_value: float
    side_b_total_value: float
    value_difference: float
    fairness: str  # fair, slightly_favors_a/b, heavily_favors_a/b
    category_impact_a: dict[str, float]  # net change in each category for side A
    category_impact_b: dict[str, float]
    # Points-specific fields
    scoring_type: str = "points"
    points_analysis: dict = field(default_factory=dict)  # league-specific analysis


def _z_scores(values: list[float], invert: bool = False) -> list[float]:
    """Calculate z-scores for a list of values. Invert for stats where lower is better."""
    arr = np.array(values, dtype=float)
    mean = np.nanmean(arr)
    std = np.nanstd(arr)
    if std == 0:
        return [0.0] * len(values)
    z = (arr - mean) / std
    if invert:
        z = -z
    return z.tolist()


async def calculate_trade_values(
    session: AsyncSession, season: int
) -> tuple[list[dict], list[dict]]:
    """Calculate z-score-based trade values for all projected players.

    Returns (hitter_values, pitcher_values) where each is a list of dicts
    with player info and trade value metrics.
    """
    hitter_projs = await project_all_hitters(session, season)
    pitcher_projs = await project_all_pitchers(session, season)

    # Calculate hitter z-scores
    hitter_values = []
    if hitter_projs:
        for cat in HITTER_CATS:
            cat_values = [getattr(p, cat, 0) or 0 for p in hitter_projs]
            z = _z_scores(cat_values, invert=(cat in LOWER_IS_BETTER))
            for i, proj in enumerate(hitter_projs):
                if len(hitter_values) <= i:
                    hitter_values.append(
                        {
                            "player_id": proj.player_id,
                            "name": proj.player_name,
                            "team": proj.team,
                            "position": proj.position,
                            "z_scores": {},
                            "player_type": "hitter",
                        }
                    )
                hitter_values[i]["z_scores"][cat] = round(z[i], 3)

        # Sum z-scores for total value
        for hv in hitter_values:
            hv["z_score_total"] = round(sum(hv["z_scores"].values()), 3)

        # Calculate position-based replacement level
        for hv in hitter_values:
            pos = (hv["position"] or "UTIL").split(",")[0].strip()
            n = ROSTER_SPOTS.get(pos, 12)
            same_pos = sorted(
                [h for h in hitter_values if (h["position"] or "").split(",")[0].strip() == pos],
                key=lambda h: h["z_score_total"],
                reverse=True,
            )
            repl_val = same_pos[n]["z_score_total"] if len(same_pos) > n else -1.0
            hv["surplus_value"] = round(hv["z_score_total"] - repl_val, 3)

        # Assign positional rank
        by_pos: dict[str, list[dict]] = {}
        for hv in hitter_values:
            pos = (hv["position"] or "UTIL").split(",")[0].strip()
            by_pos.setdefault(pos, []).append(hv)
        for pos, players in by_pos.items():
            players.sort(key=lambda p: p["z_score_total"], reverse=True)
            for i, p in enumerate(players, 1):
                p["positional_rank"] = i

    # Calculate pitcher z-scores
    pitcher_values = []
    if pitcher_projs:
        for cat in PITCHER_CATS:
            cat_values = [getattr(p, cat, 0) or 0 for p in pitcher_projs]
            z = _z_scores(cat_values, invert=(cat in LOWER_IS_BETTER))
            for i, proj in enumerate(pitcher_projs):
                if len(pitcher_values) <= i:
                    pitcher_values.append(
                        {
                            "player_id": proj.player_id,
                            "name": proj.player_name,
                            "team": proj.team,
                            "position": proj.position,
                            "z_scores": {},
                            "player_type": "pitcher",
                        }
                    )
                pitcher_values[i]["z_scores"][cat] = round(z[i], 3)

        for pv in pitcher_values:
            pv["z_score_total"] = round(sum(pv["z_scores"].values()), 3)

        # Pitcher replacement levels
        sp_pitchers = sorted(
            [p for p in pitcher_values if "SP" in (p["position"] or "")],
            key=lambda p: p["z_score_total"],
            reverse=True,
        )
        rp_pitchers = sorted(
            [
                p
                for p in pitcher_values
                if "RP" in (p["position"] or "") and "SP" not in (p["position"] or "")
            ],
            key=lambda p: p["z_score_total"],
            reverse=True,
        )

        sp_repl = (
            sp_pitchers[ROSTER_SPOTS.get("SP", 84)]["z_score_total"]
            if len(sp_pitchers) > ROSTER_SPOTS.get("SP", 84)
            else -1.0
        )
        rp_repl = (
            rp_pitchers[ROSTER_SPOTS.get("RP", 36)]["z_score_total"]
            if len(rp_pitchers) > ROSTER_SPOTS.get("RP", 36)
            else -1.0
        )

        for pv in pitcher_values:
            if "SP" in (pv["position"] or ""):
                pv["surplus_value"] = round(pv["z_score_total"] - sp_repl, 3)
            else:
                pv["surplus_value"] = round(pv["z_score_total"] - rp_repl, 3)

        # Positional rank
        sp_pitchers_sorted = sorted(sp_pitchers, key=lambda p: p["z_score_total"], reverse=True)
        for i, p in enumerate(sp_pitchers_sorted, 1):
            p["positional_rank"] = i
        rp_sorted = sorted(rp_pitchers, key=lambda p: p["z_score_total"], reverse=True)
        for i, p in enumerate(rp_sorted, 1):
            p["positional_rank"] = i

    return hitter_values, pitcher_values


async def store_trade_values(
    session: AsyncSession, hitter_values: list[dict], pitcher_values: list[dict]
) -> int:
    """Store calculated trade values in the database."""
    from sqlalchemy import delete

    await session.execute(delete(TradeValue))

    count = 0
    for values in [hitter_values, pitcher_values]:
        for v in values:
            tv = TradeValue(
                player_id=v["player_id"],
                surplus_value=v.get("surplus_value", 0),
                positional_rank=v.get("positional_rank", 0),
                z_score_total=v.get("z_score_total", 0),
            )
            session.add(tv)
            count += 1

    await session.flush()
    logger.info(f"Stored {count} trade values")
    return count


async def evaluate_trade(
    session: AsyncSession,
    side_a_ids: list[int],
    side_b_ids: list[int],
    season: int,
    scoring_type: str = "points",
) -> TradeEvaluation:
    """Evaluate a trade between two sides.

    side_a_ids and side_b_ids are lists of player IDs being traded.
    Side A gives away side_a_ids and receives side_b_ids (and vice versa).

    scoring_type: "points" (default) uses H2H points surplus value,
                  "roto" uses z-score methodology.
    """
    if scoring_type == "points":
        return await _evaluate_trade_points(session, side_a_ids, side_b_ids, season)
    return await _evaluate_trade_roto(session, side_a_ids, side_b_ids, season)


async def _evaluate_trade_points(
    session: AsyncSession,
    side_a_ids: list[int],
    side_b_ids: list[int],
    season: int,
) -> TradeEvaluation:
    """Evaluate a trade using H2H Points league surplus value.

    Provides league-specific analysis including:
    - Net projected points gained/lost per side
    - Points breakdown showing why the trade is good/bad in this scoring format
    - Key scoring insights (saves value, innings value, K impact, etc.)
    """
    all_ids = side_a_ids + side_b_ids

    side_a_players = []
    side_b_players = []

    for player_id in all_ids:
        result = await session.execute(
            select(Player, PlayerPoints)
            .join(PlayerPoints, PlayerPoints.player_id == Player.id)
            .where(
                Player.id == player_id,
                PlayerPoints.season == season,
                PlayerPoints.period == "full_season",
            )
        )
        row = result.first()
        if row:
            player, pp = row
            info = {
                "player_id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "player_type": pp.player_type,
                "surplus_value": pp.surplus_value or 0.0,
                "projected_points": pp.projected_ros_points or 0.0,
                "actual_points": pp.actual_points or 0.0,
                "positional_rank": pp.positional_rank or 0,
                "points_per_pa": pp.points_per_pa,
                "points_per_ip": pp.points_per_ip,
                "points_per_start": pp.points_per_start,
                "points_per_appearance": pp.points_per_appearance,
                "is_reliever": pp.points_per_appearance is not None,
            }
            if player_id in side_a_ids:
                side_a_players.append(info)
            else:
                side_b_players.append(info)

    side_a_total = sum(p["surplus_value"] for p in side_a_players)
    side_b_total = sum(p["surplus_value"] for p in side_b_players)
    diff = side_a_total - side_b_total

    # Points-based fairness thresholds (wider than z-scores since points range is larger)
    if abs(diff) < 20:
        fairness = "fair"
    elif diff > 75:
        fairness = "heavily_favors_b"
    elif diff > 20:
        fairness = "slightly_favors_b"
    elif diff < -75:
        fairness = "heavily_favors_a"
    else:
        fairness = "slightly_favors_a"

    # Build league-specific analysis
    points_analysis = _build_points_analysis(side_a_players, side_b_players)

    return TradeEvaluation(
        side_a_players=side_a_players,
        side_b_players=side_b_players,
        side_a_total_value=round(side_a_total, 1),
        side_b_total_value=round(side_b_total, 1),
        value_difference=round(abs(diff), 1),
        fairness=fairness,
        category_impact_a={},
        category_impact_b={},
        scoring_type="points",
        points_analysis=points_analysis,
    )


def _build_points_analysis(side_a: list[dict], side_b: list[dict]) -> dict:
    """Build league-specific trade analysis with scoring insights."""
    analysis = {
        "side_a_projected_total": sum(p["projected_points"] for p in side_a),
        "side_b_projected_total": sum(p["projected_points"] for p in side_b),
        "insights": [],
    }

    # Check for reliever premium
    a_relievers = [p for p in side_a if p.get("is_reliever")]
    b_relievers = [p for p in side_b if p.get("is_reliever")]
    if a_relievers or b_relievers:
        a_rp_pts = sum(p["projected_points"] for p in a_relievers)
        b_rp_pts = sum(p["projected_points"] for p in b_relievers)
        if a_rp_pts > 0 or b_rp_pts > 0:
            analysis["insights"].append(
                f"Reliever value: Side A gives up {a_rp_pts:.0f} projected RP points, "
                f"Side B gives up {b_rp_pts:.0f}. "
                f"(SV=7, HLD=4 — relievers are premium in this format)"
            )

    # Check for starter volume
    a_starters = [p for p in side_a if p.get("points_per_start") is not None]
    b_starters = [p for p in side_b if p.get("points_per_start") is not None]
    if a_starters or b_starters:
        a_sp_pts = sum(p["projected_points"] for p in a_starters)
        b_sp_pts = sum(p["projected_points"] for p in b_starters)
        analysis["insights"].append(
            f"Starter value: Side A gives up {a_sp_pts:.0f} projected SP points, "
            f"Side B gives up {b_sp_pts:.0f}. "
            f"(Innings = 4.5 pts/IP — volume starters are gold)"
        )

    # Points differential context
    diff = analysis["side_a_projected_total"] - analysis["side_b_projected_total"]
    if abs(diff) > 50:
        analysis["insights"].append(
            f"Projected points gap: {abs(diff):.0f} points — "
            f"equivalent to roughly {abs(diff) / 7:.0f} saves or "
            f"{abs(diff) / 4.5:.0f} extra innings pitched"
        )

    return analysis


async def _evaluate_trade_roto(
    session: AsyncSession,
    side_a_ids: list[int],
    side_b_ids: list[int],
    season: int,
) -> TradeEvaluation:
    """Evaluate a trade using 5x5 roto z-score methodology (legacy)."""
    # Ensure trade values exist — calculate and store if table is empty
    tv_check = await session.execute(select(TradeValue).limit(1))
    if tv_check.scalar_one_or_none() is None:
        hitter_values, pitcher_values = await calculate_trade_values(session, season)
        if hitter_values or pitcher_values:
            await store_trade_values(session, hitter_values, pitcher_values)
            await session.flush()

    # Get trade values for all involved players
    all_ids = side_a_ids + side_b_ids

    side_a_players = []
    side_b_players = []

    for player_id in all_ids:
        result = await session.execute(
            select(Player, TradeValue).join(TradeValue).where(Player.id == player_id)
        )
        row = result.first()
        if row:
            player, tv = row
            info = {
                "player_id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "surplus_value": tv.surplus_value,
                "z_score_total": tv.z_score_total,
                "positional_rank": tv.positional_rank,
            }
            if player_id in side_a_ids:
                side_a_players.append(info)
            else:
                side_b_players.append(info)

    side_a_total = sum(p["surplus_value"] for p in side_a_players)
    side_b_total = sum(p["surplus_value"] for p in side_b_players)
    diff = side_a_total - side_b_total

    if abs(diff) < 0.5:
        fairness = "fair"
    elif diff > 2.0:
        fairness = "heavily_favors_b"  # Side B receives more value
    elif diff > 0.5:
        fairness = "slightly_favors_b"
    elif diff < -2.0:
        fairness = "heavily_favors_a"
    else:
        fairness = "slightly_favors_a"

    return TradeEvaluation(
        side_a_players=side_a_players,
        side_b_players=side_b_players,
        side_a_total_value=round(side_a_total, 2),
        side_b_total_value=round(side_b_total, 2),
        value_difference=round(abs(diff), 2),
        fairness=fairness,
        category_impact_a={},
        category_impact_b={},
        scoring_type="roto",
    )
