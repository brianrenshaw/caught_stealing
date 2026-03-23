"""Main ETL orchestrator — run with: uv run python -m app.etl.pipeline"""

import asyncio
import logging
import time
from datetime import datetime

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
SYNC_COOLDOWN = 300  # 5 minutes
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


async def check_cooldown() -> bool:
    """Return True if enough time has passed since last sync."""
    async with async_session() as session:
        result = await session.execute(select(SyncLog).order_by(SyncLog.id.desc()).limit(1))
        last_sync = result.scalar_one_or_none()
        if last_sync and last_sync.started_at:
            elapsed = (datetime.now() - last_sync.started_at).total_seconds()
            if elapsed < SYNC_COOLDOWN and last_sync.status != "failed":
                logger.info(f"Sync cooldown: {SYNC_COOLDOWN - elapsed:.0f}s remaining")
                return False
    return True


async def run_pipeline() -> dict:
    """Run the full ETL pipeline.

    Returns a status dict with counts, timing, and any error info.
    """
    if not yahoo_service.is_configured():
        return {
            "status": "not_configured",
            "message": "Yahoo API credentials not set. Check your .env file.",
        }

    if not await check_cooldown():
        return {
            "status": "cooldown",
            "message": "Please wait at least 5 minutes between syncs.",
        }

    start_time = time.time()
    total_records = 0

    async with async_session() as session:
        loader = DatabaseLoader(session)
        sync_log = await loader.create_sync_log(status="running")
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

            standings = await _retry(extractor.extract_standings, label="extract standings")

            # Save standings immediately so they persist even if rosters fail
            standings_count = await loader.upsert_standings(standings, settings.yahoo_league_id)
            total_records += standings_count
            await session.commit()

            roster_data = {}
            try:
                roster_data = await _retry(extractor.extract_all_rosters, label="extract rosters")
            except Exception as e:
                logger.warning(f"Roster extraction failed: {e}")

            transactions = await extractor.extract_transactions(limit=5)

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

            await loader.update_sync_log(
                sync_log, status="success", records_processed=total_records
            )
            await session.commit()

            duration = time.time() - start_time
            result = {
                "status": "success",
                "players": len(player_db_map),
                "rosters": roster_count,
                "stats": stat_count,
                "standings": len(standings),
                "transactions": len(transactions),
                "total_records": total_records,
                "duration_seconds": round(duration, 1),
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

    start_time = time.time()
    if season is None:
        season = default_season()
    results: dict[str, int | str | float] = {"status": "running", "season": season}

    async with async_session() as session:
        loader = DatabaseLoader(session)
        sync_log = await loader.create_sync_log(status="running")
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
