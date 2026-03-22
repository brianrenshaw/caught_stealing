from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db() -> None:

    # Import Base from one of the models (they all share the same Base)
    from app.models.player import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
