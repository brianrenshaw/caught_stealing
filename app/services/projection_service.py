"""Rest-of-season projection engine.

Blends traditional stats with Statcast expected stats to produce
weighted projections for fantasy-relevant categories.

Weight system (configurable):
  - Full season traditional stats: 25%
  - Last 30 day traditional stats: 15%
  - Last 14 day traditional stats: 10%
  - Full season Statcast expected stats (xBA, xSLG, xwOBA): 30%
  - Last 30 day Statcast expected stats: 20%
"""

import logging
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.projection import Projection
from app.models.statcast_summary import StatcastSummary

logger = logging.getLogger(__name__)

# Total games in an MLB season
TOTAL_GAMES = 162

# Minimum thresholds for inclusion
MIN_PA_HITTERS = 50
MIN_IP_PITCHERS = 20.0

# Projection weights
WEIGHTS = {
    "full_season_trad": 0.25,
    "last_30_trad": 0.15,
    "last_14_trad": 0.10,
    "full_season_statcast": 0.30,
    "last_30_statcast": 0.20,
}

# Buy/sell signal threshold (xwOBA delta)
SIGNAL_THRESHOLD = 0.030


@dataclass
class HitterProjection:
    player_id: int
    player_name: str
    team: str | None
    position: str | None
    projected_hr: float = 0.0
    projected_r: float = 0.0
    projected_rbi: float = 0.0
    projected_sb: float = 0.0
    projected_avg: float = 0.0
    projected_obp: float = 0.0
    projected_slg: float = 0.0
    projected_ops: float = 0.0
    confidence_score: float = 0.0
    buy_low_signal: bool = False
    sell_high_signal: bool = False
    xwoba_delta: float = 0.0
    actual_woba: float | None = None
    xwoba: float | None = None


@dataclass
class PitcherProjection:
    player_id: int
    player_name: str
    team: str | None
    position: str | None
    projected_w: float = 0.0
    projected_sv: float = 0.0
    projected_k: float = 0.0
    projected_era: float = 0.0
    projected_whip: float = 0.0
    confidence_score: float = 0.0
    buy_low_signal: bool = False
    sell_high_signal: bool = False
    xwoba_delta: float = 0.0


def _weighted_avg(values: list[tuple[float | None, float]]) -> float | None:
    """Calculate weighted average, skipping None values and renormalizing weights."""
    valid = [(v, w) for v, w in values if v is not None]
    if not valid:
        return None
    total_weight = sum(w for _, w in valid)
    if total_weight == 0:
        return None
    return sum(v * w for v, w in valid) / total_weight


def _calc_confidence(pa: float | None, has_statcast: bool, season_progress: float) -> float:
    """Calculate confidence score (0-1) based on sample size and data availability."""
    if pa is None or pa == 0:
        return 0.1
    # PA contribution: ramps from 0.2 at 50 PA to 0.6 at 400+ PA
    pa_factor = min(float(pa) / 400, 1.0) * 0.6
    # Statcast availability adds confidence
    sc_factor = 0.2 if has_statcast else 0.0
    # Season progress adds confidence (more games = more reliable)
    season_factor = season_progress * 0.2
    return min(pa_factor + sc_factor + season_factor, 1.0)


async def _get_batting_stats(
    session: AsyncSession, player_id: int, season: int
) -> dict[str, BattingStats | None]:
    """Fetch batting stats for all periods."""
    result = {}
    for period in ("full_season", "last_30", "last_14"):
        query = select(BattingStats).where(
            BattingStats.player_id == player_id,
            BattingStats.season == season,
            BattingStats.period == period,
        )
        res = await session.execute(query)
        result[period] = res.scalar_one_or_none()
    return result


async def _get_pitching_stats(
    session: AsyncSession, player_id: int, season: int
) -> dict[str, PitchingStats | None]:
    result = {}
    for period in ("full_season", "last_30", "last_14"):
        query = select(PitchingStats).where(
            PitchingStats.player_id == player_id,
            PitchingStats.season == season,
            PitchingStats.period == period,
        )
        res = await session.execute(query)
        result[period] = res.scalar_one_or_none()
    return result


async def _get_statcast(
    session: AsyncSession, player_id: int, season: int, player_type: str
) -> dict[str, StatcastSummary | None]:
    result = {}
    for period in ("full_season", "last_30"):
        query = select(StatcastSummary).where(
            StatcastSummary.player_id == player_id,
            StatcastSummary.season == season,
            StatcastSummary.period == period,
            StatcastSummary.player_type == player_type,
        )
        res = await session.execute(query)
        result[period] = res.scalar_one_or_none()
    return result


def _estimate_remaining_pa(full_stats: BattingStats | None) -> float:
    """Estimate remaining plate appearances for the season."""
    if not full_stats or not full_stats.pa or full_stats.pa == 0:
        return 300.0  # default estimate for a full-time player
    # Estimate games played from PA (avg ~4.5 PA/game for a full-time player)
    games_played = full_stats.pa / 4.5
    if games_played == 0:
        return 300.0
    remaining_games = max(TOTAL_GAMES - games_played, 0)
    pa_per_game = full_stats.pa / games_played
    return remaining_games * pa_per_game


def _estimate_remaining_ip(full_stats: PitchingStats | None) -> float:
    """Estimate remaining innings pitched for the season."""
    if not full_stats or not full_stats.ip or full_stats.ip == 0:
        return 100.0
    # Estimate games started/appeared
    gs = full_stats.gs or 0
    g = full_stats.g or 1
    # For starters: ~6 IP/start, ~32 starts/season
    # For relievers: ~1 IP/appearance, ~65 appearances/season
    if gs > 0 and gs >= g * 0.5:  # starter
        starts_so_far = gs
        ip_per_start = full_stats.ip / max(starts_so_far, 1)
        total_starts = 32
        remaining_starts = max(total_starts - starts_so_far, 0)
        return remaining_starts * ip_per_start
    else:  # reliever
        ip_per_app = full_stats.ip / max(g, 1)
        total_apps = 65
        remaining_apps = max(total_apps - g, 0)
        return remaining_apps * ip_per_app


async def project_hitter(
    session: AsyncSession, player: Player, season: int
) -> HitterProjection | None:
    """Generate a rest-of-season projection for a single hitter."""
    batting = await _get_batting_stats(session, player.id, season)
    statcast = await _get_statcast(session, player.id, season, "batter")

    full = batting.get("full_season")
    if not full or not full.pa or full.pa < MIN_PA_HITTERS:
        return None

    l30 = batting.get("last_30")
    l14 = batting.get("last_14")
    sc_full = statcast.get("full_season")
    sc_30 = statcast.get("last_30")

    remaining_pa = _estimate_remaining_pa(full)

    # Project counting stats using per-PA rates
    def _project_counting(stat_name: str) -> float:
        full_val = getattr(full, stat_name, None) if full else None
        l30_val = getattr(l30, stat_name, None) if l30 else None
        l14_val = getattr(l14, stat_name, None) if l14 else None

        # Convert to per-PA rates
        full_rate = full_val / full.pa if full_val and full.pa else None
        l30_rate = l30_val / l30.pa if l30_val and l30 and l30.pa else None
        l14_rate = l14_val / l14.pa if l14_val and l14 and l14.pa else None

        blended_rate = _weighted_avg(
            [
                (full_rate, WEIGHTS["full_season_trad"]),
                (l30_rate, WEIGHTS["last_30_trad"]),
                (l14_rate, WEIGHTS["last_14_trad"]),
            ]
        )

        if blended_rate is None:
            return 0.0

        # Already accumulated + projected remaining
        already = full_val or 0
        return already + blended_rate * remaining_pa

    # Project rate stats by blending traditional and Statcast expected
    def _project_rate(trad_name: str, xstat_name: str | None = None) -> float:
        full_val = getattr(full, trad_name, None) if full else None
        l30_val = getattr(l30, trad_name, None) if l30 else None
        l14_val = getattr(l14, trad_name, None) if l14 else None
        sc_full_val = getattr(sc_full, xstat_name, None) if sc_full and xstat_name else None
        sc_30_val = getattr(sc_30, xstat_name, None) if sc_30 and xstat_name else None

        result = _weighted_avg(
            [
                (full_val, WEIGHTS["full_season_trad"]),
                (l30_val, WEIGHTS["last_30_trad"]),
                (l14_val, WEIGHTS["last_14_trad"]),
                (sc_full_val, WEIGHTS["full_season_statcast"]),
                (sc_30_val, WEIGHTS["last_30_statcast"]),
            ]
        )
        return result or 0.0

    # Buy/sell signal based on xwOBA vs actual wOBA
    actual_woba = full.woba if full else None
    xwoba_val = sc_full.xwoba if sc_full else None
    xwoba_delta = 0.0
    buy_low = False
    sell_high = False
    if actual_woba and xwoba_val:
        xwoba_delta = xwoba_val - actual_woba
        buy_low = xwoba_delta >= SIGNAL_THRESHOLD
        sell_high = xwoba_delta <= -SIGNAL_THRESHOLD

    games_played = (full.pa or 0) / 4.5
    season_progress = min(games_played / TOTAL_GAMES, 1.0)

    return HitterProjection(
        player_id=player.id,
        player_name=player.name,
        team=player.team,
        position=player.position,
        projected_hr=round(_project_counting("hr"), 1),
        projected_r=round(_project_counting("r"), 1),
        projected_rbi=round(_project_counting("rbi"), 1),
        projected_sb=round(_project_counting("sb"), 1),
        projected_avg=round(_project_rate("avg", "xba"), 3),
        projected_obp=round(_project_rate("obp"), 3),
        projected_slg=round(_project_rate("slg", "xslg"), 3),
        projected_ops=round(_project_rate("ops"), 3),
        confidence_score=round(_calc_confidence(full.pa, sc_full is not None, season_progress), 2),
        buy_low_signal=buy_low,
        sell_high_signal=sell_high,
        xwoba_delta=round(xwoba_delta, 3),
        actual_woba=round(actual_woba, 3) if actual_woba else None,
        xwoba=round(xwoba_val, 3) if xwoba_val else None,
    )


async def project_pitcher(
    session: AsyncSession, player: Player, season: int
) -> PitcherProjection | None:
    """Generate a rest-of-season projection for a single pitcher."""
    pitching = await _get_pitching_stats(session, player.id, season)
    statcast = await _get_statcast(session, player.id, season, "pitcher")

    full = pitching.get("full_season")
    if not full or not full.ip or full.ip < MIN_IP_PITCHERS:
        return None

    l30 = pitching.get("last_30")
    l14 = pitching.get("last_14")
    sc_full = statcast.get("full_season")
    remaining_ip = _estimate_remaining_ip(full)

    # Project wins from win rate
    full_w_rate = (full.w or 0) / max(full.ip or 1, 1) * 9
    l30_w_rate = ((l30.w or 0) / max(l30.ip or 1, 1) * 9) if l30 and l30.ip else None
    proj_w_rate = (
        _weighted_avg(
            [
                (full_w_rate, 0.6),
                (l30_w_rate, 0.4),
            ]
        )
        or full_w_rate
    )
    projected_w = (full.w or 0) + proj_w_rate * remaining_ip / 9

    # Project saves (only for pitchers who have saves)
    full_sv = full.sv or 0
    projected_sv = 0.0
    if full_sv > 0 and full.g:
        sv_rate = full_sv / full.g
        remaining_apps = max(65 - full.g, 0)
        projected_sv = full_sv + sv_rate * remaining_apps

    # Project strikeouts from K/9 rate
    k9_values = [
        (full.k_per_9, WEIGHTS["full_season_trad"]),
        (l30.k_per_9 if l30 else None, WEIGHTS["last_30_trad"]),
        (l14.k_per_9 if l14 else None, WEIGHTS["last_14_trad"]),
    ]
    proj_k9 = _weighted_avg(k9_values) or (full.k_per_9 or 0)
    projected_k = (full.so or 0) + proj_k9 * remaining_ip / 9

    # Project ERA: weight FIP/xFIP more heavily than actual ERA
    # FIP and xFIP are better predictors of future ERA than ERA itself
    era_values = [
        (full.era, 0.15),
        (full.fip, 0.25),
        (full.xfip, 0.25),
        (l30.era if l30 else None, 0.10),
        (l30.fip if l30 else None, 0.10),
        (l14.era if l14 else None, 0.05),
    ]
    # Add Statcast xwOBA-against as ERA proxy if available
    # Higher xwOBA-against correlates with higher ERA
    projected_era = _weighted_avg(era_values) or (full.era or 0)

    # Project WHIP
    whip_values = [
        (full.whip, WEIGHTS["full_season_trad"]),
        (l30.whip if l30 else None, WEIGHTS["last_30_trad"]),
        (l14.whip if l14 else None, WEIGHTS["last_14_trad"]),
    ]
    projected_whip = _weighted_avg(whip_values) or (full.whip or 0)

    # Buy/sell for pitchers: compare xwOBA-against to actual wOBA-against
    xwoba_against = sc_full.xwoba if sc_full else None
    # For pitchers, lower xwOBA is better. A positive delta means
    # opponents are underperforming their batted ball quality against this pitcher.
    xwoba_delta = 0.0
    buy_low = False
    sell_high = False
    if xwoba_against is not None and full.whip is not None:
        # Use a rough wOBA-against estimate from WHIP if we don't have direct wOBA
        # This is approximate; if we had direct wOBA-against we'd use it
        xwoba_delta = 0.0  # Simplified: leave neutral if we can't compare directly

    games_played_equiv = (full.ip or 0) / 6 if full.gs and full.gs > 0 else (full.ip or 0)
    season_progress = min(games_played_equiv / TOTAL_GAMES, 1.0)

    return PitcherProjection(
        player_id=player.id,
        player_name=player.name,
        team=player.team,
        position=player.position,
        projected_w=round(projected_w, 1),
        projected_sv=round(projected_sv, 1),
        projected_k=round(projected_k, 1),
        projected_era=round(projected_era, 2),
        projected_whip=round(projected_whip, 2),
        confidence_score=round(
            _calc_confidence(full.ip * 3, sc_full is not None, season_progress), 2
        ),
        buy_low_signal=buy_low,
        sell_high_signal=sell_high,
        xwoba_delta=round(xwoba_delta, 3),
    )


async def project_all_hitters(session: AsyncSession, season: int) -> list[HitterProjection]:
    """Project all qualified hitters."""
    # Find all players who have full-season batting stats with enough PA
    result = await session.execute(
        select(Player)
        .join(BattingStats)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.pa >= MIN_PA_HITTERS,
        )
        .distinct()
    )
    players = result.scalars().all()

    projections = []
    for player in players:
        proj = await project_hitter(session, player, season)
        if proj:
            projections.append(proj)

    logger.info(f"Generated {len(projections)} hitter projections for {season}")
    return projections


async def project_all_pitchers(session: AsyncSession, season: int) -> list[PitcherProjection]:
    """Project all qualified pitchers."""
    result = await session.execute(
        select(Player)
        .join(PitchingStats)
        .where(
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.ip >= MIN_IP_PITCHERS,
        )
        .distinct()
    )
    players = result.scalars().all()

    projections = []
    for player in players:
        proj = await project_pitcher(session, player, season)
        if proj:
            projections.append(proj)

    logger.info(f"Generated {len(projections)} pitcher projections for {season}")
    return projections


async def store_projections(
    session: AsyncSession,
    hitter_projs: list[HitterProjection],
    pitcher_projs: list[PitcherProjection],
    season: int,
) -> int:
    """Store projections in the database, replacing existing 'blended' system entries."""
    from sqlalchemy import delete

    # Clear existing blended projections for this season
    await session.execute(
        delete(Projection).where(
            Projection.season == season,
            Projection.system == "blended",
        )
    )

    count = 0
    for proj in hitter_projs:
        stats_map = {
            "HR": proj.projected_hr,
            "R": proj.projected_r,
            "RBI": proj.projected_rbi,
            "SB": proj.projected_sb,
            "AVG": proj.projected_avg,
            "OBP": proj.projected_obp,
            "SLG": proj.projected_slg,
            "OPS": proj.projected_ops,
            "confidence": proj.confidence_score,
            "xwoba_delta": proj.xwoba_delta,
        }
        for stat_name, value in stats_map.items():
            session.add(
                Projection(
                    player_id=proj.player_id,
                    season=season,
                    system="blended",
                    stat_name=stat_name,
                    projected_value=value,
                )
            )
            count += 1

    for proj in pitcher_projs:
        stats_map = {
            "W": proj.projected_w,
            "SV": proj.projected_sv,
            "K": proj.projected_k,
            "ERA": proj.projected_era,
            "WHIP": proj.projected_whip,
            "confidence": proj.confidence_score,
            "xwoba_delta": proj.xwoba_delta,
        }
        for stat_name, value in stats_map.items():
            session.add(
                Projection(
                    player_id=proj.player_id,
                    season=season,
                    system="blended",
                    stat_name=stat_name,
                    projected_value=value,
                )
            )
            count += 1

    await session.flush()
    logger.info(f"Stored {count} projection entries for {season}")
    return count


# ── Multi-System Projection Blending ──


@dataclass
class BlendConfig:
    """Weights for blending external projection systems."""

    steamer: float = 0.30
    zips: float = 0.25
    atc: float = 0.25
    thebat: float = 0.20

    def normalize(self) -> "BlendConfig":
        total = self.steamer + self.zips + self.atc + self.thebat
        if total == 0:
            return BlendConfig()
        return BlendConfig(
            steamer=self.steamer / total,
            zips=self.zips / total,
            atc=self.atc / total,
            thebat=self.thebat / total,
        )

    def weights_dict(self) -> dict[str, float]:
        return {
            "steamer": self.steamer,
            "zips": self.zips,
            "atc": self.atc,
            "thebat": self.thebat,
        }


async def get_projections_comparison(
    session: AsyncSession, player_id: int, season: int
) -> dict[str, dict[str, float]]:
    """Get all projection systems for a player, organized by system.

    Returns: {"steamer": {"HR": 25, "R": 80, ...}, "zips": {...}, "blended": {...}}
    """
    result = await session.execute(
        select(Projection).where(
            Projection.player_id == player_id,
            Projection.season == season,
        )
    )
    systems: dict[str, dict[str, float]] = defaultdict(dict)
    for proj in result.scalars().all():
        systems[proj.system][proj.stat_name] = proj.projected_value
    return dict(systems)


async def blend_external_projections(
    session: AsyncSession,
    player_id: int,
    season: int,
    config: BlendConfig | None = None,
) -> dict[str, float]:
    """Blend projections from multiple external systems using configurable weights.

    Returns blended stat values as a dict.
    """
    if config is None:
        config = BlendConfig()
    config = config.normalize()
    weights = config.weights_dict()

    systems = await get_projections_comparison(session, player_id, season)

    # Collect all stat names across systems (excluding metadata like 'confidence')
    all_stats: set[str] = set()
    for sys_stats in systems.values():
        all_stats.update(sys_stats.keys())
    all_stats -= {"confidence", "xwoba_delta"}

    blended = {}
    for stat in all_stats:
        values = []
        for sys_name, weight in weights.items():
            if sys_name in systems and stat in systems[sys_name]:
                values.append((systems[sys_name][stat], weight))
        if values:
            total_weight = sum(w for _, w in values)
            if total_weight > 0:
                blended[stat] = round(sum(v * w for v, w in values) / total_weight, 3)

    return blended


async def compute_performance_gaps(session: AsyncSession, player_id: int, season: int) -> dict:
    """Compute gaps between expected and actual performance.

    Returns dict with individual gaps and composite score.
    """
    bat_result = await session.execute(
        select(BattingStats).where(
            BattingStats.player_id == player_id,
            BattingStats.season == season,
            BattingStats.period == "full_season",
        )
    )
    bat = bat_result.scalar_one_or_none()

    sc_result = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == player_id,
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
            StatcastSummary.player_type == "batter",
        )
    )
    sc = sc_result.scalar_one_or_none()

    pitch_result = await session.execute(
        select(PitchingStats).where(
            PitchingStats.player_id == player_id,
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
        )
    )
    pitch = pitch_result.scalar_one_or_none()

    gaps = {
        "xba_vs_avg": None,
        "xslg_vs_slg": None,
        "xwoba_vs_woba": None,
        "fip_vs_era": None,
        "composite_score": 0.0,
        "signal": "neutral",
    }

    scores = []

    if bat and sc:
        if sc.xba is not None and bat.avg is not None:
            gaps["xba_vs_avg"] = round(sc.xba - bat.avg, 3)
            scores.append(gaps["xba_vs_avg"])
        if sc.xslg is not None and bat.slg is not None:
            gaps["xslg_vs_slg"] = round(sc.xslg - bat.slg, 3)
            scores.append(gaps["xslg_vs_slg"])
        if sc.xwoba is not None and bat.woba is not None:
            gaps["xwoba_vs_woba"] = round(sc.xwoba - bat.woba, 3)
            scores.append(gaps["xwoba_vs_woba"] * 2)

    if pitch:
        if pitch.fip is not None and pitch.era is not None:
            gaps["fip_vs_era"] = round(pitch.fip - pitch.era, 2)
            scores.append(gaps["fip_vs_era"])

    if scores:
        gaps["composite_score"] = round(sum(scores) / len(scores), 3)
        if gaps["composite_score"] >= 0.020:
            gaps["signal"] = "buy_low"
        elif gaps["composite_score"] <= -0.020:
            gaps["signal"] = "sell_high"

    return gaps


async def get_buy_sell_candidates(
    session: AsyncSession, season: int, limit: int = 20
) -> dict[str, list[dict]]:
    """Find top buy-low and sell-high candidates based on performance gaps.

    Returns {"buy_low": [...], "sell_high": [...]}
    """
    # Get all players with both batting stats and Statcast data
    result = await session.execute(
        select(Player, BattingStats, StatcastSummary)
        .join(BattingStats, BattingStats.player_id == Player.id)
        .join(StatcastSummary, StatcastSummary.player_id == Player.id)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.pa >= MIN_PA_HITTERS,
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
            StatcastSummary.player_type == "batter",
        )
    )

    candidates = []
    for player, bat, sc in result.all():
        if sc.xwoba is None or bat.woba is None:
            continue
        xwoba_delta = sc.xwoba - bat.woba
        composite = xwoba_delta
        if sc.xba is not None and bat.avg is not None:
            composite = (composite + (sc.xba - bat.avg)) / 2

        candidates.append(
            {
                "player_id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "xwoba_delta": round(xwoba_delta, 3),
                "composite_score": round(composite, 3),
                "actual_woba": round(bat.woba, 3),
                "xwoba": round(sc.xwoba, 3),
            }
        )

    # Sort by composite score
    buy_low = sorted(
        [c for c in candidates if c["composite_score"] > 0],
        key=lambda x: x["composite_score"],
        reverse=True,
    )[:limit]

    sell_high = sorted(
        [c for c in candidates if c["composite_score"] < 0],
        key=lambda x: x["composite_score"],
    )[:limit]

    return {"buy_low": buy_low, "sell_high": sell_high}
