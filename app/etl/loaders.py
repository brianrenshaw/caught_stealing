"""Write transformed data to SQLite."""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batting_stats import BattingStats
from app.models.league_team import LeagueTeam
from app.models.pitching_stats import PitchingStats
from app.models.player import Player
from app.models.roster import Roster
from app.models.statcast_summary import StatcastSummary
from app.models.stats import Stat
from app.models.sync_log import SyncLog

logger = logging.getLogger(__name__)


def _safe_val(val: object) -> float | None:
    """Convert a value to float, returning None for NaN/inf."""
    if val is None:
        return None
    if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


class DatabaseLoader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_standings(self, standings: list[dict], league_id: str) -> int:
        """Full delete-and-replace for standings data."""
        await self.session.execute(delete(LeagueTeam).where(LeagueTeam.league_id == league_id))

        count = 0
        for team_data in standings:
            team = LeagueTeam(
                league_id=league_id,
                team_id=team_data["team_id"],
                team_name=team_data["name"],
                rank=team_data.get("rank", 0),
                wins=team_data.get("wins", 0),
                losses=team_data.get("losses", 0),
                ties=team_data.get("ties", 0),
                points_for=team_data.get("points_for", 0.0),
                points_against=team_data.get("points_against", 0.0),
                is_my_team=team_data.get("is_owned_by_current_login", False),
            )
            self.session.add(team)
            count += 1

        logger.info(f"Loaded {count} league teams (replaced all for league {league_id})")
        return count

    async def upsert_players(self, players: list[dict]) -> dict[str, int]:
        """Find-or-create players by yahoo_id.

        Returns a mapping of yahoo_id -> database player.id.
        """
        yahoo_to_db = {}

        for player_data in players:
            yahoo_id = player_data["yahoo_id"]

            result = await self.session.execute(select(Player).where(Player.yahoo_id == yahoo_id))
            existing = result.scalar_one_or_none()

            if existing:
                existing.name = player_data["name"]
                existing.team = player_data["team"]
                existing.position = player_data["position"]
                existing.updated_at = datetime.now()
                yahoo_to_db[yahoo_id] = existing.id
            else:
                new_player = Player(
                    name=player_data["name"],
                    team=player_data["team"],
                    position=player_data["position"],
                    yahoo_id=yahoo_id,
                )
                self.session.add(new_player)
                await self.session.flush()
                yahoo_to_db[yahoo_id] = new_player.id

        logger.info(f"Upserted {len(yahoo_to_db)} players")
        return yahoo_to_db

    async def upsert_rosters(self, rosters: list[dict], league_id: str) -> int:
        """Full delete-and-replace for roster data.

        Rosters change daily in baseball, so a full refresh is simpler
        and avoids stale data.
        """
        await self.session.execute(delete(Roster).where(Roster.league_id == league_id))

        count = 0
        for roster_data in rosters:
            roster = Roster(
                league_id=roster_data["league_id"],
                team_id=roster_data["team_id"],
                team_name=roster_data["team_name"],
                player_id=roster_data["player_id"],
                roster_position=roster_data["roster_position"],
                is_my_team=roster_data["is_my_team"],
            )
            self.session.add(roster)
            count += 1

        logger.info(f"Loaded {count} roster entries (replaced all for league {league_id})")
        return count

    async def upsert_stats(self, stats: list[dict]) -> int:
        """Upsert stats by (player_id, season, stat_name, source)."""
        count = 0

        for stat_data in stats:
            result = await self.session.execute(
                select(Stat).where(
                    Stat.player_id == stat_data["player_id"],
                    Stat.season == stat_data["season"],
                    Stat.stat_name == stat_data["stat_name"],
                    Stat.source == stat_data["source"],
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.value = stat_data["value"]
                existing.updated_at = datetime.now()
            else:
                new_stat = Stat(
                    player_id=stat_data["player_id"],
                    season=stat_data["season"],
                    stat_type=stat_data["stat_type"],
                    stat_name=stat_data["stat_name"],
                    value=stat_data["value"],
                    source=stat_data["source"],
                )
                self.session.add(new_stat)
            count += 1

        logger.info(f"Upserted {count} stat entries")
        return count

    async def create_sync_log(self, status: str = "running") -> SyncLog:
        """Create a new sync log entry."""
        sync_log = SyncLog(status=status)
        self.session.add(sync_log)
        await self.session.flush()
        return sync_log

    async def update_sync_log(
        self,
        sync_log: SyncLog,
        status: str,
        records_processed: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Update an existing sync log entry."""
        sync_log.status = status
        sync_log.completed_at = datetime.now()
        sync_log.records_processed = records_processed
        sync_log.error_message = error_message

    async def upsert_batting_stats(
        self,
        session: AsyncSession,
        df: pd.DataFrame,
        season: int,
        period: str,
        source: str,
    ) -> int:
        """Upsert batting stats from a FanGraphs DataFrame.

        Matches players by fangraphs_id. Skips players not found in the DB.
        """
        if df.empty:
            return 0

        count = 0
        for _, row in df.iterrows():
            fg_id = str(row.get("fangraphs_id", ""))
            if not fg_id or fg_id == "nan":
                continue

            # Find player by fangraphs_id
            result = await session.execute(select(Player).where(Player.fangraphs_id == fg_id))
            player = result.scalar_one_or_none()
            if not player:
                continue

            # Check for existing record
            result = await session.execute(
                select(BattingStats).where(
                    BattingStats.player_id == player.id,
                    BattingStats.season == season,
                    BattingStats.period == period,
                    BattingStats.source == source,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.pa = _safe_val(row.get("pa"))
                existing.ab = _safe_val(row.get("ab"))
                existing.h = _safe_val(row.get("h"))
                existing.doubles = _safe_val(row.get("doubles"))
                existing.triples = _safe_val(row.get("triples"))
                existing.hr = _safe_val(row.get("hr"))
                existing.r = _safe_val(row.get("r"))
                existing.rbi = _safe_val(row.get("rbi"))
                existing.sb = _safe_val(row.get("sb"))
                existing.cs = _safe_val(row.get("cs"))
                existing.bb = _safe_val(row.get("bb"))
                existing.so = _safe_val(row.get("so"))
                existing.avg = _safe_val(row.get("avg"))
                existing.obp = _safe_val(row.get("obp"))
                existing.slg = _safe_val(row.get("slg"))
                existing.ops = _safe_val(row.get("ops"))
                existing.woba = _safe_val(row.get("woba"))
                existing.wrc_plus = _safe_val(row.get("wrc_plus"))
                existing.updated_at = datetime.now()
            else:
                new_stat = BattingStats(
                    player_id=player.id,
                    season=season,
                    period=period,
                    source=source,
                    pa=_safe_val(row.get("pa")),
                    ab=_safe_val(row.get("ab")),
                    h=_safe_val(row.get("h")),
                    doubles=_safe_val(row.get("doubles")),
                    triples=_safe_val(row.get("triples")),
                    hr=_safe_val(row.get("hr")),
                    r=_safe_val(row.get("r")),
                    rbi=_safe_val(row.get("rbi")),
                    sb=_safe_val(row.get("sb")),
                    cs=_safe_val(row.get("cs")),
                    bb=_safe_val(row.get("bb")),
                    so=_safe_val(row.get("so")),
                    avg=_safe_val(row.get("avg")),
                    obp=_safe_val(row.get("obp")),
                    slg=_safe_val(row.get("slg")),
                    ops=_safe_val(row.get("ops")),
                    woba=_safe_val(row.get("woba")),
                    wrc_plus=_safe_val(row.get("wrc_plus")),
                )
                session.add(new_stat)
            count += 1

        await session.flush()
        logger.info(f"Upserted {count} batting stat rows ({period}/{source})")
        return count

    async def upsert_pitching_stats(
        self,
        session: AsyncSession,
        df: pd.DataFrame,
        season: int,
        period: str,
        source: str,
    ) -> int:
        """Upsert pitching stats from a FanGraphs DataFrame."""
        if df.empty:
            return 0

        count = 0
        for _, row in df.iterrows():
            fg_id = str(row.get("fangraphs_id", ""))
            if not fg_id or fg_id == "nan":
                continue

            result = await session.execute(select(Player).where(Player.fangraphs_id == fg_id))
            player = result.scalar_one_or_none()
            if not player:
                continue

            result = await session.execute(
                select(PitchingStats).where(
                    PitchingStats.player_id == player.id,
                    PitchingStats.season == season,
                    PitchingStats.period == period,
                    PitchingStats.source == source,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.w = _safe_val(row.get("w"))
                existing.l = _safe_val(row.get("l"))
                existing.sv = _safe_val(row.get("sv"))
                existing.hld = _safe_val(row.get("hld"))
                existing.g = _safe_val(row.get("g"))
                existing.gs = _safe_val(row.get("gs"))
                existing.ip = _safe_val(row.get("ip"))
                existing.h = _safe_val(row.get("h"))
                existing.er = _safe_val(row.get("er"))
                existing.hr = _safe_val(row.get("hr"))
                existing.bb = _safe_val(row.get("bb"))
                existing.so = _safe_val(row.get("so"))
                existing.era = _safe_val(row.get("era"))
                existing.whip = _safe_val(row.get("whip"))
                existing.k_per_9 = _safe_val(row.get("k_per_9"))
                existing.bb_per_9 = _safe_val(row.get("bb_per_9"))
                existing.fip = _safe_val(row.get("fip"))
                existing.xfip = _safe_val(row.get("xfip"))
                existing.updated_at = datetime.now()
            else:
                new_stat = PitchingStats(
                    player_id=player.id,
                    season=season,
                    period=period,
                    source=source,
                    w=_safe_val(row.get("w")),
                    l=_safe_val(row.get("l")),
                    sv=_safe_val(row.get("sv")),
                    hld=_safe_val(row.get("hld")),
                    g=_safe_val(row.get("g")),
                    gs=_safe_val(row.get("gs")),
                    ip=_safe_val(row.get("ip")),
                    h=_safe_val(row.get("h")),
                    er=_safe_val(row.get("er")),
                    hr=_safe_val(row.get("hr")),
                    bb=_safe_val(row.get("bb")),
                    so=_safe_val(row.get("so")),
                    era=_safe_val(row.get("era")),
                    whip=_safe_val(row.get("whip")),
                    k_per_9=_safe_val(row.get("k_per_9")),
                    bb_per_9=_safe_val(row.get("bb_per_9")),
                    fip=_safe_val(row.get("fip")),
                    xfip=_safe_val(row.get("xfip")),
                )
                session.add(new_stat)
            count += 1

        await session.flush()
        logger.info(f"Upserted {count} pitching stat rows ({period}/{source})")
        return count

    async def upsert_statcast_summary(
        self,
        session: AsyncSession,
        df: pd.DataFrame,
        season: int,
        period: str,
        player_type: str,
    ) -> int:
        """Upsert Statcast expected stats summary from a DataFrame.

        Matches players by mlbam_id. player_type is 'batter' or 'pitcher'.
        """
        if df.empty:
            return 0

        count = 0
        for _, row in df.iterrows():
            mlbam_id = str(row.get("mlbam_id", ""))
            if not mlbam_id or mlbam_id == "nan":
                continue

            # Convert to int string for matching (MLBAM IDs are integers)
            try:
                mlbam_id = str(int(float(mlbam_id)))
            except (ValueError, TypeError):
                continue

            result = await session.execute(select(Player).where(Player.mlbam_id == mlbam_id))
            player = result.scalar_one_or_none()
            if not player:
                continue

            result = await session.execute(
                select(StatcastSummary).where(
                    StatcastSummary.player_id == player.id,
                    StatcastSummary.season == season,
                    StatcastSummary.period == period,
                    StatcastSummary.player_type == player_type,
                )
            )
            existing = result.scalar_one_or_none()

            pa_val = row.get("pa")
            pa_int = None
            if pa_val is not None and not (isinstance(pa_val, float) and np.isnan(pa_val)):
                pa_int = int(float(pa_val))

            if existing:
                existing.pa = pa_int
                existing.avg_exit_velo = _safe_val(row.get("avg_exit_velo"))
                existing.max_exit_velo = _safe_val(row.get("max_exit_velo"))
                existing.barrel_pct = _safe_val(row.get("barrel_pct"))
                existing.hard_hit_pct = _safe_val(row.get("hard_hit_pct"))
                existing.xba = _safe_val(row.get("xba"))
                existing.xslg = _safe_val(row.get("xslg"))
                existing.xwoba = _safe_val(row.get("xwoba"))
                existing.sweet_spot_pct = _safe_val(row.get("sweet_spot_pct"))
                existing.updated_at = datetime.now()
            else:
                new_sc = StatcastSummary(
                    player_id=player.id,
                    season=season,
                    period=period,
                    player_type=player_type,
                    pa=pa_int,
                    avg_exit_velo=_safe_val(row.get("avg_exit_velo")),
                    max_exit_velo=_safe_val(row.get("max_exit_velo")),
                    barrel_pct=_safe_val(row.get("barrel_pct")),
                    hard_hit_pct=_safe_val(row.get("hard_hit_pct")),
                    xba=_safe_val(row.get("xba")),
                    xslg=_safe_val(row.get("xslg")),
                    xwoba=_safe_val(row.get("xwoba")),
                    sweet_spot_pct=_safe_val(row.get("sweet_spot_pct")),
                )
                session.add(new_sc)
            count += 1

        await session.flush()
        logger.info(f"Upserted {count} statcast summary rows ({player_type}/{period})")
        return count
