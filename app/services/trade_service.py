"""Trade value calculator using VORP and z-score methodology.

Calculates surplus value (value above replacement) for each player
to enable fair trade evaluation.
"""

import logging
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import Player
from app.models.trade_value import TradeValue
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
) -> TradeEvaluation:
    """Evaluate a trade between two sides.

    side_a_ids and side_b_ids are lists of player IDs being traded.
    Side A gives away side_a_ids and receives side_b_ids (and vice versa).
    """
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
        category_impact_a={},  # Could be expanded with per-category z-score changes
        category_impact_b={},
    )
