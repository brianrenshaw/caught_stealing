"""Main ETL orchestrator — run with: uv run python -m app.etl.pipeline"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import default_season, settings
from app.database import async_session
from app.etl.extractors import YahooExtractor
from app.etl.loaders import DatabaseLoader
from app.etl.transformers import DataTransformer
from app.models.sync_log import SyncLog
from app.services.yahoo_service import yahoo_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Minimum seconds between syncs
SYNC_COOLDOWN = 60  # 1 minute
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


async def _retry(coro_func, *args, label: str = "operation", **kwargs):
    """Retry an async function with exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await coro_func(*args, **kwargs)
        except Exception as e:
            if attempt == MAX_RETRIES:
                logger.error(f"{label} failed after {MAX_RETRIES} attempts: {e}")
                raise
            delay = RETRY_DELAY * attempt
            logger.warning(f"{label} attempt {attempt} failed: {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)


async def check_cooldown(pipeline_type: str = "yahoo") -> bool:
    """Return True if enough time has passed since last sync of this type.

    Each pipeline type (yahoo, stats) has its own independent cooldown
    so they don't block each other.
    """
    async with async_session() as session:
        query = (
            select(SyncLog)
            .where(SyncLog.pipeline_type == pipeline_type)
            .order_by(SyncLog.id.desc())
            .limit(1)
        )
        result = await session.execute(query)
        last_sync = result.scalar_one_or_none()
        if last_sync and last_sync.started_at:
            # SQLite CURRENT_TIMESTAMP is UTC; we must compare in UTC
            now_utc = datetime.now(timezone.utc)
            started_utc = last_sync.started_at.replace(tzinfo=timezone.utc)
            elapsed = (now_utc - started_utc).total_seconds()
            if elapsed < SYNC_COOLDOWN and last_sync.status != "failed":
                logger.info(
                    f"Sync cooldown ({pipeline_type}): "
                    f"{SYNC_COOLDOWN - elapsed:.0f}s remaining"
                )
                return False
    return True


async def _update_player_ages(session) -> int:
    """Fetch birth dates from MLB-StatsAPI for players missing age data."""
    from datetime import date

    import statsapi

    from app.models.player import Player

    result = await session.execute(
        select(Player).where(
            Player.mlbam_id.isnot(None),
            Player.birth_date.is_(None),
        )
    )
    players = result.scalars().all()
    if not players:
        return 0

    count = 0
    batch_size = 50
    for i in range(0, len(players), batch_size):
        batch = players[i : i + batch_size]
        ids = ",".join(str(p.mlbam_id) for p in batch)
        try:
            data = await asyncio.get_event_loop().run_in_executor(
                None, lambda: statsapi.get("people", {"personIds": ids})
            )
            for person in data.get("people", []):
                mlbam_id = str(person.get("id", ""))
                birth_str = person.get("birthDate")
                if not birth_str:
                    continue
                for p in batch:
                    if str(p.mlbam_id) == mlbam_id:
                        birth = date.fromisoformat(birth_str)
                        p.birth_date = birth
                        today = date.today()
                        p.age = (
                            today.year
                            - birth.year
                            - ((today.month, today.day) < (birth.month, birth.day))
                        )
                        count += 1
                        break
        except Exception as e:
            logger.warning(f"MLB API batch age fetch failed: {e}")
        await asyncio.sleep(0.5)

    await session.flush()
    logger.info(f"Updated ages for {count} players")
    return count


async def _store_steamer_projections(
    session, season: int, fetch_batting, fetch_pitching
) -> int:
    """Fetch Steamer ROS projections and store in the projections table.

    Matches players by fangraphs_id or mlbam_id, then stores each counting stat
    as a separate row in the projections table (system='steamer_ros').
    """
    from sqlalchemy import delete

    from app.models.player import Player
    from app.models.projection import Projection

    # Clear old steamer_ros entries for this season
    await session.execute(
        delete(Projection).where(
            Projection.system == "steamer_ros",
            Projection.season == season,
        )
    )

    # Build lookup maps: fangraphs_id -> player_id, mlbam_id -> player_id
    player_result = await session.execute(select(Player))
    players = player_result.scalars().all()
    fg_map: dict[str, int] = {}
    mlb_map: dict[str, int] = {}
    for p in players:
        if p.fangraphs_id:
            fg_map[str(p.fangraphs_id)] = p.id
        if p.mlbam_id:
            mlb_map[str(p.mlbam_id)] = p.id

    count = 0

    # Fetch and store batting projections
    bat_data = await fetch_batting()
    for entry in bat_data:
        player_id = fg_map.get(entry["fangraphs_id"])
        if not player_id and entry.get("mlbam_id"):
            player_id = mlb_map.get(entry["mlbam_id"])
        if not player_id:
            continue

        for stat_name, value in entry["stats"].items():
            session.add(
                Projection(
                    player_id=player_id,
                    season=season,
                    system="steamer_ros",
                    stat_name=stat_name,
                    projected_value=float(value),
                )
            )
            count += 1

    # Fetch and store pitching projections
    pitch_data = await fetch_pitching()
    for entry in pitch_data:
        player_id = fg_map.get(entry["fangraphs_id"])
        if not player_id and entry.get("mlbam_id"):
            player_id = mlb_map.get(entry["mlbam_id"])
        if not player_id:
            continue

        for stat_name, value in entry["stats"].items():
            session.add(
                Projection(
                    player_id=player_id,
                    season=season,
                    system="steamer_ros",
                    stat_name=stat_name,
                    projected_value=float(value),
                )
            )
            count += 1

    await session.flush()
    logger.info(f"Stored {count} Steamer ROS projection rows")
    return count


async def run_pipeline() -> dict:
    """Run the full ETL pipeline.

    Returns a status dict with counts, timing, and any error info.
    """
    if not yahoo_service.is_configured():
        return {
            "status": "not_configured",
            "message": "Yahoo API credentials not set. Check your .env file.",
        }

    if not await check_cooldown(pipeline_type="yahoo"):
        return {
            "status": "cooldown",
            "message": "Please wait at least 5 minutes between syncs.",
        }

    start_time = time.time()
    total_records = 0

    async with async_session() as session:
        loader = DatabaseLoader(session)
        sync_log = await loader.create_sync_log(
            status="running", pipeline_type="yahoo"
        )
        await session.commit()

        try:
            # --- EXTRACT ---
            extractor = YahooExtractor()

            logger.info("=== EXTRACT PHASE ===")
            stat_categories = {}
            try:
                stat_categories = await extractor.extract_stat_categories()
            except Exception as e:
                logger.warning(f"Stat categories extraction failed: {e}")

            warnings = []

            standings = []
            try:
                standings = await _retry(
                    extractor.extract_standings, label="extract standings"
                )
            except Exception as e:
                warnings.append(f"Standings: {e}")
                logger.warning(f"Standings extraction failed: {e}")

            # Save standings immediately so they persist even if rosters fail
            standings_count = await loader.upsert_standings(standings, settings.yahoo_league_id)
            total_records += standings_count
            await session.commit()

            roster_data = {}
            try:
                roster_data = await _retry(
                    extractor.extract_all_rosters, label="extract rosters"
                )
            except Exception as e:
                warnings.append(f"Rosters: {e}")
                logger.warning(f"Roster extraction failed: {e}")

            transactions = []
            try:
                transactions = await extractor.extract_transactions(limit=5)
            except Exception as e:
                logger.warning(f"Transactions extraction failed: {e}")

            # --- TRANSFORM ---
            logger.info("=== TRANSFORM PHASE ===")
            transformer = DataTransformer(stat_categories=stat_categories)
            players = transformer.transform_players(roster_data)

            # --- LOAD ---
            logger.info("=== LOAD PHASE ===")
            player_db_map = await loader.upsert_players(players)
            total_records += len(player_db_map)

            rosters = transformer.transform_rosters(roster_data, player_db_map)
            roster_count = await loader.upsert_rosters(rosters, settings.yahoo_league_id)
            total_records += roster_count

            stats = transformer.transform_stats(roster_data, player_db_map)
            stat_count = await loader.upsert_stats(stats)
            total_records += stat_count

            # Determine status: partial if critical data is missing
            if roster_count == 0 and standings_count == 0:
                status = "partial"
                if not warnings:
                    warnings.append(
                        "No rosters or standings loaded — Yahoo API may "
                        "need re-authorization (restart server and check terminal)"
                    )
            elif roster_count == 0 or standings_count == 0:
                status = "partial"
            else:
                status = "success"

            await loader.update_sync_log(
                sync_log, status=status, records_processed=total_records
            )
            await session.commit()

            # Update weekly matchup actuals after successful sync
            try:
                from app.services.weekly_matchup_service import (
                    update_current_matchup_actuals,
                )

                await update_current_matchup_actuals(session, default_season())
                await session.commit()
            except Exception as e:
                logger.warning(f"Matchup actuals update failed: {e}")

            duration = time.time() - start_time
            result = {
                "status": status,
                "players": len(player_db_map),
                "rosters": roster_count,
                "stats": stat_count,
                "standings": standings_count,
                "transactions": len(transactions),
                "total_records": total_records,
                "duration_seconds": round(duration, 1),
                "warnings": warnings,
            }
            logger.info(f"=== PIPELINE COMPLETE === {result}")
            return result

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            await loader.update_sync_log(sync_log, status="failed", error_message=str(e))
            await session.commit()
            return {
                "status": "failed",
                "message": str(e),
                "duration_seconds": round(time.time() - start_time, 1),
            }


async def run_stats_pipeline(season: int | None = None) -> dict:
    """Run the FanGraphs + Statcast stats ETL pipeline.

    This is separate from the Yahoo pipeline and pulls public baseball data
    from FanGraphs (via pybaseball) and Statcast (via Baseball Savant).

    Args:
        season: MLB season year to fetch. Defaults to current year, but falls
                back to previous year if we're before April (season hasn't started).
    """
    from app.services import fangraphs_service, statcast_service
    from app.services.id_mapper import id_mapper

    if not await check_cooldown(pipeline_type="stats"):
        return {
            "status": "cooldown",
            "message": "Please wait at least 5 minutes between stats syncs.",
        }

    start_time = time.time()
    if season is None:
        season = default_season()
    results: dict[str, int | str | float] = {"status": "running", "season": season}

    async with async_session() as session:
        loader = DatabaseLoader(session)
        sync_log = await loader.create_sync_log(
            status="running", pipeline_type="stats"
        )
        await session.commit()

        try:
            # Step 1: Seed/update the player ID crosswalk
            logger.info("=== STATS PIPELINE: Seeding ID crosswalk ===")
            crosswalk_count = await id_mapper.seed_crosswalk(session)
            results["crosswalk_updates"] = crosswalk_count

            # Step 2: Fetch FanGraphs batting stats (full season)
            logger.info("=== STATS PIPELINE: Fetching batting stats ===")
            try:
                batting_df = await fangraphs_service.fetch_batting_stats(season, qual=0)
                batting_count = await loader.upsert_batting_stats(
                    session, batting_df, season, "full_season", "fangraphs"
                )
                results["batting_stats"] = batting_count
            except Exception as e:
                logger.error(f"Batting stats fetch failed: {e}")
                results["batting_stats_error"] = str(e)

            # Step 3: Fetch FanGraphs pitching stats (full season)
            logger.info("=== STATS PIPELINE: Fetching pitching stats ===")
            try:
                pitching_df = await fangraphs_service.fetch_pitching_stats(season, qual=0)
                pitching_count = await loader.upsert_pitching_stats(
                    session, pitching_df, season, "full_season", "fangraphs"
                )
                results["pitching_stats"] = pitching_count
            except Exception as e:
                logger.error(f"Pitching stats fetch failed: {e}")
                results["pitching_stats_error"] = str(e)

            # Step 4: Fetch Statcast expected stats (batters)
            logger.info("=== STATS PIPELINE: Fetching Statcast batter summaries ===")
            try:
                batter_xstats = await statcast_service.fetch_statcast_batting_summary(season)
                batter_sc_count = await loader.upsert_statcast_summary(
                    session, batter_xstats, season, "full_season", "batter"
                )
                results["statcast_batters"] = batter_sc_count
            except Exception as e:
                logger.error(f"Statcast batter fetch failed: {e}")
                results["statcast_batters_error"] = str(e)

            # Step 5: Fetch Statcast expected stats (pitchers)
            logger.info("=== STATS PIPELINE: Fetching Statcast pitcher summaries ===")
            try:
                pitcher_xstats = await statcast_service.fetch_statcast_pitching_summary(season)
                pitcher_sc_count = await loader.upsert_statcast_summary(
                    session, pitcher_xstats, season, "full_season", "pitcher"
                )
                results["statcast_pitchers"] = pitcher_sc_count
            except Exception as e:
                logger.error(f"Statcast pitcher fetch failed: {e}")
                results["statcast_pitchers_error"] = str(e)

            # Step 6: Fetch sprint speed and merge into batter Statcast data
            logger.info("=== STATS PIPELINE: Fetching sprint speed data ===")
            try:
                sprint_df = await statcast_service.fetch_sprint_speed(season)
                if not sprint_df.empty:
                    sprint_count = await loader.upsert_sprint_speed(
                        session, sprint_df, season
                    )
                    results["sprint_speed"] = sprint_count
                else:
                    results["sprint_speed"] = 0
            except Exception as e:
                logger.warning(f"Sprint speed fetch failed: {e}")
                results["sprint_speed_error"] = str(e)

            # Step 7: Fetch player birth dates and compute ages
            logger.info("=== STATS PIPELINE: Updating player ages ===")
            try:
                age_count = await _update_player_ages(session)
                results["player_ages"] = age_count
            except Exception as e:
                logger.warning(f"Player age update failed: {e}")
                results["player_ages_error"] = str(e)

            # Step 8: Fetch Steamer ROS projections from FanGraphs API
            logger.info("=== STATS PIPELINE: Fetching Steamer ROS projections ===")
            try:
                from app.services.external_projections import (
                    fetch_steamer_batting_ros,
                    fetch_steamer_pitching_ros,
                )

                steamer_count = await _store_steamer_projections(
                    session, season, fetch_steamer_batting_ros, fetch_steamer_pitching_ros
                )
                results["steamer_projections"] = steamer_count
            except Exception as e:
                logger.warning(f"Steamer ROS projection fetch failed: {e}")
                results["steamer_projections_error"] = str(e)

            # Step 9: Calculate player points from loaded stats
            logger.info("=== STATS PIPELINE: Calculating player points ===")
            try:
                from app.services.points_service import calculate_all_player_points

                points_summaries = await calculate_all_player_points(session, season)
                results["player_points"] = len(points_summaries)
            except Exception as e:
                logger.error(f"Player points calculation failed: {e}")
                results["player_points_error"] = str(e)

            total = sum(v for v in results.values() if isinstance(v, int))
            await loader.update_sync_log(sync_log, status="success", records_processed=total)
            await session.commit()

            duration = time.time() - start_time
            results["status"] = "success"
            results["duration_seconds"] = round(duration, 1)
            logger.info(f"=== STATS PIPELINE COMPLETE === {results}")
            return results

        except Exception as e:
            logger.error(f"Stats pipeline failed: {e}", exc_info=True)
            await loader.update_sync_log(sync_log, status="failed", error_message=str(e))
            await session.commit()
            return {
                "status": "failed",
                "message": str(e),
                "duration_seconds": round(time.time() - start_time, 1),
            }


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_pipeline())
