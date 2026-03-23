"""Player profile aggregation service.

Assembles a complete player profile from multiple data sources:
batting/pitching stats, Statcast, projections, trade values, and roster status.
"""

import logging
import math
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.projection import Projection
from app.models.roster import Roster
from app.models.statcast_summary import StatcastSummary
from app.models.trade_value import TradeValue

logger = logging.getLogger(__name__)

PERIODS = ("full_season", "last_30", "last_14", "last_7")


@dataclass
class PerformanceGaps:
    xba_vs_avg: float | None = None
    xslg_vs_slg: float | None = None
    xwoba_vs_woba: float | None = None
    fip_vs_era: float | None = None
    composite_score: float = 0.0
    signal: str = "neutral"  # "buy_low", "sell_high", "neutral"


@dataclass
class PlayerProfile:
    player: Player
    batting_stats: dict[str, BattingStats | None] = field(default_factory=dict)
    pitching_stats: dict[str, PitchingStats | None] = field(default_factory=dict)
    statcast_bat: dict[str, StatcastSummary | None] = field(default_factory=dict)
    statcast_pitch: dict[str, StatcastSummary | None] = field(default_factory=dict)
    projections: dict[str, dict[str, float]] = field(default_factory=dict)
    trade_value: TradeValue | None = None
    roster_info: dict | None = None
    gaps: PerformanceGaps | None = None
    comparable_players: list[dict] = field(default_factory=list)

    @property
    def is_hitter(self) -> bool:
        return bool(self.batting_stats.get("full_season"))

    @property
    def is_pitcher(self) -> bool:
        return bool(self.pitching_stats.get("full_season"))


async def get_player_profile(
    session: AsyncSession, player_id: int, season: int
) -> PlayerProfile | None:
    """Build a complete player profile."""
    player = await session.get(Player, player_id)
    if not player:
        return None

    profile = PlayerProfile(player=player)

    # Batting stats by period
    for period in PERIODS:
        result = await session.execute(
            select(BattingStats).where(
                BattingStats.player_id == player_id,
                BattingStats.season == season,
                BattingStats.period == period,
            )
        )
        profile.batting_stats[period] = result.scalar_one_or_none()

    # Pitching stats by period
    for period in PERIODS:
        result = await session.execute(
            select(PitchingStats).where(
                PitchingStats.player_id == player_id,
                PitchingStats.season == season,
                PitchingStats.period == period,
            )
        )
        profile.pitching_stats[period] = result.scalar_one_or_none()

    # Statcast by period (batter + pitcher)
    for period in ("full_season", "last_30", "last_14"):
        pairs = [("batter", profile.statcast_bat), ("pitcher", profile.statcast_pitch)]
        for ptype, target in pairs:
            result = await session.execute(
                select(StatcastSummary).where(
                    StatcastSummary.player_id == player_id,
                    StatcastSummary.season == season,
                    StatcastSummary.period == period,
                    StatcastSummary.player_type == ptype,
                )
            )
            target[period] = result.scalar_one_or_none()

    # Projections grouped by system
    proj_result = await session.execute(
        select(Projection).where(
            Projection.player_id == player_id,
            Projection.season == season,
        )
    )
    for proj in proj_result.scalars().all():
        if proj.system not in profile.projections:
            profile.projections[proj.system] = {}
        profile.projections[proj.system][proj.stat_name] = proj.projected_value

    # Trade value (most recent)
    tv_result = await session.execute(
        select(TradeValue)
        .where(TradeValue.player_id == player_id)
        .order_by(TradeValue.updated_at.desc())
        .limit(1)
    )
    profile.trade_value = tv_result.scalar_one_or_none()

    # Roster status
    roster_result = await session.execute(select(Roster).where(Roster.player_id == player_id))
    roster_entry = roster_result.scalar_one_or_none()
    if roster_entry:
        profile.roster_info = {
            "team_name": roster_entry.team_name,
            "roster_position": roster_entry.roster_position,
            "is_my_team": roster_entry.is_my_team,
        }

    # Performance gaps / buy-low sell-high signals
    profile.gaps = _compute_gaps(profile)

    return profile


def _compute_gaps(profile: PlayerProfile) -> PerformanceGaps:
    """Compute performance gaps between expected and actual stats."""
    gaps = PerformanceGaps()

    bat_full = profile.batting_stats.get("full_season")
    sc_bat = profile.statcast_bat.get("full_season")
    pitch_full = profile.pitching_stats.get("full_season")

    scores = []

    if bat_full and sc_bat:
        if sc_bat.xba is not None and bat_full.avg is not None:
            gaps.xba_vs_avg = round(sc_bat.xba - bat_full.avg, 3)
            scores.append(gaps.xba_vs_avg)
        if sc_bat.xslg is not None and bat_full.slg is not None:
            gaps.xslg_vs_slg = round(sc_bat.xslg - bat_full.slg, 3)
            scores.append(gaps.xslg_vs_slg)
        if sc_bat.xwoba is not None and bat_full.woba is not None:
            gaps.xwoba_vs_woba = round(sc_bat.xwoba - bat_full.woba, 3)
            scores.append(gaps.xwoba_vs_woba * 2)  # weight xwOBA gap higher

    if pitch_full:
        if pitch_full.fip is not None and pitch_full.era is not None:
            # For pitchers, FIP < ERA means ERA should drop (buy low)
            gaps.fip_vs_era = round(pitch_full.fip - pitch_full.era, 2)
            scores.append(gaps.fip_vs_era)

    if scores:
        gaps.composite_score = round(sum(scores) / len(scores), 3)
        if gaps.composite_score >= 0.020:
            gaps.signal = "buy_low"
        elif gaps.composite_score <= -0.020:
            gaps.signal = "sell_high"

    return gaps


async def get_comparable_players(
    session: AsyncSession, player_id: int, season: int, limit: int = 5
) -> list[dict]:
    """Find players with the most similar statistical profile."""
    # Get the target player's key stats
    bat_result = await session.execute(
        select(BattingStats).where(
            BattingStats.player_id == player_id,
            BattingStats.season == season,
            BattingStats.period == "full_season",
        ).limit(1)
    )
    target_bat = bat_result.scalar_one_or_none()

    pitch_result = await session.execute(
        select(PitchingStats).where(
            PitchingStats.player_id == player_id,
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
        ).limit(1)
    )
    target_pitch = pitch_result.scalar_one_or_none()

    sc_result = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == player_id,
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
        ).limit(1)
    )
    target_sc = sc_result.scalar_one_or_none()

    if target_bat and target_bat.pa and target_bat.pa >= 50:
        return await _comparable_hitters(session, player_id, season, target_bat, target_sc, limit)
    elif target_pitch and target_pitch.ip and target_pitch.ip >= 20:
        return await _comparable_pitchers(session, player_id, season, target_pitch, limit)
    return []


async def _comparable_hitters(
    session: AsyncSession,
    player_id: int,
    season: int,
    target: BattingStats,
    target_sc: StatcastSummary | None,
    limit: int,
) -> list[dict]:
    """Find similar hitters by wRC+, wOBA, ISO, K%, BB%."""
    result = await session.execute(
        select(BattingStats, Player)
        .join(Player)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.pa >= 50,
            BattingStats.player_id != player_id,
        )
    )
    rows = result.all()

    target_vec = [
        target.wrc_plus or 100,
        (target.woba or 0.320) * 300,  # scale wOBA to similar range as wRC+
        (target.iso or 0.150) * 500,
        (target.k_pct or 0.22) * 300,
        (target.bb_pct or 0.08) * 300,
    ]

    comps = []
    for bat, player in rows:
        vec = [
            bat.wrc_plus or 100,
            (bat.woba or 0.320) * 300,
            (bat.iso or 0.150) * 500,
            (bat.k_pct or 0.22) * 300,
            (bat.bb_pct or 0.08) * 300,
        ]
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(target_vec, vec)))
        comps.append(
            {
                "player_id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "distance": round(dist, 2),
                "wrc_plus": bat.wrc_plus,
                "woba": bat.woba,
            }
        )

    comps.sort(key=lambda x: x["distance"])
    return comps[:limit]


async def _comparable_pitchers(
    session: AsyncSession,
    player_id: int,
    season: int,
    target: PitchingStats,
    limit: int,
) -> list[dict]:
    """Find similar pitchers by ERA, FIP, K/9, BB/9, WHIP."""
    result = await session.execute(
        select(PitchingStats, Player)
        .join(Player)
        .where(
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.ip >= 20,
            PitchingStats.player_id != player_id,
        )
    )
    rows = result.all()

    target_vec = [
        (target.era or 4.0) * 10,
        (target.fip or 4.0) * 10,
        target.k_per_9 or 8.0,
        (target.bb_per_9 or 3.0) * 3,
        (target.whip or 1.3) * 30,
    ]

    comps = []
    for pitch, player in rows:
        vec = [
            (pitch.era or 4.0) * 10,
            (pitch.fip or 4.0) * 10,
            pitch.k_per_9 or 8.0,
            (pitch.bb_per_9 or 3.0) * 3,
            (pitch.whip or 1.3) * 30,
        ]
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(target_vec, vec)))
        comps.append(
            {
                "player_id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "distance": round(dist, 2),
                "era": pitch.era,
                "fip": pitch.fip,
            }
        )

    comps.sort(key=lambda x: x["distance"])
    return comps[:limit]
