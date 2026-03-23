"""Tool definitions and handlers for the AI assistant.

Each tool maps to a database query via existing services.
Handlers return dicts that serialize to JSON for the Anthropic API.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.statcast_summary import StatcastSummary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Player name lookup helper
# ---------------------------------------------------------------------------


async def find_player(session: AsyncSession, name: str) -> dict:
    """Search for a player by name. Returns match info dict.

    - Single match: {"found": True, "player": Player, "multiple": False}
    - Multiple matches: {"found": True, "players": [...], "multiple": True}
    - No match: {"found": False, "error": "..."}
    """
    result = await session.execute(select(Player).where(Player.name.ilike(f"%{name}%")))
    players = result.scalars().all()

    if not players:
        return {
            "found": False,
            "error": f"No player found matching '{name}'",
        }

    # Prefer exact match
    for p in players:
        if p.name.lower() == name.lower():
            return {"found": True, "player": p, "multiple": False}

    if len(players) == 1:
        return {"found": True, "player": players[0], "multiple": False}

    # Multiple matches — return list for disambiguation
    return {
        "found": True,
        "multiple": True,
        "players": [
            {"id": p.id, "name": p.name, "team": p.team, "position": p.position}
            for p in players[:5]
        ],
    }


def _player_info(player: Player) -> dict:
    return {
        "player_id": player.id,
        "name": player.name,
        "team": player.team,
        "position": player.position,
    }


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def handle_get_player_stats(
    session: AsyncSession,
    player_name: str,
    period: str = "full_season",
    stat_type: str = "auto",
) -> dict:
    """Get a player's batting or pitching stats and Statcast metrics."""
    season = date.today().year
    lookup = await find_player(session, player_name)
    if not lookup["found"]:
        return lookup
    if lookup["multiple"]:
        return {
            "multiple_matches": lookup["players"],
            "message": "Multiple players found. Please specify which one.",
        }

    player = lookup["player"]
    result_data = _player_info(player)
    result_data["period"] = period

    # Determine stat type
    pos = (player.position or "").upper()
    is_pitcher = stat_type == "pitching" or (stat_type == "auto" and pos in ("SP", "RP", "P"))

    if is_pitcher:
        res = await session.execute(
            select(PitchingStats).where(
                PitchingStats.player_id == player.id,
                PitchingStats.period == period,
                PitchingStats.season == season,
            )
        )
        stats = res.scalar_one_or_none()
        if stats:
            result_data["pitching_stats"] = {
                "w": stats.w,
                "l": stats.l,
                "sv": stats.sv,
                "g": stats.g,
                "gs": stats.gs,
                "ip": stats.ip,
                "so": stats.so,
                "bb": stats.bb,
                "era": stats.era,
                "whip": stats.whip,
                "k_per_9": stats.k_per_9,
                "bb_per_9": stats.bb_per_9,
                "fip": stats.fip,
                "xfip": stats.xfip,
            }
        else:
            result_data["pitching_stats"] = None
    else:
        res = await session.execute(
            select(BattingStats).where(
                BattingStats.player_id == player.id,
                BattingStats.period == period,
                BattingStats.season == season,
            )
        )
        stats = res.scalar_one_or_none()
        if stats:
            result_data["batting_stats"] = {
                "pa": stats.pa,
                "ab": stats.ab,
                "h": stats.h,
                "hr": stats.hr,
                "r": stats.r,
                "rbi": stats.rbi,
                "sb": stats.sb,
                "bb": stats.bb,
                "so": stats.so,
                "avg": stats.avg,
                "obp": stats.obp,
                "slg": stats.slg,
                "ops": stats.ops,
                "woba": stats.woba,
                "wrc_plus": stats.wrc_plus,
            }
        else:
            result_data["batting_stats"] = None

    # Statcast summary
    sc_type = "pitcher" if is_pitcher else "batter"
    res = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == player.id,
            StatcastSummary.period == period,
            StatcastSummary.season == season,
            StatcastSummary.player_type == sc_type,
        )
    )
    sc = res.scalar_one_or_none()
    if sc:
        result_data["statcast"] = {
            "xba": sc.xba,
            "xslg": sc.xslg,
            "xwoba": sc.xwoba,
            "avg_exit_velo": sc.avg_exit_velo,
            "max_exit_velo": sc.max_exit_velo,
            "barrel_pct": sc.barrel_pct,
            "hard_hit_pct": sc.hard_hit_pct,
            "sweet_spot_pct": sc.sweet_spot_pct,
        }
    else:
        result_data["statcast"] = None

    return result_data


async def handle_get_player_projection(
    session: AsyncSession,
    player_name: str,
) -> dict:
    """Get a player's rest-of-season projection with buy/sell signals."""
    from app.services.projection_service import project_hitter, project_pitcher

    season = date.today().year
    lookup = await find_player(session, player_name)
    if not lookup["found"]:
        return lookup
    if lookup["multiple"]:
        return {
            "multiple_matches": lookup["players"],
            "message": "Multiple players found. Please specify which one.",
        }

    player = lookup["player"]
    pos = (player.position or "").upper()

    if pos in ("SP", "RP", "P"):
        proj = await project_pitcher(session, player, season)
        if not proj:
            return {**_player_info(player), "error": "Insufficient data for projection"}
        return {
            **_player_info(player),
            "projection_type": "pitcher",
            "ros_projection": {
                "w": proj.projected_w,
                "sv": proj.projected_sv,
                "k": proj.projected_k,
                "era": proj.projected_era,
                "whip": proj.projected_whip,
            },
            "confidence_score": proj.confidence_score,
            "buy_low": proj.buy_low_signal,
            "sell_high": proj.sell_high_signal,
            "xwoba_delta": proj.xwoba_delta,
        }
    else:
        proj = await project_hitter(session, player, season)
        if not proj:
            return {**_player_info(player), "error": "Insufficient data for projection"}
        return {
            **_player_info(player),
            "projection_type": "hitter",
            "ros_projection": {
                "hr": proj.projected_hr,
                "r": proj.projected_r,
                "rbi": proj.projected_rbi,
                "sb": proj.projected_sb,
                "avg": proj.projected_avg,
                "obp": proj.projected_obp,
                "slg": proj.projected_slg,
                "ops": proj.projected_ops,
            },
            "confidence_score": proj.confidence_score,
            "buy_low": proj.buy_low_signal,
            "sell_high": proj.sell_high_signal,
            "xwoba_delta": proj.xwoba_delta,
        }


async def handle_get_position_rankings(
    session: AsyncSession,
    position: str,
    scoring_type: str = "roto",
    limit: int = 20,
) -> dict:
    """Get ranked players at a specific position."""
    from app.services.rankings_service import get_position_rankings

    season = date.today().year
    ranked = await get_position_rankings(session, position, season, scoring_type, limit=limit)
    return {
        "position": position,
        "scoring_type": scoring_type,
        "players": [
            {
                "rank": r.position_rank,
                "name": r.name,
                "team": r.team,
                "overall_rank": r.overall_rank,
                "composite_score": r.composite_score,
                "value_above_replacement": r.value_above_replacement,
                "buy_low": r.buy_low,
                "sell_high": r.sell_high,
                "trend": r.trend,
            }
            for r in ranked
        ],
    }


async def handle_get_matchup_info(
    session: AsyncSession,
    game_date: str | None = None,
) -> dict:
    """Get today's game schedule, streaming picks, and hitter stacks."""
    from app.services.matchup_service import get_stacks, get_streaming_pitchers
    from app.services.mlb_service import get_schedule

    if game_date and game_date != "today":
        dt = date.fromisoformat(game_date)
    else:
        dt = date.today()

    season = dt.year
    schedule = await get_schedule(dt)
    streaming = await get_streaming_pitchers(session, dt, season, limit=5)
    stacks = await get_stacks(session, dt, limit=5)

    return {
        "date": dt.isoformat(),
        "games": [
            {
                "away_team": g.away_team,
                "home_team": g.home_team,
                "status": g.status,
                "away_pitcher": g.away_pitcher,
                "home_pitcher": g.home_pitcher,
            }
            for g in schedule
        ],
        "top_streaming_picks": [
            {
                "name": s.name,
                "team": s.team,
                "opponent": s.opponent,
                "park": s.park,
                "streaming_score": s.streaming_score,
                "projected_k": s.projected_k,
                "reasoning": s.reasoning,
            }
            for s in streaming
        ],
        "top_stacks": [
            {
                "team": s.team,
                "opponent_pitcher": s.opponent_pitcher,
                "stack_score": s.stack_score,
                "reasoning": s.reasoning,
            }
            for s in stacks
        ],
    }


async def handle_get_head_to_head(
    session: AsyncSession,
    batter_name: str,
    pitcher_name: str,
) -> dict:
    """Get head-to-head matchup data between a batter and pitcher.

    Since we don't store pitch-level data, this returns overall season stats
    for both players as a fallback.
    """
    season = date.today().year

    batter_lookup = await find_player(session, batter_name)
    pitcher_lookup = await find_player(session, pitcher_name)

    if not batter_lookup["found"]:
        return {"error": f"Batter not found: {batter_name}"}
    if not pitcher_lookup["found"]:
        return {"error": f"Pitcher not found: {pitcher_name}"}
    if batter_lookup["multiple"]:
        return {"error": "Multiple batters matched", "matches": batter_lookup["players"]}
    if pitcher_lookup["multiple"]:
        return {"error": "Multiple pitchers matched", "matches": pitcher_lookup["players"]}

    batter = batter_lookup["player"]
    pitcher = pitcher_lookup["player"]

    # Get batter's season stats
    b_res = await session.execute(
        select(BattingStats).where(
            BattingStats.player_id == batter.id,
            BattingStats.period == "full_season",
            BattingStats.season == season,
        )
    )
    b_stats = b_res.scalar_one_or_none()

    # Get pitcher's season stats
    p_res = await session.execute(
        select(PitchingStats).where(
            PitchingStats.player_id == pitcher.id,
            PitchingStats.period == "full_season",
            PitchingStats.season == season,
        )
    )
    p_stats = p_res.scalar_one_or_none()

    # Get Statcast for both
    b_sc_res = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == batter.id,
            StatcastSummary.period == "full_season",
            StatcastSummary.season == season,
            StatcastSummary.player_type == "batter",
        )
    )
    b_sc = b_sc_res.scalar_one_or_none()

    p_sc_res = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == pitcher.id,
            StatcastSummary.period == "full_season",
            StatcastSummary.season == season,
            StatcastSummary.player_type == "pitcher",
        )
    )
    p_sc = p_sc_res.scalar_one_or_none()

    return {
        "batter": _player_info(batter),
        "pitcher": _player_info(pitcher),
        "data_source": "overall_season_fallback",
        "note": (
            "Direct head-to-head matchup data is not available. "
            "Showing overall season stats for context."
        ),
        "batter_stats": {
            "avg": b_stats.avg if b_stats else None,
            "ops": b_stats.ops if b_stats else None,
            "woba": b_stats.woba if b_stats else None,
            "hr": b_stats.hr if b_stats else None,
            "so": b_stats.so if b_stats else None,
            "xwoba": b_sc.xwoba if b_sc else None,
            "barrel_pct": b_sc.barrel_pct if b_sc else None,
            "avg_exit_velo": b_sc.avg_exit_velo if b_sc else None,
        },
        "pitcher_stats": {
            "era": p_stats.era if p_stats else None,
            "whip": p_stats.whip if p_stats else None,
            "k_per_9": p_stats.k_per_9 if p_stats else None,
            "fip": p_stats.fip if p_stats else None,
            "xwoba_against": p_sc.xwoba if p_sc else None,
            "barrel_pct_against": p_sc.barrel_pct if p_sc else None,
        },
    }


async def handle_compare_players(
    session: AsyncSession,
    player_names: list[str],
) -> dict:
    """Compare 2-5 players side by side with stats and projections."""
    from app.services.projection_service import project_hitter, project_pitcher

    season = date.today().year
    players_data = []

    for name in player_names[:5]:
        lookup = await find_player(session, name)
        if not lookup["found"] or lookup["multiple"]:
            players_data.append({"name": name, "error": "Player not found or ambiguous"})
            continue

        player = lookup["player"]
        info = _player_info(player)
        pos = (player.position or "").upper()

        # Get stats
        if pos in ("SP", "RP", "P"):
            res = await session.execute(
                select(PitchingStats).where(
                    PitchingStats.player_id == player.id,
                    PitchingStats.period == "full_season",
                    PitchingStats.season == season,
                )
            )
            stats = res.scalar_one_or_none()
            if stats:
                info["stats"] = {
                    "ip": stats.ip,
                    "era": stats.era,
                    "whip": stats.whip,
                    "so": stats.so,
                    "k_per_9": stats.k_per_9,
                    "fip": stats.fip,
                }
            proj = await project_pitcher(session, player, season)
            if proj:
                info["projection"] = {
                    "w": proj.projected_w,
                    "k": proj.projected_k,
                    "era": proj.projected_era,
                    "whip": proj.projected_whip,
                }
                info["confidence"] = proj.confidence_score
        else:
            res = await session.execute(
                select(BattingStats).where(
                    BattingStats.player_id == player.id,
                    BattingStats.period == "full_season",
                    BattingStats.season == season,
                )
            )
            stats = res.scalar_one_or_none()
            if stats:
                info["stats"] = {
                    "pa": stats.pa,
                    "avg": stats.avg,
                    "hr": stats.hr,
                    "rbi": stats.rbi,
                    "sb": stats.sb,
                    "ops": stats.ops,
                    "woba": stats.woba,
                    "wrc_plus": stats.wrc_plus,
                }
            proj = await project_hitter(session, player, season)
            if proj:
                info["projection"] = {
                    "hr": proj.projected_hr,
                    "r": proj.projected_r,
                    "rbi": proj.projected_rbi,
                    "avg": proj.projected_avg,
                }
                info["buy_low"] = proj.buy_low_signal
                info["sell_high"] = proj.sell_high_signal
                info["xwoba_delta"] = proj.xwoba_delta
                info["confidence"] = proj.confidence_score

        # Statcast
        sc_type = "pitcher" if pos in ("SP", "RP", "P") else "batter"
        res = await session.execute(
            select(StatcastSummary).where(
                StatcastSummary.player_id == player.id,
                StatcastSummary.period == "full_season",
                StatcastSummary.season == season,
                StatcastSummary.player_type == sc_type,
            )
        )
        sc = res.scalar_one_or_none()
        if sc:
            info["statcast"] = {
                "xba": sc.xba,
                "xwoba": sc.xwoba,
                "barrel_pct": sc.barrel_pct,
                "hard_hit_pct": sc.hard_hit_pct,
            }

        players_data.append(info)

    return {"players": players_data}


async def handle_get_waiver_recommendations(
    session: AsyncSession,
    position: str | None = None,
    limit: int = 15,
) -> dict:
    """Get waiver wire pickup recommendations."""
    from app.services.waiver_service import score_free_agents

    season = date.today().year
    recs = await score_free_agents(session, season, limit=limit)

    if position:
        recs = [r for r in recs if r.position and position in r.position]

    return {
        "position_filter": position,
        "recommendations": [
            {
                "name": r.name,
                "team": r.team,
                "position": r.position,
                "waiver_score": r.waiver_score,
                "trend": r.trend,
                "buy_low": r.buy_low,
                "xwoba_delta": r.xwoba_delta,
                "reasoning": r.reasoning,
            }
            for r in recs
        ],
    }


async def handle_get_team_schedule(
    session: AsyncSession,
    team: str,
    days_ahead: int = 7,
) -> dict:
    """Get upcoming schedule for an MLB team."""
    from app.services.mlb_service import get_schedule

    games = []
    start = date.today()
    for i in range(days_ahead):
        dt = start + timedelta(days=i)
        day_games = await get_schedule(dt)
        for g in day_games:
            if team.lower() in g.away_team.lower() or team.lower() in g.home_team.lower():
                games.append(
                    {
                        "date": g.game_date,
                        "away_team": g.away_team,
                        "home_team": g.home_team,
                        "away_pitcher": g.away_pitcher,
                        "home_pitcher": g.home_pitcher,
                        "status": g.status,
                    }
                )

    return {"team": team, "days_ahead": days_ahead, "games": games}


async def handle_evaluate_trade(
    session: AsyncSession,
    giving_away: list[str],
    receiving: list[str],
) -> dict:
    """Evaluate a fantasy trade by comparing surplus values."""
    from app.services.trade_service import calculate_trade_values, evaluate_trade

    season = date.today().year

    # Ensure trade values exist
    await calculate_trade_values(session, season)

    # Resolve player names to IDs
    side_a_ids = []
    side_b_ids = []
    errors = []

    for name in giving_away:
        lookup = await find_player(session, name)
        if lookup["found"] and not lookup["multiple"]:
            side_a_ids.append(lookup["player"].id)
        else:
            errors.append(f"Could not find player: {name}")

    for name in receiving:
        lookup = await find_player(session, name)
        if lookup["found"] and not lookup["multiple"]:
            side_b_ids.append(lookup["player"].id)
        else:
            errors.append(f"Could not find player: {name}")

    if errors:
        return {"error": "Some players not found", "details": errors}

    if not side_a_ids or not side_b_ids:
        return {"error": "Need at least one player on each side"}

    result = await evaluate_trade(session, side_a_ids, side_b_ids, season)

    net = result.side_b_total_value - result.side_a_total_value
    if abs(net) < 0.5:
        verdict = "close"
    elif net > 0:
        verdict = "accept"
    else:
        verdict = "reject"

    return {
        "giving_away": result.side_a_players,
        "receiving": result.side_b_players,
        "giving_total_value": result.side_a_total_value,
        "receiving_total_value": result.side_b_total_value,
        "net_value": round(net, 2),
        "verdict": verdict,
        "fairness": result.fairness,
        "scoring_type": result.scoring_type,
        "points_analysis": result.points_analysis,
    }


async def handle_get_player_points(
    session: AsyncSession,
    player_name: str,
) -> dict:
    """Get a player's fantasy points data for this league's scoring system."""
    from app.models.player_points import PlayerPoints

    lookup = await find_player(session, player_name)
    if not lookup["found"]:
        return lookup
    if lookup["multiple"]:
        return {"multiple_matches": lookup["players"]}

    player = lookup["player"]
    season = date.today().year

    pp_result = await session.execute(
        select(PlayerPoints).where(
            PlayerPoints.player_id == player.id,
            PlayerPoints.season == season,
            PlayerPoints.period == "full_season",
        )
    )
    pp = pp_result.scalar_one_or_none()

    if not pp:
        return {
            "player": player.name,
            "error": "No points data available. Run the points calculation first.",
        }

    return {
        "player": player.name,
        "team": player.team,
        "position": player.position,
        "player_type": pp.player_type,
        "actual_points": pp.actual_points,
        "projected_ros_points": pp.projected_ros_points,
        "points_per_pa": pp.points_per_pa,
        "points_per_ip": pp.points_per_ip,
        "points_per_start": pp.points_per_start,
        "points_per_appearance": pp.points_per_appearance,
        "positional_rank": pp.positional_rank,
        "surplus_value": pp.surplus_value,
        "scoring_note": (
            "This league: SV=7, HLD=4, RW=4, OUT=1.5, K(pitcher)=0.5, "
            "ER=-4, H(pitcher)=-0.75, BB(pitcher)=-0.75, "
            "HR=4, 1B=1, 2B=2, 3B=3, R=1, RBI=1, SB=2, BB=1, K(batter)=-0.5"
        ),
    }


async def handle_get_scoring_config(
    session: AsyncSession,
) -> dict:
    """Return the league scoring configuration."""
    from app.league_config import LEAGUE_CONFIG

    return {
        "league": LEAGUE_CONFIG["league_name"],
        "scoring_type": LEAGUE_CONFIG["scoring_type"],
        "teams": LEAGUE_CONFIG["teams"],
        "keeper": LEAGUE_CONFIG["keeper"],
        "batting_scoring": LEAGUE_CONFIG["batting_scoring"],
        "pitching_scoring": LEAGUE_CONFIG["pitching_scoring"],
        "roster_slots": LEAGUE_CONFIG["roster_slots"],
        "key_insights": [
            "Saves = 7 pts — elite closers are premium assets",
            "Holds = 4 pts — setup men have real value",
            "Each out = 1.5 pts (IP = 4.5) — innings eaters are gold",
            "ER = -4 pts — blowups are devastating, avoid volatile starters",
            "Batter K = -0.5 — contact hitters gain edge over TTO sluggers",
            "BB = 1 pt — walks are free points, high-OBP hitters undervalued",
            "4 flexible P slots — can load SP or RP based on matchups",
        ],
    }


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic API format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "get_player_stats",
        "description": (
            "Get a player's batting or pitching stats and Statcast metrics "
            "for a specified time period. Use this when the user asks about "
            "how a player is performing, what their stats are, or any "
            "question requiring current statistical data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {
                    "type": "string",
                    "description": "Full or partial player name to search for",
                },
                "period": {
                    "type": "string",
                    "enum": ["full_season", "last_30", "last_14", "last_7"],
                    "description": "Time period for the stats. Default is full_season.",
                },
                "stat_type": {
                    "type": "string",
                    "enum": ["batting", "pitching", "auto"],
                    "description": (
                        "Whether to pull batting or pitching stats. "
                        "'auto' detects based on the player's primary position."
                    ),
                },
            },
            "required": ["player_name"],
        },
    },
    {
        "name": "get_player_projection",
        "description": (
            "Get a player's rest-of-season projection including projected "
            "stats, confidence score, and buy-low/sell-high signals based "
            "on Statcast expected stats vs actual performance. Use this when "
            "the user asks about a player's ROS outlook or trade value."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {
                    "type": "string",
                    "description": "Full or partial player name to search for",
                },
            },
            "required": ["player_name"],
        },
    },
    {
        "name": "get_position_rankings",
        "description": (
            "Get ranked players at a specific fantasy baseball position. "
            "Use this when the user asks who the best players are at a "
            "position, or wants to see position rankings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "position": {
                    "type": "string",
                    "enum": ["C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "DH"],
                    "description": "The position to get rankings for",
                },
                "scoring_type": {
                    "type": "string",
                    "enum": ["roto", "points"],
                    "description": "Scoring format. Default is roto.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of players to return. Default is 20.",
                },
            },
            "required": ["position"],
        },
    },
    {
        "name": "get_matchup_info",
        "description": (
            "Get today's MLB game schedule with probable pitchers, "
            "streaming pitcher recommendations, and hitter stack "
            "recommendations. Use this when the user asks about today's "
            "games, who to stream, or which offenses to target."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "game_date": {
                    "type": "string",
                    "description": ("Date in YYYY-MM-DD format, or 'today'. Default is today."),
                },
            },
        },
    },
    {
        "name": "get_head_to_head",
        "description": (
            "Get matchup context between a specific batter and pitcher. "
            "Returns overall season stats for both players since direct "
            "head-to-head data is not tracked. Use this for start/sit "
            "decisions involving a specific pitcher matchup."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "batter_name": {
                    "type": "string",
                    "description": "The batter's name",
                },
                "pitcher_name": {
                    "type": "string",
                    "description": "The pitcher's name",
                },
            },
            "required": ["batter_name", "pitcher_name"],
        },
    },
    {
        "name": "compare_players",
        "description": (
            "Compare 2 to 5 players side by side with their current stats, "
            "Statcast metrics, and projections. Use this when the user wants "
            "to compare players or decide between options."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 5,
                    "description": "List of player names to compare",
                },
            },
            "required": ["player_names"],
        },
    },
    {
        "name": "get_waiver_recommendations",
        "description": (
            "Get waiver wire pickup recommendations based on projections, "
            "recent trends, and positional scarcity. Use this when the user "
            "asks about waiver adds, pickups, or free agents to target."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "position": {
                    "type": "string",
                    "enum": ["C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "DH"],
                    "description": "Filter by position. Omit for all positions.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of recommendations. Default is 15.",
                },
            },
        },
    },
    {
        "name": "get_team_schedule",
        "description": (
            "Get an MLB team's upcoming schedule with opponents and "
            "probable pitchers. Use this when the user asks about a team's "
            "schedule or upcoming matchups."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {
                    "type": "string",
                    "description": (
                        "Team name or abbreviation (e.g., 'Yankees', 'NYY', 'New York Yankees')"
                    ),
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Number of days to look ahead. Default is 7.",
                },
            },
            "required": ["team"],
        },
    },
    {
        "name": "evaluate_trade",
        "description": (
            "Evaluate a fantasy baseball trade by comparing the projected "
            "fantasy points surplus value of players on both sides. Returns "
            "league-specific analysis including points breakdown, reliever "
            "premium, and innings value. Use this when the user asks about "
            "a specific trade or wants to know if a trade is fair."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "giving_away": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Player names the user would trade away",
                },
                "receiving": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Player names the user would receive",
                },
            },
            "required": ["giving_away", "receiving"],
        },
    },
    {
        "name": "get_player_points",
        "description": (
            "Get a player's projected fantasy points breakdown for this "
            "H2H Points league (SV=7, HLD=4, OUT=1.5, ER=-4, K=-0.5). "
            "Returns actual points, projected ROS points, points per PA "
            "(hitters) or points per IP/start/appearance (pitchers), and "
            "surplus value above replacement. Use this when the user asks "
            "about a player's fantasy points value or ranking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {
                    "type": "string",
                    "description": "Full or partial player name to search for",
                },
            },
            "required": ["player_name"],
        },
    },
    {
        "name": "get_scoring_config",
        "description": (
            "Get the league's scoring rules and configuration including "
            "point values for all stats, roster slots, and strategic "
            "insights. Use this when the user asks about the scoring "
            "system or how specific stats are valued."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

# Handler registry: tool name → async handler function
TOOL_HANDLERS = {
    "get_player_stats": handle_get_player_stats,
    "get_player_projection": handle_get_player_projection,
    "get_position_rankings": handle_get_position_rankings,
    "get_matchup_info": handle_get_matchup_info,
    "get_head_to_head": handle_get_head_to_head,
    "compare_players": handle_compare_players,
    "get_waiver_recommendations": handle_get_waiver_recommendations,
    "get_team_schedule": handle_get_team_schedule,
    "evaluate_trade": handle_evaluate_trade,
    "get_player_points": handle_get_player_points,
    "get_scoring_config": handle_get_scoring_config,
}
