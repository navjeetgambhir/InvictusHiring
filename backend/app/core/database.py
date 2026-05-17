"""
Database engine and session factory.

engine            — async SQLAlchemy engine (asyncpg driver).
AsyncSessionLocal — session factory used everywhere except get_db (which is the FastAPI dep).
Base              — declarative base shared by all models.
get_db            — FastAPI dependency that yields a per-request AsyncSession.

AsyncSessionLocal is also used directly in background tasks and agents that need
a fresh session independent of the request lifecycle (e.g. fire_run, _save_to_past_jds).
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
