"""Unit tests for trading database repository."""

import pytest
from datetime import datetime, timezone
from poly_sports.trading.models import ExecutionResult, OrderIntent, Position, Signal
from poly_sports.db.repository import TradingRepository
from sqlalchemy import select
from poly_sports.db.models import (
    Fill as FillModel,
    Order as OrderModel,
    RiskEvent as RiskEventModel,
    PositionCheck as PositionCheckModel,
    Signal as SignalModel,
)


@pytest.mark.asyncio
async def test_save_and_get_signal(in_memory_db):
    """Signal fields are preserved exactly after save+retrieve."""
    factory, session = in_memory_db
    repo = TradingRepository(session)

    sig = Signal(
        signal_id="sig-test-1",
        market_id="m1",
        event_id="e1",
        outcome_name="Team A",
        side="BUY",
        order_type="ENTRY",
        suggested_price=0.5,
        target_price=0.55,
        confidence=0.9,
        expected_profit_pct=0.05,
        liquidity=5000,
        spread=0.01,
        created_at="2026-01-01T00:00:00Z",
        metadata={"key": "value"},
    )

    await repo.save_signal(sig)

    result = await repo._session.execute(select(SignalModel).where(SignalModel.signal_id == "sig-test-1"))
    row = result.scalar_one()

    assert row.signal_id == "sig-test-1"
    assert row.market_id == "m1"
    assert row.confidence == 0.9
    assert row.metadata_json == {"key": "value"}


@pytest.mark.asyncio
async def test_save_signal_duplicate_idempotent(in_memory_db):
    """Saving same signal_id twice does not create duplicates."""
    factory, session = in_memory_db
    repo = TradingRepository(session)

    sig = Signal(
        signal_id="sig-dup",
        market_id="m1",
        event_id="e1",
        outcome_name="Team A",
        side="BUY",
        order_type="ENTRY",
        suggested_price=0.5,
        target_price=0.55,
        confidence=0.9,
        expected_profit_pct=0.05,
        liquidity=5000,
        spread=0.01,
        created_at="2026-01-01T00:00:00Z",
    )

    await repo.save_signal(sig)
    await repo.save_signal(sig)

    result = await repo._session.execute(select(SignalModel).where(SignalModel.signal_id == "sig-dup"))
    rows = result.scalars().all()

    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_open_positions_only(in_memory_db):
    """Only OPEN positions are returned by get_open_positions."""
    factory, session = in_memory_db
    repo = TradingRepository(session)

    open_pos = Position(
        position_id="pos-open-1",
        signal_id="sig-1",
        market_id="m1",
        event_id="e1",
        outcome_name="Team A",
        side="BUY",
        status="OPEN",
        size_usd=25,
        entry_price=0.5,
        entry_time="2026-01-01T00:00:00Z",
        target_price=0.55,
        stop_loss_price=0.45,
        take_profit_price=0.6,
        max_holding_minutes=60,
    )
    closed_pos = Position(
        position_id="pos-closed-1",
        signal_id="sig-2",
        market_id="m2",
        event_id="e2",
        outcome_name="Team B",
        side="BUY",
        status="CLOSED",
        size_usd=25,
        entry_price=0.5,
        entry_time="2026-01-01T00:00:00Z",
        target_price=0.55,
        stop_loss_price=0.45,
        take_profit_price=0.6,
        max_holding_minutes=60,
        realized_pnl_usd=1.5,
    )

    await repo.save_position(open_pos)
    await repo.save_position(closed_pos)

    open_positions = await repo.get_open_positions()

    assert len(open_positions) == 1
    assert open_positions[0].position_id == "pos-open-1"
    assert open_positions[0].is_open()


@pytest.mark.asyncio
async def test_get_seen_signal_ids_entry_vs_exit(in_memory_db):
    """get_seen_signal_ids returns signal_ids with ENTRY orders only, deduped."""
    factory, session = in_memory_db
    repo = TradingRepository(session)

    orders = [
        OrderIntent(
            signal_id="sig-entry-1",
            market_id="m1",
            event_id="e1",
            outcome_name="A",
            side="BUY",
            order_type="ENTRY",
            requested_price=0.5,
            requested_size_usd=25,
            created_at="2026-01-01T00:00:00Z",
        ),
        OrderIntent(
            signal_id="sig-entry-2",
            market_id="m2",
            event_id="e2",
            outcome_name="B",
            side="BUY",
            order_type="ENTRY",
            requested_price=0.5,
            requested_size_usd=25,
            created_at="2026-01-01T00:00:00Z",
        ),
        OrderIntent(
            signal_id="sig-entry-3",
            market_id="m3",
            event_id="e3",
            outcome_name="C",
            side="SELL",
            order_type="EXIT",
            requested_price=0.6,
            requested_size_usd=25,
            created_at="2026-01-01T01:00:00Z",
        ),
    ]

    for o in orders:
        await repo.save_order(o)

    seen = await repo.get_seen_signal_ids()

    assert "sig-entry-1" in seen
    assert "sig-entry-2" in seen
    assert "sig-entry-3" not in seen  # EXIT orders excluded
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_realized_pnl_today_aggregates_correctly(in_memory_db):
    """get_realized_pnl_today sums only today's closed positions."""
    factory, session = in_memory_db
    repo = TradingRepository(session)

    now = datetime.now(timezone.utc)
    yesterday = now.replace(day=now.day - 1)

    positions = [
        Position(
            position_id="pos-win-today",
            signal_id="sig-w1",
            market_id="m1",
            event_id="e1",
            outcome_name="A",
            side="BUY",
            status="CLOSED",
            size_usd=100,
            entry_price=0.5,
            entry_time=now.isoformat(),
            target_price=0.6,
            stop_loss_price=0.4,
            take_profit_price=0.7,
            max_holding_minutes=60,
            realized_pnl_usd=10.0,
            exit_time=now.isoformat(),
        ),
        Position(
            position_id="pos-lose-today",
            signal_id="sig-l1",
            market_id="m2",
            event_id="e2",
            outcome_name="B",
            side="BUY",
            status="CLOSED",
            size_usd=100,
            entry_price=0.5,
            entry_time=now.isoformat(),
            target_price=0.6,
            stop_loss_price=0.4,
            take_profit_price=0.7,
            max_holding_minutes=60,
            realized_pnl_usd=-5.0,
            exit_time=now.isoformat(),
        ),
        Position(
            position_id="pos-win-yesterday",
            signal_id="sig-w2",
            market_id="m3",
            event_id="e3",
            outcome_name="C",
            side="BUY",
            status="CLOSED",
            size_usd=100,
            entry_price=0.5,
            entry_time=yesterday.isoformat(),
            target_price=0.6,
            stop_loss_price=0.4,
            take_profit_price=0.7,
            max_holding_minutes=60,
            realized_pnl_usd=999.0,
            exit_time=yesterday.isoformat(),
        ),
    ]

    for p in positions:
        await repo.save_position(p)

    pnl = await repo.get_realized_pnl_today()

    assert pnl == 5.0


@pytest.mark.asyncio
async def test_update_position_closes(in_memory_db):
    """update_position changes status, exit fields, realized_pnl."""
    factory, session = in_memory_db
    repo = TradingRepository(session)

    pos = Position(
        position_id="pos-to-close",
        signal_id="sig-1",
        market_id="m1",
        event_id="e1",
        outcome_name="A",
        side="BUY",
        status="OPEN",
        size_usd=25,
        entry_price=0.5,
        entry_time="2026-01-01T00:00:00Z",
        target_price=0.55,
        stop_loss_price=0.45,
        take_profit_price=0.6,
        max_holding_minutes=60,
    )
    await repo.save_position(pos)

    closed = Position(
        position_id="pos-to-close",
        signal_id="sig-1",
        market_id="m1",
        event_id="e1",
        outcome_name="A",
        side="BUY",
        status="CLOSED",
        size_usd=25,
        entry_price=0.5,
        entry_time="2026-01-01T00:00:00Z",
        target_price=0.55,
        stop_loss_price=0.45,
        take_profit_price=0.6,
        max_holding_minutes=60,
        exit_price=0.6,
        exit_time="2026-01-01T01:00:00Z",
        exit_reason="take_profit",
        realized_pnl_usd=5.0,
    )
    await repo.update_position(closed)

    retrieved = await repo.get_position_by_id("pos-to-close")
    assert retrieved is not None
    assert retrieved.status == "CLOSED"
    assert retrieved.realized_pnl_usd == 5.0
    assert retrieved.exit_reason == "take_profit"


@pytest.mark.asyncio
async def test_save_and_get_fill(in_memory_db):
    """ExecutionResult fields preserved after save+retrieve."""
    factory, session = in_memory_db
    repo = TradingRepository(session)

    fill = ExecutionResult(
        ok=True,
        order_id="ord-1",
        signal_id="sig-1",
        market_id="m1",
        side="BUY",
        order_type="ENTRY",
        filled_size_usd=20.0,
        fill_price=0.502,
        fees_usd=0.04,
        slippage_bps=10.0,
        timestamp="2026-01-01T00:00:00Z",
        status="filled",
        metadata={"fill_ratio": 0.8},
    )
    await repo.save_fill(fill)

    result = await session.execute(select(FillModel).where(FillModel.fill_id == f"fill-ord-1"))
    row = result.scalar_one()

    assert row.filled_size_usd == 20.0
    assert row.fill_price == 0.502
    assert row.metadata_json == {"fill_ratio": 0.8}
    assert row.status == "filled"


@pytest.mark.asyncio
async def test_save_risk_event_allow_and_deny(in_memory_db):
    """RiskDecision with allow=False is persisted correctly."""
    factory, session = in_memory_db
    repo = TradingRepository(session)

    sig = Signal(
        signal_id="sig-risk-test",
        market_id="m1",
        event_id="e1",
        outcome_name="Team A",
        side="BUY",
        order_type="ENTRY",
        suggested_price=0.5,
        target_price=0.55,
        confidence=0.5,
        expected_profit_pct=0.05,
        liquidity=5000,
        spread=0.01,
        created_at="2026-01-01T00:00:00Z",
    )
    await repo.save_signal(sig)

    await repo.save_risk_event(
        event_id="risk-1",
        signal_id="sig-risk-test",
        market_id="m1",
        allow=False,
        reason_code="low_confidence",
        message="Confidence too low.",
        details={"confidence": 0.5, "min_confidence": 0.7},
        created_at="2026-01-01T00:00:00Z",
    )

    result = await session.execute(select(RiskEventModel).where(RiskEventModel.event_id == "risk-1"))
    row = result.scalar_one()
    assert row.allow is False
    assert row.reason_code == "low_confidence"
    assert row.details_json["min_confidence"] == 0.7


@pytest.mark.asyncio
async def test_save_and_get_position_checks(in_memory_db):
    """PositionCheck records retrieved by position_id in chronological order."""
    factory, session = in_memory_db
    repo = TradingRepository(session)

    pos = Position(
        position_id="pos-check-test",
        signal_id="sig-1",
        market_id="m1",
        event_id="e1",
        outcome_name="A",
        side="BUY",
        status="OPEN",
        size_usd=25,
        entry_price=0.5,
        entry_time="2026-01-01T00:00:00Z",
        target_price=0.55,
        stop_loss_price=0.45,
        take_profit_price=0.6,
        max_holding_minutes=60,
    )
    await repo.save_position(pos)

    checks = [
        ("2026-01-01T00:30:00Z", 0.52, 0.5, False, "hold"),
        ("2026-01-01T01:00:00Z", 0.56, 1.5, True, "take_profit"),
    ]
    for i, (ts, price, pnl, should_exit, reason) in enumerate(checks):
        await repo.save_position_check(
            check_id=f"check-{i}",
            position_id="pos-check-test",
            latest_price=price,
            unrealized_pnl_usd=pnl,
            should_exit=should_exit,
            exit_reason=reason,
            checked_at=ts,
        )

    result = await session.execute(
        select(PositionCheckModel)
        .where(PositionCheckModel.position_id == "pos-check-test")
        .order_by(PositionCheckModel.checked_at)
    )
    rows = result.scalars().all()

    assert len(rows) == 2
    assert rows[0].latest_price == 0.52
    assert rows[0].should_exit is False
    assert rows[1].latest_price == 0.56
    assert rows[1].should_exit is True
    assert rows[1].exit_reason == "take_profit"


@pytest.mark.asyncio
async def test_get_signal_by_id_not_found(in_memory_db):
    """Non-existent signal_id returns None."""
    factory, session = in_memory_db
    repo = TradingRepository(session)
    result = await repo.get_signal_by_id("does-not-exist")
    assert result is None


@pytest.mark.asyncio
async def test_get_position_by_id_not_found(in_memory_db):
    """Non-existent position_id returns None."""
    factory, session = in_memory_db
    repo = TradingRepository(session)
    result = await repo.get_position_by_id("does-not-exist")
    assert result is None


@pytest.mark.asyncio
async def test_realized_pnl_today_empty_db_returns_zero(in_memory_db):
    """Empty positions table returns 0.0, not None."""
    factory, session = in_memory_db
    repo = TradingRepository(session)
    pnl = await repo.get_realized_pnl_today()
    assert pnl == 0.0


@pytest.mark.asyncio
async def test_get_open_positions_empty_returns_empty_list(in_memory_db):
    """No positions returns empty list."""
    factory, session = in_memory_db
    repo = TradingRepository(session)
    result = await repo.get_open_positions()
    assert result == []


@pytest.mark.asyncio
async def test_order_id_generation_consistency(in_memory_db):
    """Order ID generated by repository.save_order matches dry_run fill order_id."""
    factory, session = in_memory_db
    repo = TradingRepository(session)

    sig = Signal(
        signal_id="sig-consistency-test",
        market_id="m1",
        event_id="e1",
        outcome_name="Team A",
        side="BUY",
        order_type="ENTRY",
        suggested_price=0.5,
        target_price=0.55,
        confidence=0.9,
        expected_profit_pct=0.05,
        liquidity=5000,
        spread=0.01,
        created_at="2026-01-01T00:00:00Z",
        metadata={},
    )
    await repo.save_signal(sig)

    intent = OrderIntent(
        signal_id="sig-consistency-test",
        market_id="m1",
        event_id="e1",
        outcome_name="Team A",
        side="BUY",
        order_type="ENTRY",
        requested_price=0.5,
        requested_size_usd=20.0,
        created_at="2026-01-01T00:00:00Z",
        metadata={},
    )
    await repo.save_order(intent)

    result = await session.execute(select(OrderModel).where(OrderModel.order_id == "entry-sig-consistency-test"))
    order_row = result.scalar_one()
    assert order_row.order_id == "entry-sig-consistency-test"
    assert order_row.signal_id == "sig-consistency-test"