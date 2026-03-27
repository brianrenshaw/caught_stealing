import logging

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models.roster import Roster
from app.models.stats import Stat

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Preferred display order for Yahoo stats on the roster page.
# Stats not in these lists still appear, appended at the end.
BATTER_STAT_ORDER = [
    "AB",
    "R",
    "H",
    "HR",
    "RBI",
    "SB",
    "BB",
    "K",
    "AVG",
    "OBP",
    "SLG",
    "OPS",
]
PITCHER_STAT_ORDER = [
    "IP",
    "W",
    "L",
    "SV",
    "HLD",
    "K",
    "ERA",
    "WHIP",
    "QS",
    "BB",
    "H",
    "ER",
]


@router.get("/roster")
async def roster(request: Request):
    batters = []
    pitchers = []

    try:
        async with async_session() as session:
            result = await session.execute(
                select(Roster)
                .options(selectinload(Roster.player))
                .where(Roster.is_my_team.is_(True))
            )
            roster_entries = result.scalars().all()

            for entry in roster_entries:
                player = entry.player
                if not player:
                    continue

                # Get player stats from Yahoo
                stat_result = await session.execute(
                    select(Stat).where(
                        Stat.player_id == player.id,
                        Stat.source == "yahoo",
                    )
                )
                player_stats = {s.stat_name: s.value for s in stat_result.scalars().all()}

                player_data = {
                    "player_id": player.id,
                    "name": player.name,
                    "team": player.team or "",
                    "position": player.position or "",
                    "roster_position": entry.roster_position,
                    "stats": player_stats,
                }

                pitching_positions = {"SP", "RP", "P"}
                positions = {p.strip() for p in (player.position or "").split(",")}
                if positions & pitching_positions:
                    pitchers.append(player_data)
                else:
                    batters.append(player_data)

    except Exception:
        logger.exception("Failed to load roster data")

    # Sort by roster position
    position_order = [
        "C",
        "1B",
        "2B",
        "3B",
        "SS",
        "LF",
        "CF",
        "RF",
        "OF",
        "Util",
        "BN",
        "SP",
        "RP",
        "P",
        "DL",
        "IL",
        "NA",
    ]

    def sort_key(p):
        pos = p["roster_position"]
        if pos in position_order:
            return position_order.index(pos)
        return 99

    batters.sort(key=sort_key)
    pitchers.sort(key=sort_key)

    # Build ordered stat column lists: preferred order first, then any extras
    def _ordered_stats(players: list[dict], preferred: list[str]) -> list[str]:
        all_keys: set[str] = set()
        for p in players:
            all_keys.update(p["stats"].keys())
        ordered = [k for k in preferred if k in all_keys]
        extras = sorted(all_keys - set(ordered))
        return (ordered + extras)[:12]

    batting_stats = _ordered_stats(batters, BATTER_STAT_ORDER)
    pitching_stats = _ordered_stats(pitchers, PITCHER_STAT_ORDER)

    return templates.TemplateResponse(
        request,
        "roster.html",
        {
            "batters": batters,
            "pitchers": pitchers,
            "batting_stats": batting_stats,
            "pitching_stats": pitching_stats,
            "has_data": bool(batters or pitchers),
        },
    )
