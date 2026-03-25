import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.database import init_db
from app.routes import (
    api,
    assistant,
    auth,
    comparison,
    dashboard,
    intel,
    league_dashboard,
    matchups,
    player,
    projection_analysis,
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


_PUBLIC_PREFIXES = ("/login", "/static", "/health")


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated requests to the login page."""

    async def dispatch(self, request: Request, call_next):
        from app.routes.auth import is_authenticated

        path = request.url.path
        if (
            not settings.auth_password
            or any(path.startswith(p) for p in _PUBLIC_PREFIXES)
            or is_authenticated(request)
        ):
            return await call_next(request)

        # HTMX / fetch requests get 401; browsers get a redirect.
        if request.headers.get("HX-Request") or request.headers.get(
            "accept", ""
        ).startswith("application/json"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=302)


app = FastAPI(title="Fantasy Baseball", lifespan=lifespan)

app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


# Cache static assets for 7 days
@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=604800"
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(auth.router)
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
app.include_router(intel.router)
app.include_router(projection_analysis.router)
app.include_router(api.router)
