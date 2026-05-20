"""Unit tests for database engine, WAL mode, and session factories."""

import pytest
from sqlalchemy import text


def test_sync_engine_wal_mode():
    """Sync engine connects with WAL journal_mode pragma."""
    from poly_sports.db.database import sync_engine

    with sync_engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode"))
        mode = result.scalar()

    assert mode == "wal", f"Expected WAL mode, got {mode}"


def test_async_engine_created():
    """Async engine is created with correct sqlite+aiosqlite URL."""
    from poly_sports.db.database import async_engine

    assert "sqlite+aiosqlite" in str(async_engine.url)


@pytest.mark.asyncio
async def test_init_db_creates_all_tables():
    """init_db() creates all 6 tables."""
    from poly_sports.db.database import async_engine, init_db

    await init_db()

    tables = [
        "signals",
        "orders",
        "fills",
        "positions",
        "risk_events",
        "position_checks",
        "data_runs",
        "raw_payloads",
        "polymarket_market_snapshots",
        "sportsbook_event_snapshots",
        "sportsbook_odds_snapshots",
        "event_match_snapshots",
        "comparison_snapshots",
        "opportunity_snapshots",
        "live_price_snapshots",
    ]
    async with async_engine.connect() as conn:
        for table in tables:
            result = await conn.execute(
                text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            )
            assert result.scalar() == table


@pytest.mark.asyncio
async def test_sync_session_factory_returns_session():
    """SyncSessionFactory returns a usable Session."""
    from poly_sports.db.database import SyncSessionFactory

    session = SyncSessionFactory()
    try:
        result = session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    finally:
        session.close()


def test_data_dir_created():
    """DATABASE_URL points to existing data directory."""
    from poly_sports.db.database import DATA_DIR

    assert DATA_DIR.exists()


def test_async_engine_wal_mode():
    """Async engine sync_connection has WAL journal_mode pragma set."""
    import sqlite3
    from poly_sports.db.database import async_engine

    db_path = str(async_engine.url.database)
    conn = sqlite3.connect(db_path)
    try:
        result = conn.execute("PRAGMA journal_mode").fetchone()
        mode = result[0]
    finally:
        conn.close()

    assert mode == "wal", f"Expected WAL mode on async engine, got {mode}"


def test_init_db_called_on_startup():
    """run_auto_trader main() calls init_db() via asyncio.run()."""
    import ast
    import inspect
    from scripts.run_auto_trader import main

    source = inspect.getsource(main)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if hasattr(node.func, "attr") and node.func.attr == "run":
                for arg in node.args:
                    if isinstance(arg, ast.Call):
                        if isinstance(arg.func, ast.Name) and arg.func.id == "init_db":
                            return
    assert False, "asyncio.run(init_db()) should be called in main()"
