"""Integration: engine writes to SQLite instead of JSONL files."""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from poly_sports.trading.config import TradingConfig
from poly_sports.trading.engine import AutoTraderEngine
from poly_sports.utils.file_utils import save_json


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def comparison_data(tmp_path: Path) -> Path:
    path = tmp_path / "comparison.json"
    save_json(
        [{
            "pm_event_id": "event-1",
            "pm_market_id": "market-1",
            "pm_market_outcomes": '["Team A", "Team B"]',
            "pm_market_outcomePrices": '["0.50", "0.50"]',
            "pm_event_liquidity": 10000,
            "pm_market_liquidityNum": 10000,
            "pm_spread": 0.01,
            "sportsbook_count": 3,
            "match_confidence": 0.9,
            "sportsbook_outcomes": [
                {"name": "Team A", "avg_implied_probability": 0.515},
                {"name": "Team B", "avg_implied_probability": 0.485},
            ],
        }],
        str(path),
    )
    return path


@pytest.fixture
def session_factory(db_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _init():
        async with engine.begin() as conn:
            from poly_sports.db.models import Base
            await conn.run_sync(Base.metadata.create_all)

    asyncio.get_event_loop().run_until_complete(_init())
    return factory


def test_auto_trader_cycle_writes_to_database(
    tmp_path: Path, comparison_data: Path, session_factory
):
    """run_cycle() writes signals, orders, fills to SQLite."""
    cfg = TradingConfig(
        trading_mode="paper",
        comparison_data_path=str(comparison_data),
        refresh_comparison_each_cycle=False,
        stake_per_trade_usd=20,
        min_profit_threshold=0.02,
        min_liquidity_usd=1000,
        min_confidence=0.7,
        max_spread=0.03,
    )

    engine_obj = AutoTraderEngine(cfg, session_factory)
    asyncio.get_event_loop().run_until_complete(engine_obj.run_cycle())

    import sqlite3
    conn = sqlite3.connect(session_factory.kw["bind"].url.database)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM signals")
    signals_count = cur.fetchone()[0]
    assert signals_count >= 1, f"Expected signals >= 1, got {signals_count}"

    cur.execute("SELECT COUNT(*) FROM orders")
    orders_count = cur.fetchone()[0]
    assert orders_count >= 1, f"Expected orders >= 1, got {orders_count}"

    cur.execute("SELECT COUNT(*) FROM fills")
    fills_count = cur.fetchone()[0]
    assert fills_count >= 1, f"Expected fills >= 1, got {fills_count}"

    cur.execute("SELECT COUNT(*) FROM positions WHERE status = 'OPEN'")
    open_count = cur.fetchone()[0]
    assert open_count >= 1, f"Expected open positions >= 1, got {open_count}"

    conn.close()