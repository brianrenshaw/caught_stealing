import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routes import (
    api,
    assistant,
    comparison,
    dashboard,
    league_dashboard,
    matchups,
    player,
    projections,
    roster,
    stats_dashboard,
    trades,
    waivers,
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _job_yahoo_sync():
    from app.etl.pipeline import run_pipeline

    logger.info("Scheduled job: Yahoo sync starting")
    result = await run_pipeline()
    logger.info(f"Scheduled job: Yahoo sync completed: {result.get('status')}")


async def _job_stats_sync():
    from app.etl.pipeline import run_stats_pipeline

    logger.info("Scheduled job: Stats sync starting")
    result = await run_stats_pipeline()
    logger.info(f"Scheduled job: Stats sync completed: {result.get('status')}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    # Schedule automated data refreshes
    # Yahoo league sync: every 6 hours
    scheduler.add_job(
        _job_yahoo_sync,
        CronTrigger(hour="*/6"),
        id="yahoo_sync",
        replace_existing=True,
    )
    # FanGraphs + Statcast stats: daily at 5 AM ET
    scheduler.add_job(
        _job_stats_sync,
        CronTrigger(hour=5, timezone="US/Eastern"),
        id="stats_sync",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("APScheduler started with automated sync jobs")

    yield

    scheduler.shutdown(wait=False)
    logger.info("APScheduler shut down")


app = FastAPI(title="Fantasy Baseball", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router)
app.include_router(roster.router)
app.include_router(trades.router)
app.include_router(waivers.router)
app.include_router(projections.router)
app.include_router(matchups.router)
app.include_router(player.router)
app.include_router(stats_dashboard.router)
app.include_router(assistant.router)
app.include_router(comparison.router)
app.include_router(league_dashboard.router)
app.include_router(api.router)
