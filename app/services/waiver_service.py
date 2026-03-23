"""Waiver wire recommendation engine for H2H Points league.

Scores free agents using a composite of:
  - Projected fantasy points (35%): ROS or weekly projected points
  - Recent performance trend (25%): last-14 Statcast metrics vs season
  - Positional need (15%): how much the position is needed (based on scarcity)
  - League scoring fit (15%): bonus for players who excel in this format
    (low-K hitters, high-SV/HLD relievers, innings-eating starters)
  - Schedule volume (10%): team games this week (weekly) or neutral (ROS)

Weekly mode adds: two-start pitcher detection, reliever role/opportunity,
opponent quality adjustments, Statcast breakout detection, and injury filtering.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.league_config import REPLACEMENT_LEVEL_SLOTS
from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.player_points import PlayerPoints
from app.models.statcast_summary import StatcastSummary
from app.services.mlb_service import InjuryEntry
from app.services.projection_service import project_hitter, project_pitcher

logger = logging.getLogger(__name__)

# Normalization constant for weekly projections (0-100 scale)
# ~80 pts is a strong hitter week over 7 games
WEEKLY_PROJECTION_MAX = 80.0


@dataclass
class WaiverRecommendation:
    player_id: int
    name: str
    team: str | None
    position: str | None
    waiver_score: float  # 0-100 composite score
    projection_score: float
    trend_score: float
    positional_need_score: float
    reasoning: str
    buy_low: bool = False
    xwoba_delta: float = 0.0
    trend: str = "stable"  # hot, cold, stable
    # Points league fields
    projected_points: float = 0.0
    points_per_pa: float | None = None
    points_per_ip: float | None = None
    scoring_fit_score: float = 0.0
    player_type: str = "hitter"
    # Weekly-specific fields
    projection_period: str = "ros"
    weekly_points: float = 0.0
    team_games: int = 0
    num_starts: int = 0
    # Reliever role context
    reliever_role: str | None = None  # closer, setup, middle, long
    save_opps_week: float = 0.0
    hold_opps_week: float = 0.0
    closer_vacancy: bool = False
    # Matchup quality
    matchup_quality: float = 50.0  # 0-100 (50 = neutral)
    matchup_detail: str = ""
    # Breakout detection
    breakout_signal: bool = False
    breakout_detail: str = ""
    # Injury status
    injury_status: str | None = None
    injury_source: str = "MLB Official Injury Report"
    # Two-start pitcher
    two_start: bool = False
    start_opponents: list[str] = field(default_factory=list)


async def _get_all_players(session: AsyncSession, season: int) -> list[Player]:
    """Get all qualified hitters and pitchers."""
    result = await session.execute(
        select(Player)
        .join(BattingStats)
        .where(
            BattingStats.season == season,
            BattingStats.period == "full_season",
            BattingStats.pa >= 20,
        )
        .distinct()
    )
    hitters = result.scalars().all()

    pitch_result = await session.execute(
        select(Player)
        .join(PitchingStats)
        .where(
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.ip >= 10,
        )
        .distinct()
    )
    pitchers = pitch_result.scalars().all()

    seen_ids: set[int] = set()
    all_players = []
    for p in list(hitters) + list(pitchers):
        if p.id not in seen_ids:
            seen_ids.add(p.id)
            all_players.append(p)
    return all_players


async def _get_max_pts(session: AsyncSession, season: int) -> float:
    """Get max projected ROS points for normalization."""
    max_pts_result = await session.execute(
        select(PlayerPoints.projected_ros_points)
        .where(
            PlayerPoints.season == season,
            PlayerPoints.period == "full_season",
        )
        .order_by(PlayerPoints.projected_ros_points.desc())
        .limit(1)
    )
    max_pts_row = max_pts_result.scalar_one_or_none()
    return max_pts_row if max_pts_row and max_pts_row > 0 else 400.0


async def _compute_trend(
    session: AsyncSession, player_id: int, season: int
) -> tuple[float, str, float, float, float]:
    """Compute trend score and breakout indicators from Statcast data.

    Returns: (trend_score, trend_label, xwoba_delta, barrel_delta, hard_hit_delta)
    """
    full_sc = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == player_id,
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
        )
    )
    full_sc_row = full_sc.scalar_one_or_none()

    recent_sc = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == player_id,
            StatcastSummary.season == season,
            StatcastSummary.period == "last_14",
        )
    )
    recent_sc_row = recent_sc.scalar_one_or_none()

    trend_score = 50.0
    trend = "stable"
    xwoba_delta = 0.0
    barrel_delta = 0.0
    hard_hit_delta = 0.0

    if full_sc_row and recent_sc_row:
        if full_sc_row.xwoba and recent_sc_row.xwoba:
            xwoba_delta = recent_sc_row.xwoba - full_sc_row.xwoba
            if xwoba_delta > 0.030:
                trend_score = 80.0
                trend = "hot"
            elif xwoba_delta > 0.015:
                trend_score = 65.0
                trend = "hot"
            elif xwoba_delta < -0.030:
                trend_score = 20.0
                trend = "cold"
            elif xwoba_delta < -0.015:
                trend_score = 35.0
                trend = "cold"

        if full_sc_row.barrel_pct is not None and recent_sc_row.barrel_pct is not None:
            barrel_delta = recent_sc_row.barrel_pct - full_sc_row.barrel_pct
        if full_sc_row.hard_hit_pct is not None and recent_sc_row.hard_hit_pct is not None:
            hard_hit_delta = recent_sc_row.hard_hit_pct - full_sc_row.hard_hit_pct

    return trend_score, trend, xwoba_delta, barrel_delta, hard_hit_delta


def _detect_breakout(
    xwoba_delta: float, barrel_delta: float, hard_hit_delta: float
) -> tuple[bool, str]:
    """Detect breakout candidates from Statcast trend deltas.

    Breakout = any two of: barrel% up 3+, hard-hit% up 5+, xwOBA up .030+
    """
    signals = []
    if barrel_delta >= 3.0:
        signals.append(f"Barrel% +{barrel_delta:.1f}%")
    if hard_hit_delta >= 5.0:
        signals.append(f"HardHit% +{hard_hit_delta:.1f}%")
    if xwoba_delta >= 0.030:
        signals.append(f"xwOBA +{xwoba_delta:.3f}")

    if len(signals) >= 2:
        return True, f"BREAKOUT: {', '.join(signals)} in last 14 days"
    return False, ""


def _compute_positional_scarcity(position: str | None) -> float:
    """Score positional scarcity for 10-team H2H league."""
    pos = (position or "UTIL").split(",")[0].strip()
    repl_slots = REPLACEMENT_LEVEL_SLOTS.get(pos, 10)
    if repl_slots <= 10:
        return 70.0  # C, 1B, 2B, 3B, SS
    elif repl_slots <= 20:
        return 60.0  # SP, RP
    elif repl_slots <= 30:
        return 40.0  # OF
    return 30.0


async def _compute_scoring_fit(
    session: AsyncSession,
    player: Player,
    player_type: str,
    season: int,
) -> tuple[float, list[str]]:
    """Compute league scoring fit bonus and reasons."""
    scoring_fit = 50.0
    reasons: list[str] = []

    if player_type == "hitter":
        bat_result = await session.execute(
            select(BattingStats).where(
                BattingStats.player_id == player.id,
                BattingStats.season == season,
                BattingStats.period == "full_season",
            )
        )
        bat = bat_result.scalar_one_or_none()
        if bat and bat.k_pct and bat.k_pct < 0.18:
            scoring_fit = 75.0
            reasons.append(f"Low K% ({bat.k_pct:.1%}) — premium in points format (K=-0.5)")
        elif bat and bat.bb_pct and bat.bb_pct > 0.10:
            scoring_fit = 65.0
            reasons.append(f"High BB% ({bat.bb_pct:.1%}) — walks are free points (BB=1)")
    else:
        pitch_result = await session.execute(
            select(PitchingStats).where(
                PitchingStats.player_id == player.id,
                PitchingStats.season == season,
                PitchingStats.period == "full_season",
            )
        )
        pitch = pitch_result.scalar_one_or_none()
        if pitch:
            if (pitch.sv or 0) > 0:
                scoring_fit = 85.0
                reasons.append(f"Closer with {int(pitch.sv)} SV — saves = 7 pts each")
            elif (pitch.hld or 0) > 0:
                scoring_fit = 75.0
                reasons.append(f"Setup man with {int(pitch.hld)} HLD — holds = 4 pts each")
            elif (pitch.gs or 0) > 0 and (pitch.ip or 0) / max(pitch.gs, 1) > 5.5:
                scoring_fit = 70.0
                avg_ip = (pitch.ip or 0) / max(pitch.gs, 1)
                reasons.append(
                    f"Innings eater ({avg_ip:.1f} IP/start) — each IP = 4.5 pts from outs"
                )

    return scoring_fit, reasons


async def score_free_agents(
    session: AsyncSession,
    season: int,
    limit: int = 30,
    injuries: list[InjuryEntry] | None = None,
) -> list[WaiverRecommendation]:
    """Score and rank available free agents for waiver wire pickup (ROS).

    Uses projected fantasy points from the player_points table as the
    primary scoring input, with league-specific scoring fit bonuses.
    """
    all_players = await _get_all_players(session, season)
    max_pts = await _get_max_pts(session, season)

    # Build injury lookup
    injury_lookup: dict[int, InjuryEntry] = {}
    if injuries:
        from app.services.mlb_service import build_injury_lookup

        injury_lookup = build_injury_lookup(injuries)

    recommendations: list[WaiverRecommendation] = []

    for player in all_players:
        pp_result = await session.execute(
            select(PlayerPoints).where(
                PlayerPoints.player_id == player.id,
                PlayerPoints.season == season,
                PlayerPoints.period == "full_season",
            )
        )
        pp = pp_result.scalar_one_or_none()

        proj = await project_hitter(session, player, season)
        player_type = "hitter"
        if not proj:
            proj = await project_pitcher(session, player, season)
            player_type = "pitcher"
        if not proj:
            continue

        # Projection score
        proj_pts = pp.projected_ros_points if pp else 0.0
        proj_score = min((proj_pts / max_pts) * 100, 100) if proj_pts > 0 else 0.0

        # Trend + breakout
        trend_score, trend, xwoba_delta, barrel_delta, hard_hit_delta = await _compute_trend(
            session, player.id, season
        )
        breakout, breakout_detail = _detect_breakout(xwoba_delta, barrel_delta, hard_hit_delta)
        if breakout:
            trend_score = min(trend_score + 15, 100)

        # Positional scarcity
        pos_score = _compute_positional_scarcity(player.position)

        # Scoring fit
        scoring_fit, reasons = await _compute_scoring_fit(session, player, player_type, season)

        # Injury status
        injury_status = None
        mlbam_id = int(player.mlbam_id) if player.mlbam_id else None
        if mlbam_id and mlbam_id in injury_lookup:
            entry = injury_lookup[mlbam_id]
            injury_status = f"{entry.status} - {entry.injury}"

        # Reasoning
        if trend == "hot":
            reasons.append("Recent Statcast metrics trending up")
        if breakout:
            reasons.append(breakout_detail)
        if hasattr(proj, "buy_low_signal") and proj.buy_low_signal:
            reasons.append(f"Buy low: xwOBA exceeds wOBA by {proj.xwoba_delta:+.3f}")
        if pos_score >= 70:
            pos = (player.position or "UTIL").split(",")[0].strip()
            reasons.append(f"Scarce position ({pos})")
        if proj_pts > 0:
            reasons.append(f"Projected {proj_pts:.0f} ROS points")
        if injury_status:
            reasons.append(f"⚠ {injury_status}")

        reasoning = "; ".join(reasons) if reasons else "Solid production"

        # Composite score
        composite = (
            proj_score * 0.35
            + trend_score * 0.25
            + pos_score * 0.15
            + scoring_fit * 0.15
            + 50.0 * 0.10  # schedule neutral for ROS
        )

        buy_low = getattr(proj, "buy_low_signal", False)
        xwoba_d = getattr(proj, "xwoba_delta", 0.0)

        recommendations.append(
            WaiverRecommendation(
                player_id=player.id,
                name=player.name,
                team=player.team,
                position=player.position,
                waiver_score=round(composite, 1),
                projection_score=round(proj_score, 1),
                trend_score=round(trend_score, 1),
                positional_need_score=round(pos_score, 1),
                reasoning=reasoning,
                buy_low=buy_low,
                xwoba_delta=xwoba_d,
                trend=trend,
                projected_points=round(proj_pts, 1) if proj_pts else 0.0,
                points_per_pa=pp.points_per_pa if pp else None,
                points_per_ip=pp.points_per_ip if pp else None,
                scoring_fit_score=round(scoring_fit, 1),
                player_type=player_type,
                projection_period="ros",
                breakout_signal=breakout,
                breakout_detail=breakout_detail,
                injury_status=injury_status,
            )
        )

    recommendations.sort(key=lambda r: r.waiver_score, reverse=True)
    return recommendations[:limit]


async def score_free_agents_weekly(
    session: AsyncSession,
    season: int,
    week_start: date,
    week_end: date,
    limit: int = 30,
    injuries: list[InjuryEntry] | None = None,
) -> list[WaiverRecommendation]:
    """Score and rank free agents for a specific week.

    Integrates: weekly volume projections, two-start pitcher detection,
    reliever role/opportunity, opponent quality adjustments, Statcast
    breakout detection, and injury filtering.
    """
    from app.services.mlb_service import build_injury_lookup
    from app.services.schedule_service import (
        get_all_team_games_in_range,
        get_game_details_in_range,
        get_probable_starters_in_range,
    )

    all_players = await _get_all_players(session, season)

    # Fetch schedule data
    team_games = await get_all_team_games_in_range(week_start, week_end)
    probable_starters = await get_probable_starters_in_range(week_start, week_end)
    game_details = await get_game_details_in_range(week_start, week_end)

    # Build injury lookup
    injury_lookup: dict[int, InjuryEntry] = {}
    if injuries:
        injury_lookup = build_injury_lookup(injuries)

    # Build closer list for vacancy detection
    closer_teams: dict[str, int] = {}  # team -> player_id of closer
    closer_result = await session.execute(
        select(Player, PitchingStats)
        .join(PitchingStats)
        .where(
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
            PitchingStats.sv > 3,
        )
        .order_by(PitchingStats.sv.desc())
    )
    for player, ps in closer_result.all():
        team = player.team or ""
        if team and team not in closer_teams:
            closer_teams[team] = player.id

    # Check which closers are injured
    teams_with_closer_vacancy: set[str] = set()
    injured_closer_names: dict[str, str] = {}  # team -> closer name
    for team, pid in closer_teams.items():
        player_result = await session.execute(select(Player).where(Player.id == pid))
        closer_player = player_result.scalar_one_or_none()
        if closer_player and closer_player.mlbam_id:
            mlbam = int(closer_player.mlbam_id)
            if mlbam in injury_lookup:
                entry = injury_lookup[mlbam]
                if "IL" in entry.status:
                    teams_with_closer_vacancy.add(team)
                    injured_closer_names[team] = closer_player.name

    # Build pitcher-opponent matchups for game details
    # Map: team -> list of opposing pitcher names for the week
    team_opponents: dict[str, list[str]] = {}
    for gd in game_details:
        away = gd.get("away_team", "")
        home = gd.get("home_team", "")
        away_p = gd.get("home_pitcher_name") or "TBD"
        home_p = gd.get("away_pitcher_name") or "TBD"
        team_opponents.setdefault(away, []).append(away_p)
        team_opponents.setdefault(home, []).append(home_p)

    # Build pitcher start details: mlbam_id -> list of opponent teams
    pitcher_start_opponents: dict[int, list[str]] = {}
    for gd in game_details:
        for side, opp_side in [("away_pitcher_id", "home_team"), ("home_pitcher_id", "away_team")]:
            pid = gd.get(side)
            if pid:
                pitcher_start_opponents.setdefault(int(pid), []).append(gd.get(opp_side, "TBD"))

    recommendations: list[WaiverRecommendation] = []

    for player in all_players:
        # Check injury — exclude IL players from weekly
        mlbam_id = int(player.mlbam_id) if player.mlbam_id else None
        injury_status = None
        if mlbam_id and mlbam_id in injury_lookup:
            entry = injury_lookup[mlbam_id]
            injury_status = f"{entry.status} - {entry.injury}"
            if "IL" in entry.status:
                continue  # Skip IL players for weekly

        pp_result = await session.execute(
            select(PlayerPoints).where(
                PlayerPoints.player_id == player.id,
                PlayerPoints.season == season,
                PlayerPoints.period == "full_season",
            )
        )
        pp = pp_result.scalar_one_or_none()

        proj = await project_hitter(session, player, season)
        player_type = "hitter"
        if not proj:
            proj = await project_pitcher(session, player, season)
            player_type = "pitcher"
        if not proj:
            continue

        team = player.team or ""
        games_this_week = team_games.get(team, 6)
        reasons: list[str] = []

        # --- Weekly projection ---
        weekly_pts = 0.0
        num_starts = 0
        two_start = False
        start_opponents: list[str] = []
        reliever_role = None
        save_opps = 0.0
        hold_opps = 0.0
        closer_vacancy = False

        if player_type == "hitter":
            # Hitter weekly points: rate * weekly PA
            ppa = pp.points_per_pa if pp else None
            if ppa and ppa > 0:
                # Estimate PA/game from season data
                bat_result = await session.execute(
                    select(BattingStats).where(
                        BattingStats.player_id == player.id,
                        BattingStats.season == season,
                        BattingStats.period == "full_season",
                    )
                )
                bat = bat_result.scalar_one_or_none()
                if bat and bat.pa and bat.g and bat.g > 0:
                    pa_per_game = bat.pa / bat.g
                else:
                    pa_per_game = 3.8  # default
                weekly_pts = ppa * pa_per_game * games_this_week
            reasons.append(f"Team plays {games_this_week} games")
        else:
            # Pitcher: check if SP or RP
            pitch_result = await session.execute(
                select(PitchingStats).where(
                    PitchingStats.player_id == player.id,
                    PitchingStats.season == season,
                    PitchingStats.period == "full_season",
                )
            )
            pitch = pitch_result.scalar_one_or_none()

            is_starter = pitch and (pitch.gs or 0) > (pitch.g or 1) * 0.3 if pitch else False

            if is_starter:
                # Starting pitcher — check number of starts
                if mlbam_id and mlbam_id in probable_starters:
                    num_starts = probable_starters[mlbam_id]
                    start_opponents = pitcher_start_opponents.get(mlbam_id, [])
                else:
                    # Estimate from rotation position
                    num_starts = max(1, round(games_this_week / 5))
                    start_opponents = []

                two_start = num_starts >= 2

                # Use points_per_start if available
                pps = pp.points_per_start if pp else None
                if pps:
                    weekly_pts = pps * num_starts
                elif pp and pp.points_per_ip:
                    avg_ip_per_start = (pitch.ip or 0) / max(pitch.gs or 1, 1) if pitch else 5.5
                    weekly_pts = pp.points_per_ip * avg_ip_per_start * num_starts

                if two_start:
                    opp_str = ", ".join(f"vs {o}" for o in start_opponents[:2])
                    reasons.append(f"2-START WEEK: {opp_str}" if opp_str else "2-START WEEK")
                else:
                    if start_opponents:
                        reasons.append(f"{num_starts} start: vs {start_opponents[0]}")
                    else:
                        reasons.append(f"{num_starts} projected start(s)")
            else:
                # Reliever — use per-appearance rate
                from app.services.reliever_service import _determine_role

                if pitch:
                    reliever_role = _determine_role(pitch)
                    if reliever_role == "starter":
                        reliever_role = None

                ppa_rp = pp.points_per_appearance if pp else None
                if ppa_rp and pitch:
                    g = pitch.g or 1
                    apps_per_game = min(g / 162, 0.8)
                    weekly_apps = apps_per_game * games_this_week
                    weekly_pts = ppa_rp * weekly_apps

                    # Save/hold opportunities
                    sv = pitch.sv or 0
                    hld = pitch.hld or 0
                    if sv > 0:
                        sv_per_game = sv / max(g, 1)
                        save_opps = sv_per_game * games_this_week * 1.5
                    if hld > 0:
                        hld_per_game = hld / max(g, 1)
                        hold_opps = hld_per_game * games_this_week * 1.5

                # Closer vacancy detection
                if team in teams_with_closer_vacancy and reliever_role == "setup":
                    closer_vacancy = True
                    injured_name = injured_closer_names.get(team, "closer")
                    reasons.append(f"CLOSER VACANCY: {injured_name} on IL, next in line for saves")

                if reliever_role == "closer":
                    reasons.append(
                        f"Closer, {save_opps:.1f} projected SV opps "
                        f"({save_opps * 7:.0f} pts from saves)"
                    )
                elif reliever_role == "setup":
                    reasons.append(
                        f"Setup, {hold_opps:.1f} projected HLD opps "
                        f"({hold_opps * 4:.0f} pts from holds)"
                    )

        # DTD penalty
        if injury_status and "DTD" in (injury_status or "").upper():
            weekly_pts *= 0.5
            reasons.append(f"⚠ {injury_status} — projection reduced 50%")

        # --- Normalize weekly points to 0-100 projection score ---
        proj_score = min((weekly_pts / WEEKLY_PROJECTION_MAX) * 100, 100) if weekly_pts > 0 else 0.0

        # --- Trend + breakout ---
        trend_score, trend, xwoba_delta, barrel_delta, hard_hit_delta = await _compute_trend(
            session, player.id, season
        )
        breakout, breakout_detail = _detect_breakout(xwoba_delta, barrel_delta, hard_hit_delta)
        if breakout:
            trend_score = min(trend_score + 15, 100)
            reasons.append(breakout_detail)

        # --- Positional scarcity ---
        pos_score = _compute_positional_scarcity(player.position)

        # --- Scoring fit ---
        scoring_fit, fit_reasons = await _compute_scoring_fit(session, player, player_type, season)
        reasons = fit_reasons + reasons  # fit reasons first

        # Two-start pitcher boost
        if two_start:
            scoring_fit = min(scoring_fit + 20, 100)

        # Closer vacancy boost
        if closer_vacancy:
            scoring_fit = min(scoring_fit + 25, 100)

        # --- Schedule volume score (replaces ownership placeholder) ---
        if games_this_week >= 7:
            schedule_score = 90.0
        elif games_this_week >= 6:
            schedule_score = 60.0
        elif games_this_week >= 5:
            schedule_score = 35.0
        else:
            schedule_score = 15.0

        # --- Matchup quality (simplified for performance) ---
        matchup_quality = 50.0
        matchup_detail = ""
        # For hitters, more games = more quality opportunities on average
        # Detailed per-game matchup quality is expensive, so we use a lighter signal
        if player_type == "hitter" and games_this_week >= 7:
            matchup_quality = 65.0
            matchup_detail = f"{games_this_week} games this week"
        elif player_type == "pitcher" and two_start:
            matchup_quality = 70.0
            matchup_detail = "Two-start week"

        # --- Additional reasoning ---
        if trend == "hot":
            reasons.append("Recent Statcast metrics trending up")
        if hasattr(proj, "buy_low_signal") and proj.buy_low_signal:
            reasons.append(f"Buy low: xwOBA exceeds wOBA by {proj.xwoba_delta:+.3f}")
        if pos_score >= 70:
            pos = (player.position or "UTIL").split(",")[0].strip()
            reasons.append(f"Scarce position ({pos})")
        reasons.append(f"Projected {weekly_pts:.0f} pts this week")

        reasoning = "; ".join(reasons) if reasons else "Solid production"

        # --- Composite score ---
        composite = (
            proj_score * 0.35
            + trend_score * 0.25
            + pos_score * 0.15
            + scoring_fit * 0.15
            + schedule_score * 0.10
        )

        buy_low = getattr(proj, "buy_low_signal", False)
        xwoba_d = getattr(proj, "xwoba_delta", 0.0)

        recommendations.append(
            WaiverRecommendation(
                player_id=player.id,
                name=player.name,
                team=player.team,
                position=player.position,
                waiver_score=round(composite, 1),
                projection_score=round(proj_score, 1),
                trend_score=round(trend_score, 1),
                positional_need_score=round(pos_score, 1),
                reasoning=reasoning,
                buy_low=buy_low,
                xwoba_delta=xwoba_d,
                trend=trend,
                projected_points=round(weekly_pts, 1),
                points_per_pa=pp.points_per_pa if pp else None,
                points_per_ip=pp.points_per_ip if pp else None,
                scoring_fit_score=round(scoring_fit, 1),
                player_type=player_type,
                projection_period=f"week_{week_start.isoformat()}",
                weekly_points=round(weekly_pts, 1),
                team_games=games_this_week,
                num_starts=num_starts,
                reliever_role=reliever_role,
                save_opps_week=round(save_opps, 1),
                hold_opps_week=round(hold_opps, 1),
                closer_vacancy=closer_vacancy,
                matchup_quality=round(matchup_quality, 1),
                matchup_detail=matchup_detail,
                breakout_signal=breakout,
                breakout_detail=breakout_detail,
                injury_status=injury_status,
                two_start=two_start,
                start_opponents=start_opponents,
            )
        )

    recommendations.sort(key=lambda r: r.waiver_score, reverse=True)
    return recommendations[:limit]


def _format_weak_spots(weak_spots: list[str]) -> str:
    """Format weak spots for the AI prompt."""
    if not weak_spots:
        return "No obvious weak spots identified."
    lines = chr(10).join(f"  {w}" for w in weak_spots)
    return f"WEAK SPOTS:{chr(10)}{lines}"


async def analyze_roster_waivers(
    session: AsyncSession,
    season: int,
    recommendations: list[WaiverRecommendation],
    injuries: list[InjuryEntry] | None = None,
    period: str = "ros",
    week_start: date | None = None,
    week_end: date | None = None,
) -> str:
    """Generate AI-powered waiver pickup/drop recommendations.

    Builds a focused prompt with roster context, waiver targets, injuries,
    and league scoring, then calls Claude for personalized analysis.
    Returns markdown-formatted analysis text.
    """
    import anthropic

    from app.config import settings
    from app.models.roster import Roster

    if not settings.anthropic_api_key:
        return "**AI analysis unavailable** — Anthropic API key not configured."

    # Load user's roster
    roster_result = await session.execute(
        select(Roster, Player, PlayerPoints)
        .join(Player, Roster.player_id == Player.id)
        .outerjoin(
            PlayerPoints,
            (PlayerPoints.player_id == Player.id)
            & (PlayerPoints.season == season)
            & (PlayerPoints.period == "full_season"),
        )
        .where(Roster.is_my_team.is_(True))
    )
    roster_rows = roster_result.all()

    if not roster_rows:
        return "**No roster data available.** Sync your Yahoo roster first."

    # Build roster summary by position
    roster_lines: list[str] = []
    pos_points: dict[str, list[float]] = {}
    for roster, player, pp in roster_rows:
        pos = roster.roster_position or player.position or "UTIL"
        pts = pp.projected_ros_points if pp else 0
        ppa = pp.points_per_pa if pp and pp.points_per_pa else None
        ppi = pp.points_per_ip if pp and pp.points_per_ip else None
        rate_str = ""
        if ppa:
            rate_str = f" ({ppa:.1f} pts/PA)"
        elif ppi:
            rate_str = f" ({ppi:.1f} pts/IP)"
        has_multi = player.position and "," in player.position
        elig = f" [Eligible: {player.position}]" if has_multi else ""
        roster_lines.append(
            f"  {pos}: {player.name} ({player.team}) — {pts:.0f} ROS pts{rate_str}{elig}"
        )
        pos_points.setdefault(pos, []).append(pts or 0)

    # Identify weak spots
    weak_spots: list[str] = []
    total_pts = sum(p for pts_list in pos_points.values() for p in pts_list)
    total_count = sum(len(v) for v in pos_points.values())
    avg_pts = total_pts / max(total_count, 1)
    for pos, pts_list in pos_points.items():
        pos_avg = sum(pts_list) / len(pts_list) if pts_list else 0
        if pos_avg < avg_pts * 0.7:
            weak_spots.append(f"{pos} (avg {pos_avg:.0f} pts, roster avg {avg_pts:.0f})")

    # Build waiver target summary (top 15)
    target_lines: list[str] = []
    two_start_lines: list[str] = []
    closer_vacancy_lines: list[str] = []
    breakout_lines: list[str] = []
    for rec in recommendations[:15]:
        extras = []
        if rec.two_start:
            opp_str = ", ".join(f"vs {o}" for o in rec.start_opponents[:2])
            extras.append(f"2-START ({opp_str})")
            two_start_lines.append(
                f"  {rec.name} — {opp_str}, {rec.weekly_points:.0f} projected pts"
            )
        if rec.closer_vacancy:
            extras.append("CLOSER VACANCY")
            closer_vacancy_lines.append(f"  {rec.name} ({rec.team}) — setup man, closer injured")
        if rec.breakout_signal:
            extras.append("BREAKOUT")
            breakout_lines.append(f"  {rec.name} — {rec.breakout_detail}")
        if rec.reliever_role:
            extras.append(f"Role: {rec.reliever_role.upper()}")
        extra_str = f" [{', '.join(extras)}]" if extras else ""
        pts_label = "week pts" if period != "ros" else "ROS pts"
        pts_val = rec.weekly_points if period != "ros" else rec.projected_points
        target_lines.append(
            f"  {rec.name} ({rec.position}, {rec.team}) — "
            f"Score: {rec.waiver_score}, {pts_val:.0f} {pts_label}{extra_str}"
        )

    # Build injury context
    injury_lines: list[str] = []
    if injuries:
        relevant_mlbam: set[int] = set()
        for roster, player, _ in roster_rows:
            if player.mlbam_id:
                relevant_mlbam.add(int(player.mlbam_id))
        for inj in injuries:
            if inj.mlbam_id in relevant_mlbam:
                injury_lines.append(
                    f"  {inj.player_name} ({inj.team}) — {inj.status}: {inj.injury}"
                )
        for rec in recommendations[:15]:
            if rec.injury_status:
                injury_lines.append(f"  {rec.name} ({rec.team}) — {rec.injury_status}")

    # Build the prompt
    period_context = "rest-of-season (ROS) projections"
    if period != "ros" and week_start and week_end:
        period_context = f"the week of {week_start.strftime('%b %d')}–{week_end.strftime('%b %d')}"

    user_message = f"""Analyze my roster and the available waiver wire pickups for {period_context}.

MY CURRENT ROSTER:
{chr(10).join(roster_lines)}

{_format_weak_spots(weak_spots)}

TOP WAIVER TARGETS (ranked by composite score):
{chr(10).join(target_lines)}
"""

    if two_start_lines and period != "ros":
        user_message += f"""
TWO-START PITCHERS AVAILABLE:
{chr(10).join(two_start_lines)}
"""

    if closer_vacancy_lines:
        user_message += f"""
CLOSER VACANCIES (injured closers — setup men available):
{chr(10).join(closer_vacancy_lines)}
"""

    if breakout_lines:
        user_message += f"""
STATCAST BREAKOUT CANDIDATES:
{chr(10).join(breakout_lines)}
"""

    if injury_lines:
        user_message += f"""
RELEVANT INJURIES (Source: MLB Official Injury Report):
{chr(10).join(injury_lines)}
"""

    scoring_line = (
        "LEAGUE SCORING: H2H Points — "
        "R=1, 1B=1, 2B=2, 3B=3, HR=4, RBI=1, SB=2, "
        "CS=-1, BB=1, HBP=1, K=-0.5 | "
        "OUT=1.5, K(P)=0.5, SV=7, HLD=4, RW=4, QS=2, "
        "ER=-4, BB(P)=-0.75, H(P)=-0.75"
    )
    ask_line = (
        'Give me 3-5 specific "PICK UP [Player X], '
        'DROP [Player Y]" recommendations with '
        "reasoning tied to the scoring system. "
        "Consider each player's full position eligibility "
        "(shown in parentheses or [Eligible: ...] brackets) "
        "when evaluating roster fit — a multi-position "
        "player adds lineup flexibility."
    )
    user_message += f"\n{scoring_line}\n\n{ask_line}"

    if period != "ros":
        weekly_note = (
            "\n\nIMPORTANT: This is a WEEKLY pickup analysis. "
            "Do NOT recommend picking up players listed as "
            "Day-to-Day or on the IL for a one-week pickup. "
            "Prioritize two-start pitchers, closer vacancy "
            "pickups, and hitters with favorable schedules. "
            "Flag any of my roster players who are DTD as "
            "potential drop candidates if their injury may "
            "cause them to miss games this week."
        )
        user_message += weekly_note

    system_prompt = (
        "You are a fantasy baseball analyst for a 10-team H2H Points keeper league. "
        "Give specific, actionable pickup/drop recommendations. Always cite injury sources. "
        "Be concise — lead with the recommendation, then 1-2 sentences of reasoning. "
        "Use the league scoring rules to explain WHY each move helps."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.assistant_model,
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"AI waiver analysis failed: {e}")
        return f"**AI analysis failed:** {e}"
