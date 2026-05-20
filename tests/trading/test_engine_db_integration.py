"""Integration: engine writes to SQLite instead of JSONL files."""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from poly_sports.trading.config import TradingConfig
from poly_sports.trading.engine import AutoTraderEngine
from poly_sports.market_data.price_feed import PriceQuote
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
        price_feed_source="disabled",
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

    cur.execute("SELECT COUNT(*) FROM data_runs WHERE run_type = 'auto_trader_cycle'")
    data_runs_count = cur.fetchone()[0]
    assert data_runs_count == 1, f"Expected one auto-trader data run, got {data_runs_count}"

    cur.execute("SELECT COUNT(*) FROM comparison_snapshots")
    comparison_count = cur.fetchone()[0]
    assert comparison_count >= 1, f"Expected comparison snapshots >= 1, got {comparison_count}"

    cur.execute("SELECT COUNT(*) FROM opportunity_snapshots")
    opportunity_count = cur.fetchone()[0]
    assert opportunity_count >= 1, f"Expected opportunity snapshots >= 1, got {opportunity_count}"

    conn.close()


@pytest.mark.asyncio
async def test_fetch_live_prices_uses_thread_pool_for_gamma_fallback(tmp_path: Path):
    """_fetch_live_prices_async keeps blocking Gamma fallback off the event loop."""
    import ast
    import inspect
    import textwrap
    from poly_sports.trading.engine import AutoTraderEngine

    source = inspect.getsource(AutoTraderEngine._fetch_live_prices_async)
    dedented = textwrap.dedent(source)
    tree = ast.parse(dedented)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    to_thread_calls = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "to_thread"]
    assert len(to_thread_calls) >= 1, "asyncio.to_thread should be used for the Gamma fallback"


class FakePriceFeed:
    def __init__(self, quotes):
        self.quotes = {quote.asset_id: quote for quote in quotes}
        self.subscribed_assets = []

    async def subscribe_assets(self, asset_metadata):
        self.subscribed_assets.extend(asset_metadata.keys())
        for asset_id, metadata in asset_metadata.items():
            quote = self.quotes.get(asset_id)
            if quote:
                quote.market_id = metadata.get("market_id") or quote.market_id
                quote.event_id = metadata.get("event_id") or quote.event_id
                quote.outcome_name = metadata.get("outcome_name") or quote.outcome_name

    async def wait_for_assets(self, asset_ids, timeout_ms):
        return any(asset_id in self.quotes for asset_id in asset_ids)

    def get_quote_by_asset(self, asset_id):
        return self.quotes.get(str(asset_id))

    def drain_raw_events(self):
        return []

    def quote_snapshots(self):
        return [quote.snapshot() for quote in self.quotes.values()]


def test_auto_trader_uses_polymarket_ws_quote_for_paper_entry(
    tmp_path: Path, session_factory
):
    """Paper entries use the executable WS ask instead of stale strategy price."""
    comparison_path = tmp_path / "comparison-live-quote.json"
    save_json(
        [{
            "pm_event_id": "event-1",
            "pm_market_id": "market-1",
            "pm_market_outcomes": json.dumps(["Team A", "Team B"]),
            "pm_market_outcomePrices": json.dumps(["0.50", "0.50"]),
            "pm_clobTokenIds": json.dumps(["tok-a", "tok-b"]),
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
        str(comparison_path),
    )
    cfg = TradingConfig(
        trading_mode="paper",
        comparison_data_path=str(comparison_path),
        refresh_comparison_each_cycle=False,
        stake_per_trade_usd=20,
        min_profit_threshold=0.02,
        min_liquidity_usd=1000,
        min_confidence=0.7,
        max_spread=0.03,
        price_feed_source="disabled",
        paper_execution_use_live_quote=True,
        ws_warmup_timeout_ms=0,
    )

    engine_obj = AutoTraderEngine(cfg, session_factory)
    engine_obj.price_feed = FakePriceFeed([
        PriceQuote(
            asset_id="tok-a",
            market_id="market-1",
            event_id="event-1",
            outcome_name="Team A",
            best_bid=0.51,
            best_ask=0.52,
        )
    ])

    asyncio.get_event_loop().run_until_complete(engine_obj.run_cycle())

    import sqlite3
    conn = sqlite3.connect(session_factory.kw["bind"].url.database)
    cur = conn.cursor()
    cur.execute(
        "SELECT requested_price, metadata_json FROM orders WHERE order_type = 'ENTRY'"
    )
    row = cur.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == pytest.approx(0.52)
    metadata = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    assert metadata["token_id"] == "tok-a"
    assert metadata["quote_source"] == "polymarket_ws_market"
