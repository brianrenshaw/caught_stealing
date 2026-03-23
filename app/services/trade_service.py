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

from app.models.player import Player
from app.models.player_points import PlayerPoints
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
            .outerjoin(
                PlayerPoints,
                (PlayerPoints.player_id == Player.id)
                & (PlayerPoints.season == season)
                & (PlayerPoints.period == "full_season"),
            )
            .where(Player.id == player_id)
        )
        row = result.first()
        if row:
            player, pp = row
            info = {
                "player_id": player.id,
                "name": player.name,
                "team": player.team,
                "position": player.position,
                "player_type": pp.player_type if pp else "unknown",
                "surplus_value": (pp.surplus_value or 0.0) if pp else 0.0,
                "projected_points": (pp.projected_ros_points or 0.0) if pp else 0.0,
                "actual_points": (pp.actual_points or 0.0) if pp else 0.0,
                "steamer_ros_points": (pp.steamer_ros_points or 0.0) if pp else 0.0,
                "positional_rank": (pp.positional_rank or 0) if pp else 0,
                "points_per_pa": pp.points_per_pa if pp else None,
                "points_per_ip": pp.points_per_ip if pp else None,
                "points_per_start": pp.points_per_start if pp else None,
                "points_per_appearance": pp.points_per_appearance if pp else None,
                "is_reliever": (pp.points_per_appearance is not None) if pp else False,
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


async def suggest_trades_ai(session: AsyncSession, season: int) -> str:
    """Scan all opponents' rosters and suggest realistic trade targets using AI.

    Gathers roster data, projections, Statcast trends, and injuries, then
    calls Claude to recommend aggressive, conservative, and watch-list trades.
    Returns markdown-formatted analysis text.
    """
    import anthropic

    from app.config import settings
    from app.models.roster import Roster
    from app.models.statcast_summary import StatcastSummary
    from app.services.mlb_service import build_injury_lookup, get_injuries

    if not settings.anthropic_api_key:
        return "**AI analysis unavailable** — Anthropic API key not configured."

    # ── 1. Load my roster ──────────────────────────────────────────────
    my_result = await session.execute(
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
    my_rows = my_result.all()

    if not my_rows:
        return "**No roster data available.** Sync your Yahoo roster first."

    # Build my roster lines by position
    my_roster_lines: list[str] = []
    pos_points: dict[str, list[float]] = {}
    my_player_ids: set[int] = set()
    for roster, player, pp in my_rows:
        my_player_ids.add(player.id)
        pos = roster.roster_position or player.position or "UTIL"
        proj = pp.projected_ros_points if pp else 0
        steamer = pp.steamer_ros_points if pp else 0
        actual = pp.actual_points if pp else 0
        surplus = pp.surplus_value if pp else 0
        rate_str = ""
        if pp and pp.points_per_pa:
            rate_str = f", {pp.points_per_pa:.1f} pts/PA"
        elif pp and pp.points_per_ip:
            rate_str = f", {pp.points_per_ip:.1f} pts/IP"
        my_roster_lines.append(
            f"  {pos}: {player.name} ({player.team}) — "
            f"App: {proj:.0f}, Steamer: {steamer:.0f}, Actual: {actual:.0f}, "
            f"surplus {surplus:+.0f}{rate_str}"
        )
        pos_points.setdefault(pos, []).append(proj or 0)

    # ── 2. Identify weak spots ─────────────────────────────────────────
    weak_spots: list[str] = []
    total_pts = sum(p for pts_list in pos_points.values() for p in pts_list)
    total_count = sum(len(v) for v in pos_points.values())
    avg_pts = total_pts / max(total_count, 1)
    for pos, pts_list in pos_points.items():
        pos_avg = sum(pts_list) / len(pts_list) if pts_list else 0
        if pos_avg < avg_pts * 0.7:
            weak_spots.append(f"{pos} (avg {pos_avg:.0f} pts, roster avg {avg_pts:.0f})")

    weak_spots_str = "No obvious weak spots identified."
    if weak_spots:
        weak_spots_str = "ROSTER WEAK SPOTS:\n" + "\n".join(f"  {w}" for w in weak_spots)

    # ── 3. Load all opponents' rosters ─────────────────────────────────
    opp_result = await session.execute(
        select(Roster, Player, PlayerPoints)
        .join(Player, Roster.player_id == Player.id)
        .outerjoin(
            PlayerPoints,
            (PlayerPoints.player_id == Player.id)
            & (PlayerPoints.season == season)
            & (PlayerPoints.period == "full_season"),
        )
        .where(Roster.is_my_team.is_(False))
    )
    opp_rows = opp_result.all()

    # Group by team, keep top 8 per team by surplus_value
    teams: dict[str, list[tuple]] = {}
    all_player_ids: set[int] = set(my_player_ids)
    for roster, player, pp in opp_rows:
        team_name = roster.team_name or "Unknown"
        teams.setdefault(team_name, []).append((roster, player, pp))
        all_player_ids.add(player.id)

    opp_lines: list[str] = []
    for team_name, members in sorted(teams.items()):
        members.sort(
            key=lambda x: (x[2].surplus_value if x[2] and x[2].surplus_value else 0),
            reverse=True,
        )
        opp_lines.append(f'  Team: "{team_name}"')
        for roster, player, pp in members[:8]:
            pos = player.position or "UTIL"
            proj = pp.projected_ros_points if pp else 0
            steamer = pp.steamer_ros_points if pp else 0
            actual = pp.actual_points if pp else 0
            surplus = pp.surplus_value if pp else 0
            opp_lines.append(
                f"    {player.name} ({pos}, {player.team}) — "
                f"App: {proj:.0f}, Steamer: {steamer:.0f}, Actual: {actual:.0f}, "
                f"surplus {surplus:+.0f}"
            )

    # ── 4. Injuries ────────────────────────────────────────────────────
    injury_lines: list[str] = []
    try:
        injuries = await get_injuries()
        injury_lookup = build_injury_lookup(injuries)
        for roster, player, _ in list(my_rows) + opp_rows:
            if player.mlbam_id and int(player.mlbam_id) in injury_lookup:
                inj = injury_lookup[int(player.mlbam_id)]
                injury_lines.append(
                    f"  {inj.player_name} ({inj.team}) — {inj.status}: {inj.injury}"
                )
    except Exception as e:
        logger.warning(f"Could not fetch injuries for trade suggestions: {e}")
        injury_lines.append("  Injury data unavailable")

    # ── 5. Projection disagreements (App vs Steamer >20%) ──────────────
    disagree_lines: list[str] = []
    for roster, player, pp in list(my_rows) + opp_rows:
        if not pp or not pp.projected_ros_points or not pp.steamer_ros_points:
            continue
        app_val = pp.projected_ros_points
        steamer_val = pp.steamer_ros_points
        if steamer_val == 0:
            continue
        pct_diff = (app_val - steamer_val) / abs(steamer_val) * 100
        if abs(pct_diff) > 20:
            direction = "higher" if pct_diff > 0 else "lower"
            disagree_lines.append(
                f"  {player.name} — App: {app_val:.0f}, Steamer: {steamer_val:.0f} "
                f"(App {abs(pct_diff):.0f}% {direction})"
            )

    # ── 6. Statcast trends (full_season vs last_14 xwOBA delta) ────────
    statcast_lines: list[str] = []
    try:
        sc_result = await session.execute(
            select(StatcastSummary, Player)
            .join(Player, StatcastSummary.player_id == Player.id)
            .where(
                StatcastSummary.season == season,
                StatcastSummary.period.in_(["full_season", "last_14"]),
                StatcastSummary.player_id.in_(all_player_ids),
            )
        )
        sc_rows = sc_result.all()

        # Group by player
        sc_by_player: dict[int, dict[str, float]] = {}
        sc_names: dict[int, str] = {}
        for sc, player in sc_rows:
            sc_names[sc.player_id] = player.name
            sc_by_player.setdefault(sc.player_id, {})[sc.period] = sc.xwoba or 0

        for pid, periods in sc_by_player.items():
            full = periods.get("full_season", 0)
            recent = periods.get("last_14", 0)
            if full and recent:
                delta = recent - full
                if abs(delta) > 0.020:
                    direction = "UP" if delta > 0 else "DOWN"
                    statcast_lines.append(
                        f"  {sc_names[pid]} — xwOBA {direction} {abs(delta):.3f} "
                        f"(season: {full:.3f}, last 14d: {recent:.3f})"
                    )
    except Exception as e:
        logger.warning(f"Could not fetch Statcast trends: {e}")

    # ── 7. Build scoring line ──────────────────────────────────────────
    scoring_line = (
        "LEAGUE SCORING: H2H Points — "
        "R=1, 1B=1, 2B=2, 3B=3, HR=4, RBI=1, SB=2, "
        "CS=-1, BB=1, HBP=1, K=-0.5 | "
        "OUT=1.5, K(P)=0.5, SV=7, HLD=4, RW=4, QS=2, "
        "ER=-4, BB(P)=-0.75, H(P)=-0.75"
    )

    # ── 8. Assemble user message ───────────────────────────────────────
    user_message = f"""MY ROSTER (by position):
{chr(10).join(my_roster_lines)}

{weak_spots_str}

OPPONENT ROSTERS:
{chr(10).join(opp_lines)}
"""

    if disagree_lines:
        user_message += f"""
PROJECTION DISAGREEMENTS (App vs Steamer diff >20%):
{chr(10).join(disagree_lines)}
"""

    if statcast_lines:
        user_message += f"""
STATCAST TRENDS (last 14 days vs season):
{chr(10).join(statcast_lines)}
"""

    if injury_lines:
        user_message += f"""
INJURY STATUS (Source: MLB Official Injury Report):
{chr(10).join(injury_lines)}
"""

    user_message += f"""
{scoring_line}

Format your response with these sections:
## Verdict
One sentence: should I be trading right now or standing pat?

## Aggressive Move
- **Trade proposal:** [specific players on both sides]
- **Why it works for me:** [bullet points]
- **Why they'd accept:** [bullet points]
- **Projection notes:** [discuss App vs Steamer disagreements]

## Conservative Move
- **Trade proposal:** [specific players]
- **Why it works for me:** [bullet points]
- **Why they'd accept:** [bullet points]

## Keep an Eye On
- **Player 1** — [1 sentence on what to watch for]
- **Player 2** — [1 sentence]"""

    system_prompt = (
        "You are a fantasy baseball analyst for a 10-team H2H Points keeper league.\n"
        "Analyze my roster and all opponents' rosters to suggest realistic trade targets.\n"
        "Focus on REST-OF-SEASON value — trades are long-term moves, not weekly plays.\n\n"
        "You have three projection sources:\n"
        "- App Projected: Our custom model blending actual stats + Statcast expected metrics\n"
        "- Steamer ROS: FanGraphs Steamer rest-of-season projection system\n"
        "- Actual Points: What the player has scored so far this season\n\n"
        "When these projections disagree significantly, explain why and which to trust.\n\n"
        "FORMAT: Use markdown headers (## for sections) and bullet points for all analysis.\n"
        "Keep paragraphs short (2-3 sentences max). Lead with the recommendation, then reasoning.\n"
        "Be honest — if no trade clearly improves my team, say STAND PAT."
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.assistant_model,
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"AI trade suggestion failed: {e}")
        return f"**AI analysis failed:** {e}"


async def analyze_trade_ai(
    session: AsyncSession, evaluation: TradeEvaluation, season: int
) -> str:
    """Provide AI narrative analysis of a specific proposed trade.

    Takes a completed TradeEvaluation (math already done) and enriches it
    with Steamer projections, Statcast trends, injuries, and roster context,
    then calls Claude for a verdict. Returns markdown-formatted analysis text.
    """
    import anthropic

    from app.config import settings
    from app.models.roster import Roster
    from app.models.statcast_summary import StatcastSummary
    from app.services.mlb_service import build_injury_lookup, get_injuries

    if not settings.anthropic_api_key:
        return "**AI analysis unavailable** — Anthropic API key not configured."

    # ── 1. Build trade proposal lines ──────────────────────────────────
    traded_player_ids: set[int] = set()
    side_a_lines: list[str] = []
    for p in evaluation.side_a_players:
        traded_player_ids.add(p["player_id"])
        pos = p.get("position", "UTIL")
        proj = p.get("projected_points", 0)
        actual = p.get("actual_points", 0)
        surplus = p.get("surplus_value", 0)
        side_a_lines.append(
            f"  {p['name']} ({pos}) — App: {proj:.0f}, Actual: {actual:.0f}, "
            f"surplus {surplus:+.0f}"
        )

    side_b_lines: list[str] = []
    for p in evaluation.side_b_players:
        traded_player_ids.add(p["player_id"])
        pos = p.get("position", "UTIL")
        proj = p.get("projected_points", 0)
        actual = p.get("actual_points", 0)
        surplus = p.get("surplus_value", 0)
        side_b_lines.append(
            f"  {p['name']} ({pos}) — App: {proj:.0f}, Actual: {actual:.0f}, "
            f"surplus {surplus:+.0f}"
        )

    # ── 2. Fetch Steamer ROS for traded players ────────────────────────
    for p in evaluation.side_a_players + evaluation.side_b_players:
        pp_result = await session.execute(
            select(PlayerPoints).where(
                PlayerPoints.player_id == p["player_id"],
                PlayerPoints.season == season,
                PlayerPoints.period == "full_season",
            )
        )
        pp_row = pp_result.scalar_one_or_none()
        steamer = pp_row.steamer_ros_points if pp_row and pp_row.steamer_ros_points else 0
        p["steamer_ros_points"] = steamer

    # Update lines with Steamer data
    side_a_lines = []
    for p in evaluation.side_a_players:
        pos = p.get("position", "UTIL")
        proj = p.get("projected_points", 0)
        steamer = p.get("steamer_ros_points", 0)
        actual = p.get("actual_points", 0)
        surplus = p.get("surplus_value", 0)
        side_a_lines.append(
            f"  {p['name']} ({pos}) — App: {proj:.0f}, Steamer: {steamer:.0f}, "
            f"Actual: {actual:.0f}, surplus {surplus:+.0f}"
        )

    side_b_lines = []
    for p in evaluation.side_b_players:
        pos = p.get("position", "UTIL")
        proj = p.get("projected_points", 0)
        steamer = p.get("steamer_ros_points", 0)
        actual = p.get("actual_points", 0)
        surplus = p.get("surplus_value", 0)
        side_b_lines.append(
            f"  {p['name']} ({pos}) — App: {proj:.0f}, Steamer: {steamer:.0f}, "
            f"Actual: {actual:.0f}, surplus {surplus:+.0f}"
        )

    # ── 3. Math evaluation summary ─────────────────────────────────────
    math_lines: list[str] = [
        f"  Value difference: {evaluation.value_difference:.0f} pts — {evaluation.fairness}"
    ]
    if evaluation.points_analysis.get("insights"):
        for insight in evaluation.points_analysis["insights"]:
            math_lines.append(f"  {insight}")

    # ── 4. Load my roster for context ──────────────────────────────────
    my_result = await session.execute(
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
    my_rows = my_result.all()

    my_roster_lines: list[str] = []
    pos_points: dict[str, list[float]] = {}
    for roster, player, pp in my_rows:
        pos = roster.roster_position or player.position or "UTIL"
        proj = pp.projected_ros_points if pp else 0
        steamer = pp.steamer_ros_points if pp else 0
        actual = pp.actual_points if pp else 0
        my_roster_lines.append(
            f"  {pos}: {player.name} ({player.team}) — "
            f"App: {proj:.0f}, Steamer: {steamer:.0f}, Actual: {actual:.0f}"
        )
        pos_points.setdefault(pos, []).append(proj or 0)

    # ── 5. Weak spots ──────────────────────────────────────────────────
    weak_spots: list[str] = []
    total_pts = sum(p for pts_list in pos_points.values() for p in pts_list)
    total_count = sum(len(v) for v in pos_points.values())
    avg_pts = total_pts / max(total_count, 1)
    for pos, pts_list in pos_points.items():
        pos_avg = sum(pts_list) / len(pts_list) if pts_list else 0
        if pos_avg < avg_pts * 0.7:
            weak_spots.append(f"{pos} (avg {pos_avg:.0f} pts, roster avg {avg_pts:.0f})")

    weak_spots_str = "No obvious weak spots identified."
    if weak_spots:
        weak_spots_str = "ROSTER WEAK SPOTS:\n" + "\n".join(f"  {w}" for w in weak_spots)

    # ── 6. Injuries for traded players ─────────────────────────────────
    injury_lines: list[str] = []
    try:
        injuries = await get_injuries()
        injury_lookup = build_injury_lookup(injuries)
        for p in evaluation.side_a_players + evaluation.side_b_players:
            # Look up mlbam_id from Player table
            p_result = await session.execute(
                select(Player).where(Player.id == p["player_id"])
            )
            player_obj = p_result.scalar_one_or_none()
            if player_obj and player_obj.mlbam_id and int(player_obj.mlbam_id) in injury_lookup:
                inj = injury_lookup[int(player_obj.mlbam_id)]
                injury_lines.append(
                    f"  {inj.player_name} ({inj.team}) — {inj.status}: {inj.injury}"
                )
    except Exception as e:
        logger.warning(f"Could not fetch injuries for trade analysis: {e}")
        injury_lines.append("  Injury data unavailable")

    # ── 7. Statcast trends for traded players ──────────────────────────
    statcast_lines: list[str] = []
    try:
        sc_result = await session.execute(
            select(StatcastSummary, Player)
            .join(Player, StatcastSummary.player_id == Player.id)
            .where(
                StatcastSummary.season == season,
                StatcastSummary.period.in_(["full_season", "last_14"]),
                StatcastSummary.player_id.in_(traded_player_ids),
            )
        )
        sc_rows = sc_result.all()

        sc_by_player: dict[int, dict[str, float]] = {}
        sc_names: dict[int, str] = {}
        for sc, player in sc_rows:
            sc_names[sc.player_id] = player.name
            sc_by_player.setdefault(sc.player_id, {})[sc.period] = sc.xwoba or 0

        for pid, periods in sc_by_player.items():
            full = periods.get("full_season", 0)
            recent = periods.get("last_14", 0)
            if full and recent:
                delta = recent - full
                direction = "UP" if delta > 0 else "DOWN"
                statcast_lines.append(
                    f"  {sc_names[pid]} — xwOBA {direction} {abs(delta):.3f} "
                    f"(season: {full:.3f}, last 14d: {recent:.3f})"
                )
    except Exception as e:
        logger.warning(f"Could not fetch Statcast trends for trade analysis: {e}")

    # ── 8. Scoring line ────────────────────────────────────────────────
    scoring_line = (
        "LEAGUE SCORING: H2H Points — "
        "R=1, 1B=1, 2B=2, 3B=3, HR=4, RBI=1, SB=2, "
        "CS=-1, BB=1, HBP=1, K=-0.5 | "
        "OUT=1.5, K(P)=0.5, SV=7, HLD=4, RW=4, QS=2, "
        "ER=-4, BB(P)=-0.75, H(P)=-0.75"
    )

    # ── 9. Assemble user message ───────────────────────────────────────
    user_message = f"""TRADE PROPOSAL:
  Side A gives up:
{chr(10).join(side_a_lines)}
  Side B gives up:
{chr(10).join(side_b_lines)}

MATHEMATICAL EVALUATION:
{chr(10).join(math_lines)}

MY CURRENT ROSTER:
{chr(10).join(my_roster_lines)}

{weak_spots_str}
"""

    if statcast_lines:
        user_message += f"""
STATCAST TRENDS FOR TRADED PLAYERS:
{chr(10).join(statcast_lines)}
"""

    if injury_lines:
        user_message += f"""
INJURY STATUS:
{chr(10).join(injury_lines)}
"""

    user_message += f"""
{scoring_line}

Format your response as:
## Verdict
**[ACCEPT/REJECT/CLOSE CALL]** — one sentence summary.

## Key Factors
- [bullet point for each major factor]

## Projection Analysis
- [compare App vs Steamer for key players]

## Roster Fit
- [how this trade affects my lineup]

## Risk Assessment
- [injury concerns, regression risks, etc.]"""

    system_prompt = (
        "You are a fantasy baseball analyst for a 10-team H2H Points keeper league.\n"
        "Evaluate this specific trade from MY team's perspective. "
        "Focus on REST-OF-SEASON value.\n\n"
        "FORMAT: Use markdown headers (## for sections) and bullet points for all analysis.\n"
        "Lead with your verdict in bold, then explain WHY using bullet points.\n"
        "Keep paragraphs short. Consider roster fit, positional scarcity, Statcast trends,\n"
        "projection disagreements, and injury risk."
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
        logger.error(f"AI trade analysis failed: {e}")
        return f"**AI analysis failed:** {e}"
