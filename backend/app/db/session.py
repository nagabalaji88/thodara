from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()
pool_options = (
    {}
    if settings.database_url.startswith("sqlite")
    else {
        "pool_size": 10,
        "max_overflow": 10,
        "pool_timeout": 20,
        "pool_recycle": 1800,
    }
)
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    **pool_options,
)
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    factory = getattr(request.app.state, "session_factory", SessionFactory)
    async with factory() as session:
        yield session
