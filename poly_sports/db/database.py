"""Database engine and session factories with WAL mode enabled."""

from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from poly_sports.db.models import Base

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'trading.db'}"
SYNC_DATABASE_URL = f"sqlite:///{DATA_DIR / 'trading.db'}"


def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Enable WAL mode and tuning pragmas for better concurrency."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _set_async_sqlite_pragma(sync_conn, connection_record) -> None:
    """Set pragmas on the sync connection underlying aiosqlite."""
    sync_conn.execute("PRAGMA journal_mode=WAL")
    sync_conn.execute("PRAGMA synchronous=NORMAL")
    sync_conn.execute("PRAGMA foreign_keys=ON")


async_engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

event.listen(async_engine.sync_engine, "connect", _set_async_sqlite_pragma)

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

sync_engine: Engine = create_engine(
    SYNC_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False},
)

event.listen(sync_engine, "connect", _set_sqlite_pragma)

SyncSessionFactory: sessionmaker[Session] = sessionmaker(
    sync_engine,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Create all tables in the database."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for async endpoints (FastAPI, etc.)."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
        finally:
            await session.close()


def get_sync_session() -> Session:
    """Get a synchronous session (for scripts, migrations)."""
    return SyncSessionFactory()


async def dispose_async_engine() -> None:
    """Dispose async engine connections."""
    await async_engine.dispose()