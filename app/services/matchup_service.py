"""Daily matchup analysis: streaming pitchers, hitter stacks, two-start pitchers."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.statcast_summary import StatcastSummary
from app.services.mlb_service import get_probable_pitchers

logger = logging.getLogger(__name__)

# Park factors (run environment relative to league average = 1.00)
# Values > 1.00 favor hitters, < 1.00 favor pitchers
PARK_FACTORS: dict[str, float] = {
    "Coors Field": 1.38,
    "Great American Ball Park": 1.12,
    "Fenway Park": 1.09,
    "Globe Life Field": 1.08,
    "Yankee Stadium": 1.07,
    "Wrigley Field": 1.05,
    "Citizens Bank Park": 1.05,
    "Nationals Park": 1.02,
    "Chase Field": 1.01,
    "Angel Stadium": 1.00,
    "Guaranteed Rate Field": 1.00,
    "Minute Maid Park": 0.99,
    "Rogers Centre": 0.99,
    "Progressive Field": 0.98,
    "Target Field": 0.98,
    "Oriole Park at Camden Yards": 0.98,
    "Comerica Park": 0.97,
    "Kauffman Stadium": 0.97,
    "PNC Park": 0.96,
    "Busch Stadium": 0.96,
    "Truist Park": 0.96,
    "American Family Field": 0.96,
    "loanDepot park": 0.95,
    "Tropicana Field": 0.95,
    "Dodger Stadium": 0.95,
    "Citi Field": 0.94,
    "T-Mobile Park": 0.94,
    "Petco Park": 0.93,
    "Oracle Park": 0.92,
    "Oakland Coliseum": 0.91,
}

# Team abbreviation → home park mapping
TEAM_PARKS: dict[str, str] = {
    "Colorado Rockies": "Coors Field",
    "Cincinnati Reds": "Great American Ball Park",
    "Boston Red Sox": "Fenway Park",
    "Texas Rangers": "Globe Life Field",
    "New York Yankees": "Yankee Stadium",
    "Chicago Cubs": "Wrigley Field",
    "Philadelphia Phillies": "Citizens Bank Park",
    "Washington Nationals": "Nationals Park",
    "Arizona Diamondbacks": "Chase Field",
    "Los Angeles Angels": "Angel Stadium",
    "Chicago White Sox": "Guaranteed Rate Field",
    "Houston Astros": "Minute Maid Park",
    "Toronto Blue Jays": "Rogers Centre",
    "Cleveland Guardians": "Progressive Field",
    "Minnesota Twins": "Target Field",
    "Baltimore Orioles": "Oriole Park at Camden Yards",
    "Detroit Tigers": "Comerica Park",
    "Kansas City Royals": "Kauffman Stadium",
    "Pittsburgh Pirates": "PNC Park",
    "St. Louis Cardinals": "Busch Stadium",
    "Atlanta Braves": "Truist Park",
    "Milwaukee Brewers": "American Family Field",
    "Miami Marlins": "loanDepot park",
    "Tampa Bay Rays": "Tropicana Field",
    "Los Angeles Dodgers": "Dodger Stadium",
    "New York Mets": "Citi Field",
    "Seattle Mariners": "T-Mobile Park",
    "San Diego Padres": "Petco Park",
    "San Francisco Giants": "Oracle Park",
    "Oakland Athletics": "Oakland Coliseum",
}


@dataclass
class StreamingPick:
    player_id: int | None
    name: str
    team: str
    opponent: str
    park: str
    streaming_score: float  # 0-100
    projected_k: float
    projected_era_for_start: float
    reasoning: str


@dataclass
class StackRecommendation:
    team: str
    opponent_pitcher: str | None
    park: str
    stack_score: float  # 0-100
    reasoning: str


@dataclass
class TwoStartPitcher:
    player_id: int | None
    name: str
    team: str
    start_1_opponent: str
    start_2_opponent: str
    combined_score: float
    reasoning: str


def _get_park_factor(home_team: str) -> float:
    """Get park factor for a given home team."""
    park = TEAM_PARKS.get(home_team, "")
    return PARK_FACTORS.get(park, 1.00)


def _get_park_name(home_team: str) -> str:
    return TEAM_PARKS.get(home_team, "Unknown Park")


async def _get_pitcher_quality(
    session: AsyncSession, pitcher_name: str | None, pitcher_mlbam_id: int | None, season: int
) -> dict:
    """Get pitcher quality metrics from the database."""
    if not pitcher_name and not pitcher_mlbam_id:
        return {"era": 4.50, "fip": 4.50, "k_per_9": 8.0, "whip": 1.30, "xwoba": 0.320}

    # Try to find by mlbam_id
    player = None
    if pitcher_mlbam_id:
        result = await session.execute(
            select(Player).where(Player.mlbam_id == str(pitcher_mlbam_id))
        )
        player = result.scalar_one_or_none()

    if not player and pitcher_name:
        result = await session.execute(select(Player).where(Player.name.ilike(f"%{pitcher_name}%")))
        player = result.scalar_one_or_none()

    if not player:
        return {"era": 4.50, "fip": 4.50, "k_per_9": 8.0, "whip": 1.30, "xwoba": 0.320}

    # Get full season pitching stats
    result = await session.execute(
        select(PitchingStats).where(
            PitchingStats.player_id == player.id,
            PitchingStats.season == season,
            PitchingStats.period == "full_season",
        )
    )
    stats = result.scalar_one_or_none()

    # Get Statcast summary
    result = await session.execute(
        select(StatcastSummary).where(
            StatcastSummary.player_id == player.id,
            StatcastSummary.season == season,
            StatcastSummary.period == "full_season",
            StatcastSummary.player_type == "pitcher",
        )
    )
    sc = result.scalar_one_or_none()

    return {
        "player_id": player.id,
        "era": stats.era if stats and stats.era else 4.50,
        "fip": stats.fip if stats and stats.fip else 4.50,
        "k_per_9": stats.k_per_9 if stats and stats.k_per_9 else 8.0,
        "whip": stats.whip if stats and stats.whip else 1.30,
        "xwoba": sc.xwoba if sc and sc.xwoba else 0.320,
        "ip": stats.ip if stats and stats.ip else 0,
    }


async def get_streaming_pitchers(
    session: AsyncSession, game_date: date | None = None, season: int | None = None, limit: int = 10
) -> list[StreamingPick]:
    """Rank today's probable pitchers for streaming value.

    Streaming Score (0-100) combines:
    - Pitcher quality (projected ERA, FIP, K/9): 40% weight
    - Opponent quality (inverse of team wRC+): 35% weight
    - Park factor (inverse of park run factor): 15% weight
    - Recent form (last 14 day ERA, K/9): 10% weight
    """
    dt = game_date or date.today()
    yr = season or dt.year
    probables = await get_probable_pitchers(dt)

    picks: list[StreamingPick] = []

    for game in probables:
        # Score both pitchers in each game
        for side in ("away", "home"):
            pitcher_name = getattr(game, f"{side}_pitcher_name")
            pitcher_id = getattr(game, f"{side}_pitcher_id")
            team = game.away_team if side == "away" else game.home_team
            opponent = game.home_team if side == "away" else game.away_team

            if not pitcher_name:
                continue

            quality = await _get_pitcher_quality(session, pitcher_name, pitcher_id, yr)
            park_factor = _get_park_factor(game.home_team)
            park_name = _get_park_name(game.home_team)

            # Pitcher quality score (lower ERA/FIP = better, higher K/9 = better)
            era = quality["era"]
            fip = quality["fip"]
            k9 = quality["k_per_9"]
            # Scale: ERA 2.0 = 100, ERA 6.0 = 0
            era_score = max(0, min(100, (6.0 - min(era, fip)) / 4.0 * 100))
            # Scale: K/9 12+ = 100, K/9 4 = 0
            k_score = max(0, min(100, (k9 - 4.0) / 8.0 * 100))
            pitcher_score = era_score * 0.6 + k_score * 0.4

            # Opponent quality (simplified: use inverse of league average as baseline)
            # Without team batting stats in DB yet, use a neutral 50
            opponent_score = 50.0

            # Park factor score: lower park factor = better for pitchers
            park_score = max(0, min(100, (1.40 - park_factor) / 0.50 * 100))

            # Recent form (use full season as proxy if no recent data)
            recent_score = pitcher_score  # simplified

            # Combined streaming score
            streaming_score = (
                pitcher_score * 0.40
                + opponent_score * 0.35
                + park_score * 0.15
                + recent_score * 0.10
            )

            # Projected K for the start (~6 IP average)
            projected_innings = 5.5
            projected_k = k9 * projected_innings / 9

            # Build reasoning
            reasons = []
            if era_score > 70:
                reasons.append(f"Strong ERA/FIP ({era:.2f}/{fip:.2f})")
            if k_score > 60:
                reasons.append(f"High K rate ({k9:.1f} K/9)")
            if park_factor < 0.96:
                reasons.append(f"Pitcher-friendly park ({park_name})")
            elif park_factor > 1.05:
                reasons.append(f"Hitter-friendly park ({park_name})")
            reasoning = "; ".join(reasons) if reasons else "Average matchup"

            picks.append(
                StreamingPick(
                    player_id=quality.get("player_id"),
                    name=pitcher_name,
                    team=team,
                    opponent=opponent,
                    park=park_name,
                    streaming_score=round(streaming_score, 1),
                    projected_k=round(projected_k, 1),
                    projected_era_for_start=round(era, 2),
                    reasoning=reasoning,
                )
            )

    picks.sort(key=lambda p: p.streaming_score, reverse=True)
    return picks[:limit]


async def get_stacks(
    session: AsyncSession, game_date: date | None = None, limit: int = 5
) -> list[StackRecommendation]:
    """Identify the best offensive stacks for a given date."""
    dt = game_date or date.today()
    yr = dt.year
    probables = await get_probable_pitchers(dt)

    stacks: list[StackRecommendation] = []

    for game in probables:
        # Evaluate each team's stack potential against the opposing pitcher
        for batting_side, pitching_side in [("away", "home"), ("home", "away")]:
            batting_team = game.away_team if batting_side == "away" else game.home_team
            pitcher_name = getattr(game, f"{pitching_side}_pitcher_name")
            pitcher_id = getattr(game, f"{pitching_side}_pitcher_id")

            if not pitcher_name:
                continue

            # Get opposing pitcher's quality (we want to stack against weak pitchers)
            quality = await _get_pitcher_quality(session, pitcher_name, pitcher_id, yr)
            park_factor = _get_park_factor(game.home_team)

            # Stack score: higher when opposing pitcher is weaker
            era = quality["era"]
            fip = quality["fip"]
            xwoba = quality["xwoba"]

            # Pitcher weakness score (higher ERA/xwOBA = better for hitters)
            pitcher_weakness = max(0, min(100, (min(era, fip) - 2.0) / 4.0 * 100))
            xwoba_score = max(0, min(100, (xwoba - 0.280) / 0.060 * 100))

            # Park factor for hitting
            park_hit_score = max(0, min(100, (park_factor - 0.90) / 0.50 * 100))

            stack_score = pitcher_weakness * 0.40 + xwoba_score * 0.35 + park_hit_score * 0.25

            reasons = []
            if era > 4.50:
                reasons.append(f"Facing high-ERA pitcher ({pitcher_name}, {era:.2f})")
            if xwoba > 0.330:
                reasons.append(f"Pitcher allows high xwOBA ({xwoba:.3f})")
            if park_factor > 1.05:
                reasons.append("Hitter-friendly park")
            reasoning = "; ".join(reasons) if reasons else "Average matchup"

            stacks.append(
                StackRecommendation(
                    team=batting_team,
                    opponent_pitcher=pitcher_name,
                    park=_get_park_name(game.home_team),
                    stack_score=round(stack_score, 1),
                    reasoning=reasoning,
                )
            )

    stacks.sort(key=lambda s: s.stack_score, reverse=True)
    return stacks[:limit]


async def get_two_start_pitchers(
    session: AsyncSession, week_start: date | None = None, season: int | None = None
) -> list[TwoStartPitcher]:
    """Identify pitchers with two starts in the given week (Mon-Sun)."""
    if week_start is None:
        today = date.today()
        # Find the Monday of this week
        week_start = today - timedelta(days=today.weekday())

    week_end = week_start + timedelta(days=6)
    yr = season or week_start.year

    # Collect all probable pitchers for the week
    pitcher_starts: dict[str, list[dict]] = {}  # pitcher_name -> list of game info

    dt = week_start
    while dt <= week_end:
        probables = await get_probable_pitchers(dt)
        for game in probables:
            for side in ("away", "home"):
                name = getattr(game, f"{side}_pitcher_name")
                pid = getattr(game, f"{side}_pitcher_id")
                if not name:
                    continue
                team = game.away_team if side == "away" else game.home_team
                opponent = game.home_team if side == "away" else game.away_team
                pitcher_starts.setdefault(name, []).append(
                    {
                        "date": dt,
                        "team": team,
                        "opponent": opponent,
                        "pitcher_id": pid,
                    }
                )
        dt += timedelta(days=1)

    # Filter to pitchers with exactly 2 starts
    two_starters: list[TwoStartPitcher] = []
    for name, starts in pitcher_starts.items():
        if len(starts) < 2:
            continue

        # Get pitcher quality for scoring
        quality = await _get_pitcher_quality(session, name, starts[0].get("pitcher_id"), yr)
        era = quality["era"]
        k9 = quality["k_per_9"]

        # Score based on pitcher quality (two starts amplifies value)
        base_score = max(0, min(100, (6.0 - era) / 4.0 * 100)) * 0.5
        k_bonus = max(0, min(50, (k9 - 4.0) / 8.0 * 50))
        combined = round(base_score + k_bonus, 1)

        reasons = [f"Two starts: vs {starts[0]['opponent']} and vs {starts[1]['opponent']}"]
        if era < 3.50:
            reasons.append(f"Elite ERA ({era:.2f})")
        if k9 > 9.0:
            reasons.append(f"High K upside ({k9:.1f} K/9)")

        two_starters.append(
            TwoStartPitcher(
                player_id=quality.get("player_id"),
                name=name,
                team=starts[0]["team"],
                start_1_opponent=starts[0]["opponent"],
                start_2_opponent=starts[1]["opponent"],
                combined_score=combined,
                reasoning="; ".join(reasons),
            )
        )

    two_starters.sort(key=lambda t: t.combined_score, reverse=True)
    return two_starters
