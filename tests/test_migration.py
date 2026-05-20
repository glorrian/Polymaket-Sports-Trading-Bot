"""Tests for the JSONL -> SQLite migration script."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from poly_sports.db.models import Base


@pytest.fixture
def db_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine)
    yield engine, Session
    engine.dispose()


def test_migrate_signals_deduplicates(tmp_path: Path, db_engine):
    """Duplicate signal_id in JSONL results in single DB record."""
    engine, Session = db_engine

    journal_dir = tmp_path / "trading"
    journal_dir.mkdir()
    signals_file = journal_dir / "signals.jsonl"

    sig_data = {
        "signal_id": "sig-dup",
        "market_id": "m1",
        "event_id": "e1",
        "outcome_name": "A",
        "side": "BUY",
        "order_type": "ENTRY",
        "suggested_price": 0.5,
        "target_price": 0.55,
        "confidence": 0.9,
        "expected_profit_pct": 0.05,
        "liquidity": 5000,
        "spread": 0.01,
        "created_at": "2026-01-01T00:00:00",
    }
    signals_file.write_text(json.dumps(sig_data) + "\n" + json.dumps(sig_data) + "\n")
    (journal_dir / "state.json").write_text('{"positions": []}')

    with patch("scripts.migrate_jsonl_to_sqlite.DATA_DIR", journal_dir):
        from scripts.migrate_jsonl_to_sqlite import migrate_signals

        with Session() as session:
            count = migrate_signals(session)

    assert count == 1

    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM signals WHERE signal_id = 'sig-dup'"))
        assert result.scalar() == 1


def test_migrate_fills_no_fk_error(tmp_path: Path, db_engine):
    """Fills with order_id not in orders table import without FK error."""
    engine, Session = db_engine

    journal_dir = tmp_path / "trading"
    journal_dir.mkdir()
    (journal_dir / "state.json").write_text('{"positions": []}')
    (journal_dir / "signals.jsonl").write_text("")
    (journal_dir / "orders.jsonl").write_text("")

    fills_file = journal_dir / "fills.jsonl"
    fills_file.write_text(
        json.dumps({
            "fill_id": "fill-x",
            "order_id": "non-existent-order",
            "signal_id": "sig-1",
            "market_id": "m1",
            "side": "BUY",
            "order_type": "ENTRY",
            "filled_size_usd": 10,
            "fill_price": 0.5,
            "fees_usd": 0.01,
            "slippage_bps": 10,
            "timestamp": "2026-01-01T00:00:00",
        }) + "\n"
    )

    with patch("scripts.migrate_jsonl_to_sqlite.DATA_DIR", journal_dir):
        from scripts.migrate_jsonl_to_sqlite import migrate_fills_no_fk

        with Session() as session:
            count = migrate_fills_no_fk(session)

    assert count == 1


def test_migrate_position_checks_handles_null_current_price(tmp_path: Path, db_engine):
    """position_checks with null current_price become latest_price=0."""
    engine, Session = db_engine

    journal_dir = tmp_path / "trading"
    journal_dir.mkdir()
    (journal_dir / "state.json").write_text('{"positions": []}')
    (journal_dir / "signals.jsonl").write_text("")
    (journal_dir / "orders.jsonl").write_text("")
    (journal_dir / "fills.jsonl").write_text("")
    (journal_dir / "risk_events.jsonl").write_text("")

    checks_file = journal_dir / "position_checks.jsonl"
    checks_file.write_text(
        json.dumps({
            "position_id": "pos-1",
            "current_price": None,
            "unrealized_pnl_usd": 0.0,
            "should_exit": False,
            "reason": "hold",
            "timestamp": "2026-01-01T00:00:00",
        }) + "\n"
    )

    with patch("scripts.migrate_jsonl_to_sqlite.DATA_DIR", journal_dir):
        from scripts.migrate_jsonl_to_sqlite import migrate_position_checks

        with Session() as session:
            count = migrate_position_checks(session)

    assert count == 1

    with engine.connect() as conn:
        result = conn.execute(text("SELECT latest_price FROM position_checks"))
        assert result.fetchone()[0] == 0.0


def test_migrate_positions_open_and_closed(tmp_path: Path, db_engine):
    """OPEN and CLOSED positions from state.json migrated correctly."""
    engine, Session = db_engine

    journal_dir = tmp_path / "trading"
    journal_dir.mkdir()

    sig_data = {
        "signal_id": "sig-mig",
        "market_id": "m1",
        "event_id": "e1",
        "outcome_name": "A",
        "side": "BUY",
        "order_type": "ENTRY",
        "suggested_price": 0.5,
        "target_price": 0.55,
        "confidence": 0.9,
        "expected_profit_pct": 0.05,
        "liquidity": 5000,
        "spread": 0.01,
        "created_at": "2026-01-01T00:00:00",
    }
    (journal_dir / "signals.jsonl").write_text(json.dumps(sig_data) + "\n")
    (journal_dir / "orders.jsonl").write_text("")
    (journal_dir / "fills.jsonl").write_text("")
    (journal_dir / "risk_events.jsonl").write_text("")

    state = {
        "positions": [
            {
                "position_id": "pos-open-1",
                "signal_id": "sig-mig",
                "market_id": "m1",
                "event_id": "e1",
                "outcome_name": "A",
                "side": "BUY",
                "status": "OPEN",
                "size_usd": 25,
                "entry_price": 0.5,
                "entry_time": "2026-01-01T00:00:00Z",
                "target_price": 0.55,
                "stop_loss_price": 0.45,
                "take_profit_price": 0.6,
                "max_holding_minutes": 60,
            },
            {
                "position_id": "pos-closed-1",
                "signal_id": "sig-mig",
                "market_id": "m1",
                "event_id": "e1",
                "outcome_name": "A",
                "side": "BUY",
                "status": "CLOSED",
                "size_usd": 25,
                "entry_price": 0.5,
                "entry_time": "2026-01-01T00:00:00Z",
                "target_price": 0.55,
                "stop_loss_price": 0.45,
                "take_profit_price": 0.6,
                "max_holding_minutes": 60,
                "exit_price": 0.6,
                "exit_time": "2026-01-01T01:00:00Z",
                "exit_reason": "take_profit",
                "realized_pnl_usd": 5.0,
            },
        ]
    }
    (journal_dir / "state.json").write_text(json.dumps(state))

    # Need to patch DATA_DIR before importing the migration module
    import sys
    import importlib
    if "scripts.migrate_jsonl_to_sqlite" in sys.modules:
        del sys.modules["scripts.migrate_jsonl_to_sqlite"]

    with patch("scripts.migrate_jsonl_to_sqlite.DATA_DIR", journal_dir):
        from scripts.migrate_jsonl_to_sqlite import migrate_signals, migrate_positions_from_state

        with Session() as session:
            migrate_signals(session)
        with Session() as session:
            count = migrate_positions_from_state(session)

    assert count == 2

    with engine.connect() as conn:
        open_count = conn.execute(
            text("SELECT COUNT(*) FROM positions WHERE status = 'OPEN'")
        ).scalar()
        closed_count = conn.execute(
            text("SELECT COUNT(*) FROM positions WHERE status = 'CLOSED'")
        ).scalar()
        realized = conn.execute(
            text("SELECT realized_pnl_usd FROM positions WHERE position_id = 'pos-closed-1'")
        ).scalar()

    assert open_count == 1
    assert closed_count == 1
    assert realized == 5.0


def test_migrate_risk_events_deduplicates(tmp_path: Path, db_engine):
    """Duplicate event_ids in risk_events.jsonl result in single DB record."""
    engine, Session = db_engine
    journal_dir = tmp_path / "trading"
    journal_dir.mkdir()
    (journal_dir / "state.json").write_text('{"positions": []}')

    sig_data = {
        "signal_id": "sig-risk-dup",
        "market_id": "m1",
        "event_id": "e1",
        "outcome_name": "A",
        "side": "BUY",
        "order_type": "ENTRY",
        "suggested_price": 0.5,
        "target_price": 0.55,
        "confidence": 0.9,
        "expected_profit_pct": 0.05,
        "liquidity": 5000,
        "spread": 0.01,
        "created_at": "2026-01-01T00:00:00",
    }
    (journal_dir / "signals.jsonl").write_text(json.dumps(sig_data) + "\n")
    (journal_dir / "orders.jsonl").write_text("")
    (journal_dir / "fills.jsonl").write_text("")

    risk_data = {
        "signal_id": "sig-risk-dup",
        "market_id": "m1",
        "allow": False,
        "reason_code": "low_confidence",
        "message": "Reject.",
        "details": {},
        "timestamp": "2026-01-01T00:00:00",
    }
    (journal_dir / "risk_events.jsonl").write_text(
        json.dumps(risk_data) + "\n" + json.dumps(risk_data) + "\n"
    )

    import sys
    if "scripts.migrate_jsonl_to_sqlite" in sys.modules:
        del sys.modules["scripts.migrate_jsonl_to_sqlite"]

    with patch("scripts.migrate_jsonl_to_sqlite.DATA_DIR", journal_dir):
        from scripts.migrate_jsonl_to_sqlite import migrate_signals, migrate_risk_events

        with Session() as session:
            migrate_signals(session)
        with Session() as session:
            count = migrate_risk_events(session)

    assert count == 1

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT COUNT(*) FROM risk_events WHERE signal_id = 'sig-risk-dup'")
        ).scalar()
        assert result == 1