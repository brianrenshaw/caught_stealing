"""Weekly lineup analysis service for the dashboard.

Orchestrates weekly player projections, lineup optimization, injury data,
and AI-powered start/sit recommendations for the user's roster.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.roster import Roster

logger = logging.getLogger(__name__)

BENCH_POSITIONS = {"BN", "IL", "IL+", "NA", "DL"}


@dataclass
class WeeklyPlayer:
    """A rostered player with weekly projection data."""

    player_id: int
    name: str
    team: str
    position: str
    roster_position: str
    weekly_pts: float
    team_games: int = 0
    num_starts: int = 0
    is_bench: bool = False
    injury_status: str | None = None
    two_start: bool = False


@dataclass
class LineupSwap:
    """A suggested lineup change from the optimizer."""

    start_player: str
    start_player_id: int
    bench_player: str
    bench_player_id: int
    slot: str
    point_gain: float


@dataclass
class WeeklyLineupData:
    """Complete weekly lineup analysis data."""

    players: list[WeeklyPlayer] = field(default_factory=list)
    swaps: list[LineupSwap] = field(default_factory=list)
    current_total: float = 0.0
    optimal_total: float = 0.0
    improvement: float = 0.0
    p_slot_strategy: str = ""
    week_start: date | None = None
    week_end: date | None = None


async def get_weekly_lineup_data(
    session: AsyncSession,
    season: int,
) -> WeeklyLineupData | None:
    """Get weekly lineup projections with optimizer suggestions.

    Combines:
    - Per-player weekly projected points (4-phase matchup adjustments)
    - PuLP ILP optimizer for optimal slot assignments
    - Injury data from MLB API
    - P-slot strategy recommendation
    - Two-start pitcher detection
    """
    from app.services.mlb_service import (
        build_injury_lookup,
        get_injuries,
    )
    from app.services.optimizer_service import optimize_weekly_lineup
    from app.services.schedule_service import (
        get_all_team_games_in_range,
        get_probable_starters_in_range,
        get_week_boundaries,
    )
    from app.services.weekly_matchup_service import (
        compute_team_projected_breakdown,
    )

    # Get week boundaries
    week_start, week_end = get_week_boundaries(0)
    ws = week_start.strftime("%Y-%m-%d")
    we = week_end.strftime("%Y-%m-%d")

    # Find my team_id
    team_result = await session.execute(
        select(Roster.team_id).where(Roster.is_my_team.is_(True)).limit(1)
    )
    my_team_id = team_result.scalar_one_or_none()
    if not my_team_id:
        return None

    # Get schedule data
    team_games = await get_all_team_games_in_range(week_start, week_end)
    probable_starters = await get_probable_starters_in_range(week_start, week_end)

    # Get injuries
    injuries = await get_injuries()
    injury_lookup = build_injury_lookup(injuries)

    # Compute weekly projections (with bench player projections)
    breakdown = await compute_team_projected_breakdown(
        session, my_team_id, season, ws, we, project_bench=True
    )

    player_list = breakdown.get("players", [])

    # Build weekly points map for optimizer: player_id -> weekly_pts
    weekly_points_map: dict[int, float] = {}
    for p in player_list:
        pid = p.get("player_id")
        if pid:
            weekly_points_map[pid] = p.get("points", 0.0)

    # Run optimizer
    optimal = await optimize_weekly_lineup(session, weekly_points_map)

    # Batch fetch all player objects (avoid N+1 queries)
    from app.models.player import Player

    all_pids = [p.get("player_id") for p in player_list if p.get("player_id")]
    player_result = await session.execute(select(Player).where(Player.id.in_(all_pids)))
    player_map: dict[int, Player] = {p.id: p for p in player_result.scalars().all()}

    # Build player objects with enriched data
    players: list[WeeklyPlayer] = []
    for p in player_list:
        pid = p.get("player_id")
        if not pid:
            continue

        pos = p.get("roster_position", "")
        is_bench = pos in BENCH_POSITIONS
        player_obj = player_map.get(pid)
        p_team = player_obj.team or "" if player_obj else ""

        games = team_games.get(p_team, 6)

        # Check injury
        injury_status = None
        if player_obj and player_obj.mlbam_id:
            mlbam = int(player_obj.mlbam_id)
            if mlbam in injury_lookup:
                entry = injury_lookup[mlbam]
                injury_status = f"{entry.status} - {entry.injury}"

        # Check two-start
        num_starts = 0
        two_start = False
        if player_obj and player_obj.mlbam_id:
            mlbam = int(player_obj.mlbam_id)
            if mlbam in probable_starters:
                num_starts = probable_starters[mlbam]
                two_start = num_starts >= 2

        players.append(
            WeeklyPlayer(
                player_id=pid,
                name=p.get("name", ""),
                team=p_team,
                position=player_obj.position if player_obj else "",
                roster_position=pos,
                weekly_pts=round(p.get("points", 0.0), 1),
                team_games=games,
                num_starts=num_starts,
                is_bench=is_bench,
                injury_status=injury_status,
                two_start=two_start,
            )
        )

    # Compute current vs optimal totals
    current_total = sum(p.weekly_pts for p in players if not p.is_bench)

    # Build swap suggestions by comparing current vs optimal assignments
    swaps: list[LineupSwap] = []
    if optimal and optimal.improvement > 0:
        # Map current slot assignments
        current_slots: dict[int, str] = {p.player_id: p.roster_position for p in players}
        optimal_slots: dict[int, str] = {a["player_id"]: a["slot"] for a in optimal.assignments}

        # Find players who move from bench to active
        for pid, new_slot in optimal_slots.items():
            old_slot = current_slots.get(pid, "BN")
            if old_slot in BENCH_POSITIONS and new_slot not in BENCH_POSITIONS:
                # Find who they're replacing
                for other_pid, other_old in current_slots.items():
                    if other_old == new_slot or (
                        other_old not in BENCH_POSITIONS
                        and optimal_slots.get(other_pid, "") in BENCH_POSITIONS
                    ):
                        start_name = next(
                            (p.name for p in players if p.player_id == pid),
                            "Unknown",
                        )
                        bench_name = next(
                            (p.name for p in players if p.player_id == other_pid),
                            "Unknown",
                        )
                        start_pts = weekly_points_map.get(pid, 0)
                        bench_pts = weekly_points_map.get(other_pid, 0)
                        swaps.append(
                            LineupSwap(
                                start_player=start_name,
                                start_player_id=pid,
                                bench_player=bench_name,
                                bench_player_id=other_pid,
                                slot=new_slot,
                                point_gain=round(start_pts - bench_pts, 1),
                            )
                        )
                        break

    # P-slot strategy
    p_slot_strategy = ""
    try:
        from app.services.start_projector import (
            recommend_p_slot_strategy,
        )

        strategy = await recommend_p_slot_strategy(session, season, week_start, week_end)
        if strategy:
            p_slot_strategy = getattr(strategy, "recommendation", "")
    except Exception:
        pass

    return WeeklyLineupData(
        players=players,
        swaps=swaps,
        current_total=round(current_total, 1),
        optimal_total=round(optimal.total_points, 1) if optimal else round(current_total, 1),
        improvement=round(optimal.improvement, 1) if optimal else 0.0,
        p_slot_strategy=p_slot_strategy,
        week_start=week_start,
        week_end=week_end,
    )


async def analyze_weekly_lineup(
    session: AsyncSession,
    season: int,
    data: WeeklyLineupData,
) -> str:
    """Generate AI-powered start/sit recommendations.

    Follows the same Claude API pattern as waiver_service.analyze_roster_waivers().
    """
    import anthropic

    from app.config import settings

    if not settings.anthropic_api_key:
        return "**AI analysis unavailable** — Anthropic API key not configured."

    if not data.players:
        return "**No lineup data available.** Sync your Yahoo roster first."

    # Build starters and bench lists
    starters = [p for p in data.players if not p.is_bench]
    bench = [p for p in data.players if p.is_bench]

    starter_lines = []
    for p in sorted(starters, key=lambda x: x.roster_position):
        extras = []
        if p.two_start:
            extras.append("2-START")
        if p.injury_status:
            extras.append(f"INJURY: {p.injury_status}")
        extra_str = f" [{', '.join(extras)}]" if extras else ""
        elig = f" [Eligible: {p.position}]" if "," in (p.position or "") else ""
        starter_lines.append(
            f"  {p.roster_position}: {p.name} ({p.team}) — "
            f"{p.weekly_pts:.0f} weekly pts, "
            f"{p.team_games} games{elig}{extra_str}"
        )

    bench_lines = []
    for p in sorted(bench, key=lambda x: -x.weekly_pts):
        extras = []
        if p.two_start:
            extras.append("2-START")
        if p.injury_status:
            extras.append(f"INJURY: {p.injury_status}")
        extra_str = f" [{', '.join(extras)}]" if extras else ""
        bench_lines.append(
            f"  {p.name} ({p.team}, {p.position}) — "
            f"{p.weekly_pts:.0f} weekly pts, "
            f"{p.team_games} games{extra_str}"
        )

    # Build swap suggestions
    swap_lines = []
    for s in data.swaps:
        swap_lines.append(
            f"  START {s.start_player} at {s.slot}, "
            f"BENCH {s.bench_player} (+{s.point_gain:.0f} pts)"
        )

    # Build the prompt
    week_label = ""
    if data.week_start and data.week_end:
        week_label = f"{data.week_start.strftime('%b %d')}–{data.week_end.strftime('%b %d')}"

    user_message = f"""Analyze my starting lineup for the week of {week_label}.

CURRENT STARTERS ({data.current_total:.0f} projected pts):
{chr(10).join(starter_lines)}

BENCH PLAYERS:
{chr(10).join(bench_lines) if bench_lines else "  (none)"}
"""

    if swap_lines:
        user_message += f"""
OPTIMIZER SUGGESTIONS (+{data.improvement:.0f} pts):
{chr(10).join(swap_lines)}
"""

    if data.p_slot_strategy:
        user_message += f"""
P-SLOT STRATEGY: {data.p_slot_strategy}
"""

    # Injury alerts
    injured = [p for p in data.players if p.injury_status]
    if injured:
        inj_lines = [f"  {p.name} — {p.injury_status}" for p in injured]
        user_message += f"""
INJURY ALERTS (Source: MLB Official Injury Report):
{chr(10).join(inj_lines)}
"""

    scoring_line = (
        "LEAGUE SCORING: H2H Points — "
        "R=1, 1B=1, 2B=2, 3B=3, HR=4, RBI=1, SB=2, "
        "CS=-1, BB=1, HBP=1, K=-0.5 | "
        "OUT=1.5, K(P)=0.5, SV=7, HLD=4, RW=4, QS=2, "
        "ER=-4, BB(P)=-0.75, H(P)=-0.75"
    )
    user_message += f"\n{scoring_line}\n\n"
    user_message += (
        "Give me specific START/SIT recommendations for this week. "
        "Consider each player's full position eligibility (shown in "
        "[Eligible: ...] brackets) when suggesting lineup moves — "
        "a player eligible at 2B,SS,OF can fill any of those slots "
        "or Util. Explain WHY in terms of matchups, schedule, and "
        "league scoring. If the optimizer suggests changes, evaluate "
        "whether you agree. Flag any injury risks."
    )

    system_prompt = (
        "You are a fantasy baseball analyst for a 10-team H2H Points "
        "keeper league with a Monday lineup deadline. Give specific "
        "start/sit recommendations. Be concise — lead with the "
        "recommendation, then 1-2 sentences of reasoning. "
        "Use the league scoring rules to explain WHY."
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
        logger.error(f"AI lineup analysis failed: {e}")
        return f"**AI analysis failed:** {e}"


async def build_game_context_for_prompt(start: date, end: date) -> str:
    """Build a rich per-game schedule block for AI prompts.

    Includes opponent, venue, park factor, weather, and probable
    starter for each game. Reusable across waiver, lineup, and
    outlook analysis prompts.
    """
    from app.services.matchup_service import PARK_FACTORS
    from app.services.schedule_service import get_game_details_in_range

    game_details = await get_game_details_in_range(start, end)
    if not game_details:
        return "No schedule data available for this period."

    lines = []
    cold_count = 0
    for gd in game_details:
        game_date = gd.get("game_date", "")
        away = gd.get("away_team", "?")
        home = gd.get("home_team", "?")
        venue = gd.get("venue", "")
        away_p = gd.get("away_pitcher_name") or "TBD"
        home_p = gd.get("home_pitcher_name") or "TBD"

        # Park factor
        pf = PARK_FACTORS.get(venue, 1.0)
        pf_label = f"PF:{pf:.2f}"

        # Weather
        weather = gd.get("weather", {})
        temp = weather.get("temp")
        temp_str = ""
        if temp:
            try:
                temp_int = int(temp)
                temp_str = f", {temp_int}°F"
                if temp_int < 50:
                    cold_count += 1
            except (ValueError, TypeError):
                pass

        lines.append(
            f"  {game_date}: {away} @ {home} — "
            f"{venue} ({pf_label}{temp_str}) — "
            f"{away} starter: {away_p}, {home} starter: {home_p}"
        )

    header = f"WEEKLY SCHEDULE ({len(lines)} games):"
    result = header + "\n" + "\n".join(lines)

    if cold_count > 0:
        result += (
            f"\n  ⚠ COLD WEATHER: {cold_count} game(s) below 50°F — expect suppressed power numbers"
        )

    return result


async def generate_weekly_outlook(
    session: AsyncSession,
    season: int,
) -> str:
    """Generate an AI-powered weekly matchup preview column.

    Assembles comprehensive context and calls Claude to write a
    narrative fantasy analyst column covering the H2H matchup,
    key players, standings, injuries, schedule, and personalized
    sections (Cardinals Corner, Ithilien Watch).
    """
    import json

    import anthropic

    from app.config import settings
    from app.models.league_team import LeagueTeam
    from app.models.player import Player
    from app.models.player_points import PlayerPoints
    from app.services.mlb_service import get_injuries
    from app.services.rankings_service import (
        get_buy_low_candidates,
        get_hot_pickups,
        get_sell_high_candidates,
    )
    from app.services.schedule_service import get_week_boundaries
    from app.services.weekly_matchup_service import (
        get_or_create_weekly_snapshot,
    )

    def _short_team(name: str) -> str:
        """First word of fantasy team name, or 'FA' for unrostered."""
        return name.split()[0] if name else "FA"

    if not settings.anthropic_api_key:
        return "**Weekly outlook unavailable** — API key not configured."

    week_start, week_end = get_week_boundaries(0)

    # --- Build fantasy team lookup (player_id → abbreviated team name) ---
    roster_rows = await session.execute(
        select(Roster.player_id, Roster.team_name, Player.mlbam_id)
        .join(Player, Roster.player_id == Player.id)
    )
    _team_lookup: dict[int, str] = {}
    _mlbam_lookup: dict[int, str] = {}
    for r in roster_rows.all():
        short = _short_team(r.team_name)
        _team_lookup[r.player_id] = short
        if r.mlbam_id:
            _mlbam_lookup[int(r.mlbam_id)] = short

    def _ftag(player_id: int | None) -> str:
        """Return fantasy team tag string for a player, e.g. '(Empire)'."""
        if player_id is None:
            return "(FA)"
        return f"({_team_lookup.get(player_id, 'FA')})"

    def _ftag_mlbam(mlbam_id: int | None) -> str:
        """Return fantasy team tag by mlbam_id, e.g. '(Ithilien)'."""
        if mlbam_id is None:
            return "(FA)"
        return f"({_mlbam_lookup.get(int(mlbam_id), 'FA')})"

    # --- Gather all context ---

    # 1. Matchup snapshot (my team vs opponent)
    snapshot = None
    try:
        snapshot = await get_or_create_weekly_snapshot(session, season)
    except Exception as e:
        logger.warning(f"Failed to get matchup snapshot: {e}")

    # 2. League standings
    standings_result = await session.execute(select(LeagueTeam).order_by(LeagueTeam.rank))
    standings = standings_result.scalars().all()

    standings_lines = []
    my_rank = "?"
    opp_rank = "?"
    for team in standings:
        marker = ""
        if team.is_my_team:
            marker = " ← YOU"
            my_rank = str(team.rank)
        if snapshot and team.team_name == snapshot.opponent_team_name:
            marker = " ← OPPONENT"
            opp_rank = str(team.rank)
        if team.team_name == "Ithilien":
            marker += " ← BROTHER"
        standings_lines.append(
            f"  {team.rank}. {team.team_name} "
            f"({team.wins}-{team.losses}) "
            f"PF: {team.points_for:.0f}{marker}"
        )

    # 3. My team + opponent breakdowns
    my_breakdown_text = ""
    opp_breakdown_text = ""
    my_app_proj = None
    opp_app_proj = None
    if snapshot:
        try:
            my_bd = json.loads(snapshot.my_projected_breakdown or "{}")
            opp_bd = json.loads(snapshot.opponent_projected_breakdown or "{}")
            my_players = my_bd.get("players", [])
            opp_players = opp_bd.get("players", [])

            my_lines = []
            for p in sorted(my_players, key=lambda x: x.get("points", 0), reverse=True)[:10]:
                pid = p.get("player_id")
                my_lines.append(
                    f"  {p.get('roster_position', '?')}: "
                    f"{p.get('name', '?')} {_ftag(pid)} — "
                    f"{p.get('points', 0):.0f} pts"
                )
            my_breakdown_text = "\n".join(my_lines)

            opp_lines = []
            for p in sorted(opp_players, key=lambda x: x.get("points", 0), reverse=True)[:10]:
                pid = p.get("player_id")
                opp_lines.append(
                    f"  {p.get('roster_position', '?')}: "
                    f"{p.get('name', '?')} {_ftag(pid)} — "
                    f"{p.get('points', 0):.0f} pts"
                )
            opp_breakdown_text = "\n".join(opp_lines)

            # App-calculated totals (sum of per-player projections)
            my_app_proj = sum(p.get("points", 0) for p in my_players) if my_players else None
            opp_app_proj = sum(p.get("points", 0) for p in opp_players) if opp_players else None
        except Exception:
            my_app_proj = None
            opp_app_proj = None

    # 4. Hot/cold players + signals
    hot_players = []
    buy_low = []
    sell_high = []
    try:
        hot_players = await get_hot_pickups(session, season, limit=5)
        buy_low = await get_buy_low_candidates(session, season, limit=5)
        sell_high = await get_sell_high_candidates(session, season, limit=5)
    except Exception:
        pass

    # 5. Injuries
    injuries = []
    try:
        injuries = await get_injuries()
    except Exception:
        pass

    # 6. Game schedule with weather
    schedule_text = await build_game_context_for_prompt(week_start, week_end)

    # 7. Ithilien (brother's team) data
    ithilien_text = ""
    try:
        ith_team = await session.execute(
            select(LeagueTeam).where(LeagueTeam.team_name == "Ithilien")
        )
        ith = ith_team.scalar_one_or_none()

        ith_roster = await session.execute(
            select(Roster, Player, PlayerPoints)
            .join(Player, Roster.player_id == Player.id)
            .outerjoin(
                PlayerPoints,
                (PlayerPoints.player_id == Player.id)
                & (PlayerPoints.season == season)
                & (PlayerPoints.period == "full_season"),
            )
            .where(Roster.team_name == "Ithilien")
        )
        ith_rows = ith_roster.all()

        if ith and ith_rows:
            ith_lines = [
                f"  Record: {ith.wins}-{ith.losses} (Rank: {ith.rank})",
                f"  Points For: {ith.points_for:.0f}",
            ]
            top_ith = sorted(
                ith_rows,
                key=lambda x: (
                    x[2].projected_ros_points if x[2] and x[2].projected_ros_points else 0
                ),
                reverse=True,
            )[:5]
            for roster, player, pp in top_ith:
                pts = pp.projected_ros_points if pp and pp.projected_ros_points else 0
                ith_lines.append(
                    f"  {roster.roster_position}: {player.name} (Ithilien) ({player.team}) — {pts:.0f} ROS pts"
                )
            ithilien_text = "\n".join(ith_lines)
    except Exception as e:
        logger.debug(f"Failed to load Ithilien data: {e}")

    # 8. Cardinals players on relevant rosters (my team, opponent, Ithilien)
    cardinals_text = ""
    if snapshot:
        try:
            relevant_team_names = {snapshot.my_team_name, snapshot.opponent_team_name, "Ithilien"}
            relevant_roster = await session.execute(
                select(Roster.player_id).where(Roster.team_name.in_(relevant_team_names))
            )
            stl_pids = {r.player_id for r in relevant_roster.all()}

            if stl_pids:
                stl_result = await session.execute(
                    select(Player, PlayerPoints)
                    .outerjoin(
                        PlayerPoints,
                        (PlayerPoints.player_id == Player.id)
                        & (PlayerPoints.season == season)
                        & (PlayerPoints.period == "full_season"),
                    )
                    .where(
                        Player.id.in_(stl_pids),
                        Player.team == "STL",
                    )
                )
                stl_rows = stl_result.all()
                if stl_rows:
                    stl_lines = []
                    for player, pp in stl_rows:
                        pts = pp.projected_ros_points if pp and pp.projected_ros_points else 0
                        stl_lines.append(f"  {player.name} {_ftag(player.id)} — {pts:.0f} ROS pts")
                    cardinals_text = "\n".join(stl_lines)
        except Exception:
            pass

    # --- Build the prompt ---
    matchup_section = ""
    if snapshot:
        my_proj = snapshot.my_projected_points or 0
        opp_proj = snapshot.opponent_projected_points or 0
        app_proj_line = ""
        if my_app_proj is not None and opp_app_proj is not None:
            app_proj_line = (
                f"  App Projected (schedule-adjusted): {my_app_proj:.0f} pts vs {opp_app_proj:.0f} pts\n"
                f"  Analyze why Yahoo and App projections differ and which is more reliable this week."
            )
        matchup_section = f"""
H2H MATCHUP THIS WEEK:
  {snapshot.my_team_name} (Rank #{my_rank}) vs {snapshot.opponent_team_name} (Rank #{opp_rank})
  Yahoo Projected: {my_proj:.0f} pts vs {opp_proj:.0f} pts
{app_proj_line}
  Edge (Yahoo): {"+" if my_proj > opp_proj else ""}{my_proj - opp_proj:.0f} pts

MY TOP PROJECTED PLAYERS:
{my_breakdown_text if my_breakdown_text else "  (no data)"}

OPPONENT'S TOP PROJECTED PLAYERS:
{opp_breakdown_text if opp_breakdown_text else "  (no data)"}
"""

    hot_section = ""
    if hot_players:
        hot_lines = [f"  {p.name} {_ftag(p.player_id)} ({p.team}) — trending hot" for p in hot_players[:5]]
        hot_section = "HOT PLAYERS:\n" + "\n".join(hot_lines)

    signals_section = ""
    signal_lines = []
    if buy_low:
        for p in buy_low[:3]:
            signal_lines.append(
                f"  BUY LOW: {p.name} {_ftag(p.player_id)} ({p.team}) — xwOBA delta {p.xwoba_delta:+.3f}"
            )
    if sell_high:
        for p in sell_high[:3]:
            signal_lines.append(
                f"  SELL HIGH: {p.name} {_ftag(p.player_id)} ({p.team}) — xwOBA delta {p.xwoba_delta:+.3f}"
            )
    if signal_lines:
        signals_section = "BUY LOW / SELL HIGH:\n" + "\n".join(signal_lines)

    injury_section = ""
    if injuries:
        inj_lines = [
            f"  {i.player_name} {_ftag_mlbam(i.mlbam_id)} ({i.team}) — {i.status}: {i.injury}" for i in injuries[:15]
        ]
        injury_section = "INJURY REPORT (Source: MLB Official Injury Report):\n" + "\n".join(
            inj_lines
        )

    # Check if facing Ithilien
    facing_ithilien = snapshot and snapshot.opponent_team_name == "Ithilien"

    ithilien_section = ""
    if ithilien_text:
        if facing_ithilien:
            ithilien_section = (
                "SIBLING RIVALRY — FACING ITHILIEN THIS WEEK:\n"
                + ithilien_text
                + "\n  This is the brother matchup! Make it personal."
            )
        else:
            ithilien_section = (
                "ITHILIEN WATCH (brother's team):\n"
                + ithilien_text
                + "\n  Include a hypothetical: if we were "
                + "playing each other, who'd have the edge?"
            )

    cardinals_section = ""
    if cardinals_text:
        cardinals_section = "CARDINALS CORNER (STL players in this matchup):\n" + cardinals_text

    standings_text = "\n".join(standings_lines) if standings_lines else ""

    week_label = f"{week_start.strftime('%b %d')}–{week_end.strftime('%b %d')}"
    scoring_line = (
        "LEAGUE SCORING: H2H Points — "
        "R=1, 1B=1, 2B=2, 3B=3, HR=4, RBI=1, SB=2, "
        "CS=-1, BB=1, HBP=1, K=-0.5 | "
        "OUT=1.5, K(P)=0.5, SV=7, HLD=4, RW=4, QS=2, "
        "ER=-4, BB(P)=-0.75, H(P)=-0.75"
    )

    user_message = f"""Write a weekly fantasy baseball preview column for the week of {week_label}.

LEAGUE STANDINGS:
{standings_text}
{matchup_section}
{schedule_text}

{hot_section}

{signals_section}

{injury_section}

{ithilien_section}

{cardinals_section}

{scoring_line}

Write the preview covering:
1. The H2H matchup storyline — edges and vulnerabilities
2. Projection analysis — compare Yahoo vs App projections and explain discrepancies
3. Key players to watch on both sides
4. Schedule and weather factors
5. Injury concerns for both rosters
6. League standings context — playoff positioning
7. Cardinals Corner — STL players in the matchup
8. Ithilien Watch — brother's team update"""

    system_prompt = (
        "You are a professional fantasy baseball analyst writing a weekly "
        "preview column in the style of ESPN or The Athletic. Write with "
        "authority and analytical depth — be specific with numbers and "
        "projected points. Focus on actionable insights and matchup edges. "
        "This is a 10-team H2H Points keeper league. "
        "Use markdown formatting: ## for section headers, **bold** for "
        "emphasis, bullet lists for key points. "
        "Every time you mention a player, include their fantasy team "
        "abbreviation in parentheses exactly as provided in the data. "
        "The reader is a Cardinals fan — make the Cardinals Corner "
        "section insightful. The reader's brother runs 'Ithilien' — "
        "keep the rivalry section brief and factual."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.assistant_model,
            max_tokens=2500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Weekly outlook generation failed: {e}")
        return f"**Weekly outlook failed:** {e}"
