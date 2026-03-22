"""Shared test fixtures: in-memory SQLite database and sample data factories."""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.batting_stats import BattingStats
from app.models.pitching_stats import PitchingStats
from app.models.player import Base, Player
from app.models.statcast_summary import StatcastSummary

# In-memory SQLite for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


# --- Sample Data Factories ---


def make_player(
    name: str = "Test Player",
    team: str = "NYY",
    position: str = "SS",
    yahoo_id: str | None = None,
    fangraphs_id: str | None = None,
    mlbam_id: str | None = None,
) -> Player:
    return Player(
        name=name,
        team=team,
        position=position,
        yahoo_id=yahoo_id,
        fangraphs_id=fangraphs_id,
        mlbam_id=mlbam_id,
    )


def make_batting_stats(
    player_id: int,
    season: int = 2026,
    period: str = "full_season",
    source: str = "fangraphs",
    pa: float = 500,
    hr: float = 25,
    r: float = 80,
    rbi: float = 85,
    sb: float = 10,
    avg: float = 0.275,
    obp: float = 0.350,
    slg: float = 0.475,
    ops: float = 0.825,
    woba: float = 0.350,
    wrc_plus: float = 125,
) -> BattingStats:
    return BattingStats(
        player_id=player_id,
        season=season,
        period=period,
        source=source,
        pa=pa,
        hr=hr,
        r=r,
        rbi=rbi,
        sb=sb,
        avg=avg,
        obp=obp,
        slg=slg,
        ops=ops,
        woba=woba,
        wrc_plus=wrc_plus,
    )


def make_pitching_stats(
    player_id: int,
    season: int = 2026,
    period: str = "full_season",
    source: str = "fangraphs",
    ip: float = 150,
    w: float = 10,
    l: float = 5,  # noqa: E741
    sv: float = 0,
    so: float = 180,
    era: float = 3.25,
    whip: float = 1.10,
    k_per_9: float = 10.8,
    bb_per_9: float = 2.5,
    fip: float = 3.10,
    xfip: float = 3.20,
    g: float = 25,
    gs: float = 25,
) -> PitchingStats:
    return PitchingStats(
        player_id=player_id,
        season=season,
        period=period,
        source=source,
        ip=ip,
        w=w,
        l=l,
        sv=sv,
        so=so,
        era=era,
        whip=whip,
        k_per_9=k_per_9,
        bb_per_9=bb_per_9,
        fip=fip,
        xfip=xfip,
        g=g,
        gs=gs,
    )


def make_statcast_summary(
    player_id: int,
    season: int = 2026,
    period: str = "full_season",
    player_type: str = "batter",
    pa: int = 500,
    xba: float = 0.280,
    xslg: float = 0.490,
    xwoba: float = 0.360,
    barrel_pct: float = 12.0,
    hard_hit_pct: float = 42.0,
    avg_exit_velo: float = 90.5,
    sweet_spot_pct: float = 35.0,
) -> StatcastSummary:
    return StatcastSummary(
        player_id=player_id,
        season=season,
        period=period,
        player_type=player_type,
        pa=pa,
        xba=xba,
        xslg=xslg,
        xwoba=xwoba,
        barrel_pct=barrel_pct,
        hard_hit_pct=hard_hit_pct,
        avg_exit_velo=avg_exit_velo,
        sweet_spot_pct=sweet_spot_pct,
    )
