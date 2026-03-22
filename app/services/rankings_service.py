"""Fantasy baseball rankings engine.

Converts raw projections into actionable fantasy rankings with
5x5 roto scoring, points league scoring, and position scarcity adjustments.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.statcast_summary import StatcastSummary
from app.services.projection_service import (
    HitterProjection,
    PitcherProjection,
    project_all_hitters,
    project_all_pitchers,
)

logger = logging.getLogger(__name__)

# 5x5 Roto categories
HITTING_CATEGORIES = ["HR", "R", "RBI", "SB", "AVG"]
PITCHING_CATEGORIES = ["W", "SV", "K", "ERA", "WHIP"]

# Categories where lower is better
LOWER_IS_BETTER = {"ERA", "WHIP"}

# Typical roster spots per position in a 12-team league
ROSTER_SPOTS = {
    "C": 12,
    "1B": 12,
    "2B": 12,
    "3B": 12,
    "SS": 12,
    "OF": 60,  # 5 OF spots * 12 teams
    "SP": 84,  # ~7 SP * 12 teams
    "RP": 36,  # ~3 RP * 12 teams
}


@dataclass
class ScoringConfig:
    """Points league scoring weights."""

    # Hitting
    h: float = 1.0
    doubles: float = 2.0
    triples: float = 3.0
    hr: float = 4.0
    r: float = 1.0
    rbi: float = 1.0
    bb: float = 1.0
    sb: float = 2.0
    cs: float = -1.0
    so_hitting: float = -0.5
    # Pitching
    ip: float = 3.0
    w: float = 5.0
    sv: float = 5.0
    k: float = 1.0
    er: float = -2.0
    h_pitching: float = -0.5
    bb_pitching: float = -0.5
    qs: float = 3.0


@dataclass
class RankedPlayer:
    player_id: int
    name: str
    team: str | None
    position: str | None
    overall_rank: int = 0
    position_rank: int = 0
    # Projected stats
    projected_hr: float = 0.0
    projected_r: float = 0.0
    projected_rbi: float = 0.0
    projected_sb: float = 0.0
    projected_avg: float = 0.0
    projected_w: float = 0.0
    projected_sv: float = 0.0
    projected_k: float = 0.0
    projected_era: float = 0.0
    projected_whip: float = 0.0
    # Ranking metadata
    composite_score: float = 0.0
    value_above_replacement: float = 0.0
    buy_low: bool = False
    sell_high: bool = False
    xwoba_delta: float = 0.0
    trend: str = "stable"  # hot, cold, stable
    player_type: str = "hitter"  # hitter or pitcher
    confidence: float = 0.0


def _rank_category(players: list[dict], cat: str) -> list[dict]:
    """Assign category rank to each player for a given stat."""
    reverse = cat not in LOWER_IS_BETTER
    sorted_players = sorted(players, key=lambda p: p.get(cat, 0) or 0, reverse=reverse)
    for i, p in enumerate(sorted_players, 1):
        p[f"{cat}_rank"] = i
    return sorted_players


def _compute_roto_rankings(
    hitter_projs: list[HitterProjection],
    pitcher_projs: list[PitcherProjection],
) -> list[RankedPlayer]:
    """Compute 5x5 roto rankings from projections."""
    ranked: list[RankedPlayer] = []

    # Build hitter ranking data
    hitter_data = []
    for p in hitter_projs:
        hitter_data.append(
            {
                "proj": p,
                "HR": p.projected_hr,
                "R": p.projected_r,
                "RBI": p.projected_rbi,
                "SB": p.projected_sb,
                "AVG": p.projected_avg,
            }
        )

    # Rank each hitting category
    for cat in HITTING_CATEGORIES:
        _rank_category(hitter_data, cat)

    # Composite score = sum of category ranks (lower = better)
    for h in hitter_data:
        h["composite"] = sum(h.get(f"{cat}_rank", 0) for cat in HITTING_CATEGORIES)

    hitter_data.sort(key=lambda h: h["composite"])
    for i, h in enumerate(hitter_data, 1):
        p = h["proj"]
        ranked.append(
            RankedPlayer(
                player_id=p.player_id,
                name=p.player_name,
                team=p.team,
                position=p.position,
                overall_rank=0,  # set after combining with pitchers
                projected_hr=p.projected_hr,
                projected_r=p.projected_r,
                projected_rbi=p.projected_rbi,
                projected_sb=p.projected_sb,
                projected_avg=p.projected_avg,
                composite_score=h["composite"],
                buy_low=p.buy_low_signal,
                sell_high=p.sell_high_signal,
                xwoba_delta=p.xwoba_delta,
                player_type="hitter",
                confidence=p.confidence_score,
            )
        )

    # Build pitcher ranking data
    pitcher_data = []
    for p in pitcher_projs:
        pitcher_data.append(
            {
                "proj": p,
                "W": p.projected_w,
                "SV": p.projected_sv,
                "K": p.projected_k,
                "ERA": p.projected_era,
                "WHIP": p.projected_whip,
            }
        )

    for cat in PITCHING_CATEGORIES:
        _rank_category(pitcher_data, cat)

    for pd_ in pitcher_data:
        pd_["composite"] = sum(pd_.get(f"{cat}_rank", 0) for cat in PITCHING_CATEGORIES)

    pitcher_data.sort(key=lambda pd_: pd_["composite"])
    for pd_ in pitcher_data:
        p = pd_["proj"]
        ranked.append(
            RankedPlayer(
                player_id=p.player_id,
                name=p.player_name,
                team=p.team,
                position=p.position,
                overall_rank=0,
                projected_w=p.projected_w,
                projected_sv=p.projected_sv,
                projected_k=p.projected_k,
                projected_era=p.projected_era,
                projected_whip=p.projected_whip,
                composite_score=pd_["composite"],
                buy_low=p.buy_low_signal,
                sell_high=p.sell_high_signal,
                xwoba_delta=p.xwoba_delta,
                player_type="pitcher",
                confidence=p.confidence_score,
            )
        )

    # Sort all players by composite score and assign overall rank
    ranked.sort(key=lambda r: r.composite_score)
    for i, r in enumerate(ranked, 1):
        r.overall_rank = i

    # Assign position ranks
    pos_counts: dict[str, int] = {}
    for r in ranked:
        pos = r.position or "UTIL"
        primary = pos.split(",")[0].strip() if pos else "UTIL"
        pos_counts[primary] = pos_counts.get(primary, 0) + 1
        r.position_rank = pos_counts[primary]

    return ranked


def _apply_position_scarcity(ranked: list[RankedPlayer]) -> list[RankedPlayer]:
    """Adjust rankings by value above replacement at each position."""
    # Group by position
    by_position: dict[str, list[RankedPlayer]] = {}
    for r in ranked:
        pos = (r.position or "UTIL").split(",")[0].strip()
        by_position.setdefault(pos, []).append(r)

    # Calculate replacement level for each position
    for pos, players in by_position.items():
        n = ROSTER_SPOTS.get(pos, 12)
        # Replacement level = composite score of the (N+1)th player
        if len(players) > n:
            replacement_score = players[n].composite_score
        else:
            replacement_score = players[-1].composite_score + 10 if players else 0

        for p in players:
            # VAR = how much better than replacement (lower composite = better, so invert)
            p.value_above_replacement = round(replacement_score - p.composite_score, 1)

    # Re-sort by VAR descending
    ranked.sort(key=lambda r: r.value_above_replacement, reverse=True)
    for i, r in enumerate(ranked, 1):
        r.overall_rank = i

    return ranked


async def _detect_trend(session: AsyncSession, player_id: int, season: int) -> str:
    """Detect hot/cold trend by comparing last-14 Statcast to full season."""
    full = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == player_id,
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
        )
    )
    full_sc = full.scalar_one_or_none()

    recent = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == player_id,
            StatcastSummary.season == season,
            StatcastSummary.period == "last_14",
        )
    )
    recent_sc = recent.scalar_one_or_none()

    if not full_sc or not recent_sc:
        return "stable"
    if full_sc.xwoba and recent_sc.xwoba:
        delta = recent_sc.xwoba - full_sc.xwoba
        if delta > 0.020:
            return "hot"
        elif delta < -0.020:
            return "cold"
    return "stable"


async def get_overall_rankings(
    session: AsyncSession,
    season: int,
    scoring_type: str = "roto",
    limit: int = 300,
) -> list[RankedPlayer]:
    """Generate overall fantasy rankings."""
    hitter_projs = await project_all_hitters(session, season)
    pitcher_projs = await project_all_pitchers(session, season)

    ranked = _compute_roto_rankings(hitter_projs, pitcher_projs)
    ranked = _apply_position_scarcity(ranked)

    # Add trend detection for top players
    for r in ranked[: min(limit, 100)]:
        r.trend = await _detect_trend(session, r.player_id, season)

    return ranked[:limit]


async def get_position_rankings(
    session: AsyncSession,
    position: str,
    season: int,
    scoring_type: str = "roto",
    limit: int = 50,
) -> list[RankedPlayer]:
    """Get rankings filtered by position."""
    all_ranked = await get_overall_rankings(session, season, scoring_type, limit=500)
    pos_ranked = [r for r in all_ranked if r.position and position in r.position]
    return pos_ranked[:limit]


async def get_buy_low_candidates(
    session: AsyncSession, season: int, limit: int = 20
) -> list[RankedPlayer]:
    """Players whose xwOBA exceeds actual wOBA — underperforming their batted ball quality."""
    all_ranked = await get_overall_rankings(session, season, limit=300)
    buy_low = [r for r in all_ranked if r.buy_low]
    buy_low.sort(key=lambda r: r.xwoba_delta, reverse=True)
    return buy_low[:limit]


async def get_sell_high_candidates(
    session: AsyncSession, season: int, limit: int = 20
) -> list[RankedPlayer]:
    """Players whose actual wOBA exceeds xwOBA — overperforming their batted ball quality."""
    all_ranked = await get_overall_rankings(session, season, limit=300)
    sell_high = [r for r in all_ranked if r.sell_high]
    sell_high.sort(key=lambda r: r.xwoba_delta)
    return sell_high[:limit]


async def get_hot_pickups(
    session: AsyncSession, season: int, limit: int = 20
) -> list[RankedPlayer]:
    """Players trending hot based on recent Statcast metrics vs season averages."""
    all_ranked = await get_overall_rankings(session, season, limit=500)
    hot = [r for r in all_ranked if r.trend == "hot"]
    hot.sort(key=lambda r: r.value_above_replacement, reverse=True)
    return hot[:limit]
