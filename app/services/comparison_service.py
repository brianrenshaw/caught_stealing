"""Player comparison service.

Assembles rich player cards with percentile rankings, splits, rolling data,
and projections for side-by-side comparison. Builds on top of PlayerService
and RankingsService.
"""

import bisect
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.statcast_summary import StatcastSummary
from app.services.player_service import get_player_profile

logger = logging.getLogger(__name__)

# Cache TTL for league-wide distributions (1 hour)
TTL_PERCENTILE = 3600

HEADSHOT_URL_TEMPLATE = (
    "https://img.mlbstatic.com/mlb-photos/image/upload/"
    "d_people:generic:headshot:67:current.png/"
    "w_213,q_auto:best/v1/people/{mlbam_id}/headshot/67/current"
)

# ── Percentile stat definitions ──
# (display_name, model_attr, lower_is_better)

HITTER_BATTING_STATS = [
    ("AVG", "avg", False),
    ("OBP", "obp", False),
    ("SLG", "slg", False),
    ("OPS", "ops", False),
    ("wOBA", "woba", False),
    ("wRC+", "wrc_plus", False),
    ("ISO", "iso", False),
    ("BABIP", "babip", False),
    ("BB%", "bb_pct", False),
    ("K%", "k_pct", True),
    ("HR", "hr", False),
    ("SB", "sb", False),
    ("WAR", "war", False),
]

HITTER_STATCAST_STATS = [
    ("xBA", "xba", False),
    ("xSLG", "xslg", False),
    ("xwOBA", "xwoba", False),
    ("Barrel%", "barrel_pct", False),
    ("HardHit%", "hard_hit_pct", False),
    ("AvgEV", "avg_exit_velo", False),
    ("MaxEV", "max_exit_velo", False),
    ("SweetSpot%", "sweet_spot_pct", False),
    ("SprintSpeed", "sprint_speed", False),
    ("Whiff%", "whiff_pct", True),
    ("Chase%", "chase_pct", True),
]

PITCHER_STATS = [
    ("ERA", "era", True),
    ("FIP", "fip", True),
    ("xFIP", "xfip", True),
    ("WHIP", "whip", True),
    ("K/9", "k_per_9", False),
    ("BB/9", "bb_per_9", True),
    ("SIERA", "siera", True),
    ("K-BB%", "k_bb_pct", False),
    ("WAR", "war", False),
]

PITCHER_STATCAST_STATS = [
    ("xBA Against", "xba", True),
    ("xSLG Against", "xslg", True),
    ("xwOBA Against", "xwoba", True),
    ("Barrel% Against", "barrel_pct", True),
    ("HardHit% Against", "hard_hit_pct", True),
    ("AvgEV Against", "avg_exit_velo", True),
    ("Whiff%", "whiff_pct", False),
    ("Chase%", "chase_pct", False),
]


@dataclass
class StatPercentile:
    stat_name: str
    display_name: str
    value: float | None
    percentile: int  # 0-100
    rank: int
    total_qualified: int
    lower_is_better: bool = False


@dataclass
class PlayerCard:
    """Rich player card for comparison tool."""

    player: dict  # id, name, team, position, headshot_url, player_type
    traditional: dict = field(default_factory=dict)  # period -> {stat: value}
    statcast: dict = field(default_factory=dict)  # period -> {stat: value}
    percentiles: list[StatPercentile] = field(default_factory=list)
    projections: dict = field(default_factory=dict)  # system -> {stat: value}
    fantasy_value: dict = field(default_factory=dict)
    gaps: dict = field(default_factory=dict)  # buy/sell signal
    splits: dict = field(default_factory=dict)  # split_type -> {stat: value}
    rolling: dict = field(default_factory=dict)  # stat_name -> [full, l30, l14, l7]

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict."""
        return {
            "player": self.player,
            "traditional": self.traditional,
            "statcast": self.statcast,
            "percentiles": [
                {
                    "stat_name": p.stat_name,
                    "display_name": p.display_name,
                    "value": p.value,
                    "percentile": p.percentile,
                    "rank": p.rank,
                    "total_qualified": p.total_qualified,
                    "lower_is_better": p.lower_is_better,
                }
                for p in self.percentiles
            ],
            "projections": self.projections,
            "fantasy_value": self.fantasy_value,
            "gaps": self.gaps,
            "splits": self.splits,
            "rolling": self.rolling,
        }


def _headshot_url(mlbam_id: str | None) -> str | None:
    if not mlbam_id:
        return None
    return HEADSHOT_URL_TEMPLATE.format(mlbam_id=mlbam_id)


def _stat_dict_from_batting(bat: BattingStats | None) -> dict[str, float | None]:
    if not bat:
        return {}
    return {
        "pa": bat.pa,
        "ab": bat.ab,
        "h": bat.h,
        "doubles": bat.doubles,
        "triples": bat.triples,
        "hr": bat.hr,
        "r": bat.r,
        "rbi": bat.rbi,
        "sb": bat.sb,
        "cs": bat.cs,
        "bb": bat.bb,
        "so": bat.so,
        "avg": bat.avg,
        "obp": bat.obp,
        "slg": bat.slg,
        "ops": bat.ops,
        "woba": bat.woba,
        "wrc_plus": bat.wrc_plus,
        "iso": bat.iso,
        "babip": bat.babip,
        "k_pct": bat.k_pct,
        "bb_pct": bat.bb_pct,
        "war": bat.war,
    }


def _stat_dict_from_pitching(pitch: PitchingStats | None) -> dict[str, float | None]:
    if not pitch:
        return {}
    return {
        "w": pitch.w,
        "l": pitch.l,
        "sv": pitch.sv,
        "hld": pitch.hld,
        "g": pitch.g,
        "gs": pitch.gs,
        "ip": pitch.ip,
        "h": pitch.h,
        "er": pitch.er,
        "hr": pitch.hr,
        "bb": pitch.bb,
        "so": pitch.so,
        "era": pitch.era,
        "whip": pitch.whip,
        "k_per_9": pitch.k_per_9,
        "bb_per_9": pitch.bb_per_9,
        "fip": pitch.fip,
        "xfip": pitch.xfip,
        "siera": pitch.siera,
        "k_bb_pct": pitch.k_bb_pct,
        "war": pitch.war,
    }


def _stat_dict_from_statcast(sc: StatcastSummary | None) -> dict[str, float | None]:
    if not sc:
        return {}
    return {
        "pa": sc.pa,
        "avg_exit_velo": sc.avg_exit_velo,
        "max_exit_velo": sc.max_exit_velo,
        "barrel_pct": sc.barrel_pct,
        "hard_hit_pct": sc.hard_hit_pct,
        "xba": sc.xba,
        "xslg": sc.xslg,
        "xwoba": sc.xwoba,
        "sweet_spot_pct": sc.sweet_spot_pct,
        "sprint_speed": sc.sprint_speed,
        "whiff_pct": sc.whiff_pct,
        "chase_pct": sc.chase_pct,
    }


# ── Percentile calculation ──


async def _get_batting_distribution(
    session: AsyncSession, season: int
) -> dict[str, list[float]]:
    """Get sorted arrays of all qualified batter stats for percentile calculation."""
    cache_key = f"percentile_dist_batting:{season}"
    cached_val = cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    result = await session.execute(
        select(BattingStats).where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.pa >= 50,
        )
    )
    rows = result.scalars().all()

    dist: dict[str, list[float]] = {}
    for _, attr, _ in HITTER_BATTING_STATS:
        vals = sorted(v for r in rows if (v := getattr(r, attr, None)) is not None)
        if vals:
            dist[attr] = vals

    cache.set(cache_key, dist, expire=TTL_PERCENTILE)
    return dist


async def _get_pitching_distribution(
    session: AsyncSession, season: int
) -> dict[str, list[float]]:
    """Get sorted arrays of all qualified pitcher stats."""
    cache_key = f"percentile_dist_pitching:{season}"
    cached_val = cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    result = await session.execute(
        select(PitchingStats).where(
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.ip >= 20,
        )
    )
    rows = result.scalars().all()

    dist: dict[str, list[float]] = {}
    for _, attr, _ in PITCHER_STATS:
        vals = sorted(v for r in rows if (v := getattr(r, attr, None)) is not None)
        if vals:
            dist[attr] = vals

    cache.set(cache_key, dist, expire=TTL_PERCENTILE)
    return dist


async def _get_statcast_distribution(
    session: AsyncSession, season: int, player_type: str
) -> dict[str, list[float]]:
    """Get sorted arrays of statcast stats for percentile calculation."""
    cache_key = f"percentile_dist_statcast_{player_type}:{season}"
    cached_val = cache.get(cache_key)
    if cached_val is not None:
        return cached_val

    min_pa = 50 if player_type == "batter" else 20
    result = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
            StatcastSummary.player_type == player_type,
            StatcastSummary.pa >= min_pa,
        )
    )
    rows = result.scalars().all()

    stats_defs = HITTER_STATCAST_STATS if player_type == "batter" else PITCHER_STATCAST_STATS
    dist: dict[str, list[float]] = {}
    for _, attr, _ in stats_defs:
        vals = sorted(v for r in rows if (v := getattr(r, attr, None)) is not None)
        if vals:
            dist[attr] = vals

    cache.set(cache_key, dist, expire=TTL_PERCENTILE)
    return dist


def _compute_percentile(
    value: float, distribution: list[float], lower_is_better: bool
) -> tuple[int, int, int]:
    """Compute percentile, rank, and total from a sorted distribution.

    Returns (percentile 0-100, rank, total).
    """
    total = len(distribution)
    if total == 0:
        return (50, 0, 0)

    rank = bisect.bisect_left(distribution, value)

    if lower_is_better:
        # Lower value = higher percentile
        percentile = round(((total - rank) / total) * 100)
    else:
        # Higher value = higher percentile
        percentile = round((rank / total) * 100)

    percentile = max(0, min(100, percentile))
    display_rank = total - rank if lower_is_better else rank + 1
    return (percentile, display_rank, total)


def percentile_color(pct: int) -> str:
    """Return the color hex for a given percentile (Baseball Savant style)."""
    if pct <= 10:
        return "#1a3a6b"
    if pct <= 30:
        return "#3b6cb5"
    if pct <= 50:
        return "#89b4e8"
    if pct <= 70:
        return "#e88989"
    if pct <= 90:
        return "#c53030"
    return "#8b1a1a"


async def calculate_percentiles(
    session: AsyncSession,
    player_id: int,
    season: int,
    batting_stats: BattingStats | None = None,
    pitching_stats: PitchingStats | None = None,
    statcast_bat: StatcastSummary | None = None,
    statcast_pitch: StatcastSummary | None = None,
    batting_dist: dict | None = None,
    pitching_dist: dict | None = None,
    statcast_bat_dist: dict | None = None,
    statcast_pitch_dist: dict | None = None,
) -> list[StatPercentile]:
    """Calculate percentile ranks vs all qualified players.

    Accepts pre-fetched stats and distributions to avoid redundant queries
    when calculating for multiple players.
    """
    percentiles: list[StatPercentile] = []

    # Hitter batting percentiles
    if batting_stats and batting_stats.pa and batting_stats.pa >= 50:
        if batting_dist is None:
            batting_dist = await _get_batting_distribution(session, season)
        for display_name, attr, lower in HITTER_BATTING_STATS:
            val = getattr(batting_stats, attr, None)
            if val is not None and attr in batting_dist:
                pct, rank, total = _compute_percentile(val, batting_dist[attr], lower)
                percentiles.append(
                    StatPercentile(
                        stat_name=attr,
                        display_name=display_name,
                        value=round(val, 3) if isinstance(val, float) else val,
                        percentile=pct,
                        rank=rank,
                        total_qualified=total,
                        lower_is_better=lower,
                    )
                )

    # Hitter statcast percentiles
    if statcast_bat and statcast_bat.pa and statcast_bat.pa >= 50:
        if statcast_bat_dist is None:
            statcast_bat_dist = await _get_statcast_distribution(session, season, "batter")
        for display_name, attr, lower in HITTER_STATCAST_STATS:
            val = getattr(statcast_bat, attr, None)
            if val is not None and attr in statcast_bat_dist:
                pct, rank, total = _compute_percentile(val, statcast_bat_dist[attr], lower)
                percentiles.append(
                    StatPercentile(
                        stat_name=attr,
                        display_name=display_name,
                        value=round(val, 3) if isinstance(val, float) else val,
                        percentile=pct,
                        rank=rank,
                        total_qualified=total,
                        lower_is_better=lower,
                    )
                )

    # Pitcher percentiles
    if pitching_stats and pitching_stats.ip and pitching_stats.ip >= 20:
        if pitching_dist is None:
            pitching_dist = await _get_pitching_distribution(session, season)
        for display_name, attr, lower in PITCHER_STATS:
            val = getattr(pitching_stats, attr, None)
            if val is not None and attr in pitching_dist:
                pct, rank, total = _compute_percentile(val, pitching_dist[attr], lower)
                percentiles.append(
                    StatPercentile(
                        stat_name=attr,
                        display_name=display_name,
                        value=round(val, 3) if isinstance(val, float) else val,
                        percentile=pct,
                        rank=rank,
                        total_qualified=total,
                        lower_is_better=lower,
                    )
                )

    # Pitcher statcast percentiles
    if statcast_pitch and statcast_pitch.pa and statcast_pitch.pa >= 20:
        if statcast_pitch_dist is None:
            statcast_pitch_dist = await _get_statcast_distribution(
                session, season, "pitcher"
            )
        for display_name, attr, lower in PITCHER_STATCAST_STATS:
            val = getattr(statcast_pitch, attr, None)
            if val is not None and attr in statcast_pitch_dist:
                pct, rank, total = _compute_percentile(
                    val, statcast_pitch_dist[attr], lower
                )
                percentiles.append(
                    StatPercentile(
                        stat_name=attr,
                        display_name=display_name,
                        value=round(val, 3) if isinstance(val, float) else val,
                        percentile=pct,
                        rank=rank,
                        total_qualified=total,
                        lower_is_better=lower,
                    )
                )

    return percentiles


def _build_rolling(profile) -> dict[str, list[float | None]]:
    """Extract sparkline data from period-based stats.

    Returns stat_name -> [full_season, last_30, last_14, last_7] values.
    """
    rolling: dict[str, list[float | None]] = {}
    periods = ["full_season", "last_30", "last_14", "last_7"]

    if profile.is_hitter:
        for stat in ("avg", "obp", "slg", "ops", "woba", "wrc_plus", "iso", "hr", "sb"):
            rolling[stat] = [
                getattr(profile.batting_stats.get(p), stat, None) for p in periods
            ]

    if profile.is_pitcher:
        for stat in ("era", "fip", "whip", "k_per_9", "bb_per_9"):
            rolling[stat] = [
                getattr(profile.pitching_stats.get(p), stat, None) for p in periods
            ]

    # Statcast rolling (only 3 periods available)
    sc_periods = ["full_season", "last_30", "last_14"]
    sc_src = profile.statcast_bat if profile.is_hitter else profile.statcast_pitch
    if sc_src:
        for stat in ("xba", "xslg", "xwoba", "barrel_pct", "hard_hit_pct", "avg_exit_velo"):
            rolling[stat] = [getattr(sc_src.get(p), stat, None) for p in sc_periods]

    return rolling


async def get_player_card(
    session: AsyncSession,
    player_id: int,
    season: int,
    *,
    batting_dist: dict | None = None,
    pitching_dist: dict | None = None,
    statcast_bat_dist: dict | None = None,
    statcast_pitch_dist: dict | None = None,
) -> PlayerCard | None:
    """Assemble a rich player card for the comparison tool.

    Accepts pre-built distributions for batch efficiency.
    """
    profile = await get_player_profile(session, player_id, season)
    if not profile:
        return None

    player = profile.player
    player_type = "hitter" if profile.is_hitter else "pitcher"
    if profile.is_hitter and profile.is_pitcher:
        player_type = "two_way"

    # Build traditional stats by period
    traditional: dict[str, dict] = {}
    for period in ("full_season", "last_30", "last_14", "last_7"):
        bat_dict = _stat_dict_from_batting(profile.batting_stats.get(period))
        pitch_dict = _stat_dict_from_pitching(profile.pitching_stats.get(period))
        merged = {**bat_dict, **pitch_dict} if bat_dict or pitch_dict else {}
        if merged:
            traditional[period] = merged

    # Build statcast by period
    statcast: dict[str, dict] = {}
    for period in ("full_season", "last_30", "last_14"):
        sc_bat = _stat_dict_from_statcast(profile.statcast_bat.get(period))
        sc_pitch = _stat_dict_from_statcast(profile.statcast_pitch.get(period))
        merged = {**sc_bat, **sc_pitch} if sc_bat or sc_pitch else {}
        if merged:
            statcast[period] = merged

    # Percentiles
    percentiles = await calculate_percentiles(
        session,
        player_id,
        season,
        batting_stats=profile.batting_stats.get("full_season"),
        pitching_stats=profile.pitching_stats.get("full_season"),
        statcast_bat=profile.statcast_bat.get("full_season"),
        statcast_pitch=profile.statcast_pitch.get("full_season"),
        batting_dist=batting_dist,
        pitching_dist=pitching_dist,
        statcast_bat_dist=statcast_bat_dist,
        statcast_pitch_dist=statcast_pitch_dist,
    )

    # Splits (on-demand fetch)
    from app.services.splits_service import get_splits

    splits = await get_splits(session, player_id, season)

    # Fantasy value
    fantasy_value = {}
    if profile.trade_value:
        tv = profile.trade_value
        fantasy_value = {
            "surplus_value": tv.surplus_value,
            "positional_rank": tv.positional_rank,
            "z_score_total": tv.z_score_total,
        }

    # Gaps
    gaps = {}
    if profile.gaps:
        g = profile.gaps
        gaps = {
            "xba_vs_avg": g.xba_vs_avg,
            "xslg_vs_slg": g.xslg_vs_slg,
            "xwoba_vs_woba": g.xwoba_vs_woba,
            "fip_vs_era": g.fip_vs_era,
            "composite_score": g.composite_score,
            "signal": g.signal,
        }

    # Rolling trend data
    rolling = _build_rolling(profile)

    return PlayerCard(
        player={
            "id": player.id,
            "name": player.name,
            "team": player.team,
            "position": player.position,
            "headshot_url": _headshot_url(player.mlbam_id),
            "mlbam_id": player.mlbam_id,
            "player_type": player_type,
        },
        traditional=traditional,
        statcast=statcast,
        percentiles=percentiles,
        projections=profile.projections,
        fantasy_value=fantasy_value,
        gaps=gaps,
        splits=splits,
        rolling=rolling,
    )


async def get_player_cards_batch(
    session: AsyncSession, player_ids: list[int], season: int
) -> list[dict]:
    """Fetch multiple player cards efficiently, sharing distributions.

    Max 5 players.
    """
    player_ids = player_ids[:5]

    # Pre-fetch distributions once for all players
    batting_dist = await _get_batting_distribution(session, season)
    pitching_dist = await _get_pitching_distribution(session, season)
    statcast_bat_dist = await _get_statcast_distribution(session, season, "batter")
    statcast_pitch_dist = await _get_statcast_distribution(session, season, "pitcher")

    cards = []
    for pid in player_ids:
        card = await get_player_card(
            session,
            pid,
            season,
            batting_dist=batting_dist,
            pitching_dist=pitching_dist,
            statcast_bat_dist=statcast_bat_dist,
            statcast_pitch_dist=statcast_pitch_dist,
        )
        if card:
            cards.append(card.to_dict())

    return cards


async def search_players_json(
    session: AsyncSession, query: str, position: str | None = None, limit: int = 10
) -> list[dict]:
    """JSON player search for comparison autocomplete."""
    stmt = select(Player).where(Player.name.ilike(f"%{query}%"))
    if position:
        stmt = stmt.where(Player.position.ilike(f"%{position}%"))
    stmt = stmt.order_by(Player.name).limit(limit)

    result = await session.execute(stmt)
    players = result.scalars().all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "team": p.team,
            "position": p.position,
            "headshot_url": _headshot_url(p.mlbam_id),
        }
        for p in players
    ]


async def get_stat_leaders(
    session: AsyncSession,
    stat: str,
    season: int,
    position: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Return top players for a given stat."""
    # Determine which model the stat belongs to
    batting_attrs = {a for _, a, _ in HITTER_BATTING_STATS}
    pitching_attrs = {a for _, a, _ in PITCHER_STATS}
    statcast_attrs = {a for _, a, _ in HITTER_STATCAST_STATS + PITCHER_STATCAST_STATS}

    # Check if stat is lower-is-better
    lower_stats = set()
    all_stats = (
        HITTER_BATTING_STATS + PITCHER_STATS
        + HITTER_STATCAST_STATS + PITCHER_STATCAST_STATS
    )
    for _, attr, lower in all_stats:
        if lower:
            lower_stats.add(attr)

    if stat in batting_attrs:
        return await _batting_leaders(session, stat, season, position, limit, stat in lower_stats)
    elif stat in pitching_attrs:
        return await _pitching_leaders(session, stat, season, position, limit, stat in lower_stats)
    elif stat in statcast_attrs:
        return await _statcast_leaders(session, stat, season, position, limit, stat in lower_stats)

    return []


async def _batting_leaders(
    session: AsyncSession,
    stat: str,
    season: int,
    position: str | None,
    limit: int,
    ascending: bool,
) -> list[dict]:
    col = getattr(BattingStats, stat)
    stmt = (
        select(BattingStats, Player)
        .join(Player)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.pa >= 50,
            col.isnot(None),
        )
    )
    if position:
        stmt = stmt.where(Player.position.ilike(f"%{position}%"))
    stmt = stmt.order_by(col.asc() if ascending else col.desc()).limit(limit)

    result = await session.execute(stmt)
    return [
        {
            "player_id": p.id,
            "name": p.name,
            "team": p.team,
            "position": p.position,
            "value": getattr(b, stat),
            "headshot_url": _headshot_url(p.mlbam_id),
        }
        for b, p in result.all()
    ]


async def _pitching_leaders(
    session: AsyncSession,
    stat: str,
    season: int,
    position: str | None,
    limit: int,
    ascending: bool,
) -> list[dict]:
    col = getattr(PitchingStats, stat)
    stmt = (
        select(PitchingStats, Player)
        .join(Player)
        .where(
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.ip >= 20,
            col.isnot(None),
        )
    )
    if position:
        stmt = stmt.where(Player.position.ilike(f"%{position}%"))
    stmt = stmt.order_by(col.asc() if ascending else col.desc()).limit(limit)

    result = await session.execute(stmt)
    return [
        {
            "player_id": p.id,
            "name": p.name,
            "team": p.team,
            "position": p.position,
            "value": getattr(pt, stat),
            "headshot_url": _headshot_url(p.mlbam_id),
        }
        for pt, p in result.all()
    ]


async def _statcast_leaders(
    session: AsyncSession,
    stat: str,
    season: int,
    position: str | None,
    limit: int,
    ascending: bool,
) -> list[dict]:
    col = getattr(StatcastSummary, stat)
    stmt = (
        select(StatcastSummary, Player)
        .join(Player)
        .where(
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
            col.isnot(None),
        )
    )
    if position:
        stmt = stmt.where(Player.position.ilike(f"%{position}%"))
    stmt = stmt.order_by(col.asc() if ascending else col.desc()).limit(limit)

    result = await session.execute(stmt)
    return [
        {
            "player_id": p.id,
            "name": p.name,
            "team": p.team,
            "position": p.position,
            "value": getattr(sc, stat),
            "headshot_url": _headshot_url(p.mlbam_id),
        }
        for sc, p in result.all()
    ]
