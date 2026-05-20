"""Shared async fixtures for DB tests."""

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from poly_sports.db.models import Base


@pytest.fixture(scope="session")
def event_loop():
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def in_memory_db() -> AsyncGenerator[tuple[async_sessionmaker, AsyncSession], None]:
    """In-memory SQLite DB using shared cache so all connections see the same data."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true",
        echo=False,
        connect_args={"check_same_thread": False},
    )

    def _set_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("PRAGMA journal_mode=MEMORY")
        cursor.close()

    event.listen(engine.sync_engine, "connect", _set_pragma)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        yield factory, session

    await engine.dispose()