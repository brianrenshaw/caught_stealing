import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


# Migrations: (table_name, column_name, column_type)
_MIGRATIONS = [
    ("pitching_stats", "k_pct", "FLOAT"),
    ("pitching_stats", "bb_pct", "FLOAT"),
    ("pitching_stats", "gb_pct", "FLOAT"),
    ("pitching_stats", "hr_fb_pct", "FLOAT"),
    ("pitching_stats", "lob_pct", "FLOAT"),
    ("pitching_stats", "gmli", "FLOAT"),
    ("statcast_summary", "xera", "FLOAT"),
    ("players", "birth_date", "DATE"),
    ("players", "age", "INTEGER"),
]


async def _run_migrations(conn) -> None:
    """Add new columns to existing tables (safe if column already exists)."""
    for table, column, col_type in _MIGRATIONS:
        try:
            await conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            )
            logger.info(f"Migration: added {table}.{column}")
        except Exception:
            # Column already exists — this is expected
            pass


async def init_db() -> None:

    # Import Base from one of the models (they all share the same Base)
    from app.models.player import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)
