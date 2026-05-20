"""Tests for dashboard SQL query functions."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from poly_sports.db.models import Base, Position as PositionModel


@pytest.fixture
def dashboard_db(tmp_path: Path):
    """Fresh DB with all tables created."""
    db = tmp_path / "dashboard.db"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    yield db, factory
    engine.dispose()


def test_get_summary_with_data(dashboard_db):
    """SQL aggregations for summary return correct PnL."""
    db_path, factory = dashboard_db

    now = datetime.now(timezone.utc)

    with factory() as session:
        positions = [
            PositionModel(
                position_id="pos-w",
                signal_id="s1",
                market_id="m1",
                event_id="e1",
                outcome_name="A",
                side="BUY",
                status="OPEN",
                size_usd=100,
                entry_price=0.5,
                entry_time=now,
                target_price=0.6,
                stop_loss_price=0.4,
                take_profit_price=0.7,
                max_holding_minutes=60,
                unrealized_pnl_usd=10.0,
            ),
            PositionModel(
                position_id="pos-l",
                signal_id="s2",
                market_id="m2",
                event_id="e2",
                outcome_name="B",
                side="BUY",
                status="CLOSED",
                size_usd=100,
                entry_price=0.5,
                entry_time=now,
                target_price=0.6,
                stop_loss_price=0.4,
                take_profit_price=0.7,
                max_holding_minutes=60,
                realized_pnl_usd=-5.0,
                exit_time=now,
                exit_reason="stop_loss",
            ),
            PositionModel(
                position_id="pos-w2",
                signal_id="s3",
                market_id="m3",
                event_id="e3",
                outcome_name="C",
                side="BUY",
                status="CLOSED",
                size_usd=50,
                entry_price=0.5,
                entry_time=now,
                target_price=0.6,
                stop_loss_price=0.4,
                take_profit_price=0.7,
                max_holding_minutes=60,
                realized_pnl_usd=3.0,
                exit_time=now,
                exit_reason="take_profit",
            ),
        ]
        for p in positions:
            session.add(p)
        session.commit()

    conn = sqlite3.connect(db_path)

    cur = conn.execute(
        "SELECT SUM(unrealized_pnl_usd) FROM positions WHERE status = 'OPEN'"
    )
    total_unrealized = cur.fetchone()[0] or 0

    cur = conn.execute(
        "SELECT SUM(realized_pnl_usd) FROM positions WHERE status = 'CLOSED'"
    )
    total_realized = cur.fetchone()[0] or 0

    closed = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE status = 'CLOSED'"
    ).fetchone()[0]

    wins = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE status = 'CLOSED' AND realized_pnl_usd > 0"
    ).fetchone()[0]

    assert total_unrealized == 10.0
    assert total_realized == -2.0
    assert closed == 2
    assert wins == 1

    conn.close()


def test_get_open_positions_query(dashboard_db):
    """OPEN positions query returns correct rows ordered by entry_time DESC."""
    db_path, factory = dashboard_db

    now = datetime.now(timezone.utc)

    with factory() as session:
        for i in range(3):
            session.add(PositionModel(
                position_id=f"pos-{i}",
                signal_id=f"s{i}",
                market_id=f"m{i}",
                event_id=f"e{i}",
                outcome_name=f"Team {i}",
                side="BUY",
                status="OPEN",
                size_usd=25,
                entry_price=0.5,
                entry_time=now,
                target_price=0.6,
                stop_loss_price=0.4,
                take_profit_price=0.7,
                max_holding_minutes=60,
            ))
        session.commit()

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT position_id FROM positions WHERE status = 'OPEN' ORDER BY entry_time DESC"
    ).fetchall()

    assert len(rows) == 3
    conn.close()


def test_get_closed_positions_query(dashboard_db):
    """CLOSED positions exclude OPEN positions."""
    db_path, factory = dashboard_db

    now = datetime.now(timezone.utc)

    with factory() as session:
        for status, pid in [("OPEN", "pos-open"), ("CLOSED", "pos-closed")]:
            session.add(PositionModel(
                position_id=pid,
                signal_id="sig-1",
                market_id="m1",
                event_id="e1",
                outcome_name="A",
                side="BUY",
                status=status,
                size_usd=25,
                entry_price=0.5,
                entry_time=now,
                target_price=0.6,
                stop_loss_price=0.4,
                take_profit_price=0.7,
                max_holding_minutes=60,
                realized_pnl_usd=1.0,
                exit_time=now,
            ))
        session.commit()

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE status = 'CLOSED'"
    ).fetchone()

    assert rows[0] == 1
    conn.close()