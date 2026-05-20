"""One-time script: migrate trading data from JSONL + state.json to SQLite."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from sqlalchemy import text

from poly_sports.db.database import get_sync_session
from poly_sports.db.models import Base, Signal as SignalModel, Order as OrderModel, Fill as FillModel, Position as PositionModel, RiskEvent as RiskEventModel, PositionCheck as PositionCheckModel


DATA_DIR = Path("data/trading")
STATE_FILE = DATA_DIR / "state.json"


def _parse_ts(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def migrate_signals(session) -> int:
    path = DATA_DIR / "signals.jsonl"
    if not path.exists():
        return 0
    count = 0
    seen = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                sid = data["signal_id"]
                if sid in seen:
                    continue
                seen.add(sid)
                model = SignalModel(
                    signal_id=sid,
                    market_id=data["market_id"],
                    event_id=data["event_id"],
                    outcome_name=data["outcome_name"],
                    side=data["side"],
                    order_type=data["order_type"],
                    suggested_price=data["suggested_price"],
                    target_price=data["target_price"],
                    confidence=data["confidence"],
                    expected_profit_pct=data["expected_profit_pct"],
                    liquidity=data["liquidity"],
                    spread=data["spread"],
                    created_at=_parse_ts(data["created_at"]),
                    metadata_json=data.get("metadata", {}),
                )
                session.add(model)
                count += 1
            except (json.JSONDecodeError, KeyError):
                continue
    session.commit()
    print(f"  signals: {count}")
    return count


def migrate_orders(session) -> int:
    path = DATA_DIR / "orders.jsonl"
    if not path.exists():
        return 0
    count = 0
    seen = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                oid = data.get("order_id", f"ord-{data['signal_id']}")
                if oid in seen:
                    continue
                seen.add(oid)
                model = OrderModel(
                    order_id=f"paper-{data['signal_id'][:10]}",
                    signal_id=data["signal_id"],
                    market_id=data["market_id"],
                    event_id=data["event_id"],
                    outcome_name=data["outcome_name"],
                    side=data["side"],
                    order_type=data["order_type"],
                    requested_price=data["requested_price"],
                    requested_size_usd=data["requested_size_usd"],
                    created_at=_parse_ts(data["created_at"]),
                    metadata_json=data.get("metadata", {}),
                )
                session.add(model)
                count += 1
            except (json.JSONDecodeError, KeyError):
                continue
    session.commit()
    print(f"  orders: {count}")
    return count


def migrate_fills(session) -> int:
    path = DATA_DIR / "fills.jsonl"
    if not path.exists():
        return 0
    count = 0
    seen = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                fid = data.get("fill_id", f"fill-{data['order_id']}")
                if fid in seen:
                    continue
                seen.add(fid)
                model = FillModel(
                    fill_id=fid,
                    order_id=data["order_id"],
                    signal_id=data["signal_id"],
                    market_id=data["market_id"],
                    side=data["side"],
                    order_type=data["order_type"],
                    filled_size_usd=data.get("filled_size_usd", 0.0),
                    fill_price=data.get("fill_price", 0.0),
                    fees_usd=data.get("fees_usd", 0.0),
                    slippage_bps=data.get("slippage_bps", 0.0),
                    timestamp=_parse_ts(data.get("timestamp", data.get("created_at", ""))),
                    status=data.get("status", "filled"),
                    error=data.get("error"),
                    metadata_json=data.get("metadata", {}),
                )
                session.add(model)
                count += 1
            except (json.JSONDecodeError, KeyError):
                continue
    session.commit()
    print(f"  fills: {count}")
    return count


def migrate_fills_no_fk(session) -> int:
    """Migrate fills without FK constraint (order_id may not match orders table)."""
    path = DATA_DIR / "fills.jsonl"
    if not path.exists():
        return 0
    count = 0
    seen = set()
    session.execute(text("PRAGMA foreign_keys=OFF"))
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                fid = data.get("fill_id", f"fill-{data['order_id']}")
                if fid in seen:
                    continue
                seen.add(fid)
                model = FillModel(
                    fill_id=fid,
                    order_id=data["order_id"],
                    signal_id=data["signal_id"],
                    market_id=data["market_id"],
                    side=data["side"],
                    order_type=data["order_type"],
                    filled_size_usd=data.get("filled_size_usd", 0.0),
                    fill_price=data.get("fill_price", 0.0),
                    fees_usd=data.get("fees_usd", 0.0),
                    slippage_bps=data.get("slippage_bps", 0.0),
                    timestamp=_parse_ts(data.get("timestamp", data.get("created_at", ""))),
                    status=data.get("status", "filled"),
                    error=data.get("error"),
                    metadata_json=data.get("metadata", {}),
                )
                session.add(model)
                count += 1
            except (json.JSONDecodeError, KeyError):
                continue
    session.commit()
    session.execute(text("PRAGMA foreign_keys=ON"))
    print(f"  fills: {count}")
    return count


def migrate_positions_from_state(session) -> int:
    state_path = DATA_DIR / "state.json"
    if not state_path.exists():
        return 0
    state = json.loads(state_path.read_text())
    count = 0
    for row in state.get("positions", []):
        try:
            model = PositionModel(
                position_id=row["position_id"],
                signal_id=row["signal_id"],
                market_id=row["market_id"],
                event_id=row["event_id"],
                outcome_name=row["outcome_name"],
                side=row["side"],
                status=row["status"],
                size_usd=row["size_usd"],
                entry_price=row["entry_price"],
                entry_time=_parse_ts(row["entry_time"]),
                target_price=row["target_price"],
                stop_loss_price=row["stop_loss_price"],
                take_profit_price=row["take_profit_price"],
                max_holding_minutes=row["max_holding_minutes"],
                entry_fees_usd=row.get("entry_fees_usd", 0.0),
                exit_price=row.get("exit_price"),
                exit_time=_parse_ts(row["exit_time"]) if row.get("exit_time") else None,
                exit_reason=row.get("exit_reason"),
                exit_fees_usd=row.get("exit_fees_usd", 0.0),
                realized_pnl_usd=row.get("realized_pnl_usd", 0.0),
                unrealized_pnl_usd=row.get("unrealized_pnl_usd", 0.0),
                metadata_json=row.get("metadata", {}),
            )
            session.add(model)
            count += 1
        except KeyError:
            continue
    session.commit()
    print(f"  positions: {count}")
    return count


def migrate_risk_events(session) -> int:
    path = DATA_DIR / "risk_events.jsonl"
    if not path.exists():
        return 0
    count = 0
    seen = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                sid = data["signal_id"]
                if sid in seen:
                    continue
                seen.add(sid)
                model = RiskEventModel(
                    event_id=f"risk-{sid}",
                    signal_id=sid,
                    market_id=data["market_id"],
                    allow=data["allow"],
                    reason_code=data["reason_code"],
                    message=data["message"],
                    details_json=data.get("details", {}),
                    created_at=_parse_ts(data.get("timestamp", "")),
                )
                session.add(model)
                count += 1
            except (json.JSONDecodeError, KeyError):
                continue
    session.commit()
    print(f"  risk_events: {count}")
    return count


def migrate_position_checks(session) -> int:
    path = DATA_DIR / "position_checks.jsonl"
    if not path.exists():
        return 0
    count = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                model = PositionCheckModel(
                    check_id=f"check-{data['position_id']}-{count}",
                    position_id=data["position_id"],
                    latest_price=data.get("current_price") or 0.0,
                    unrealized_pnl_usd=data.get("unrealized_pnl_usd", 0.0),
                    should_exit=data.get("should_exit", False),
                    exit_reason=data.get("reason"),
                    checked_at=_parse_ts(data.get("timestamp", "")),
                )
                session.add(model)
                count += 1
            except (json.JSONDecodeError, KeyError):
                continue
    session.commit()
    print(f"  position_checks: {count}")
    return count


def main() -> None:
    print("Migrating JSONL data to SQLite...")
    print(f"Data directory: {DATA_DIR}")
    print(f"State file: {STATE_FILE}")

    session = get_sync_session()

    print("\nCreating tables...")
    Base.metadata.create_all(session.get_bind())
    print("  tables created\n")

    print("Importing data:")
    total = 0
    total += migrate_signals(session)
    total += migrate_orders(session)
    total += migrate_fills_no_fk(session)
    total += migrate_positions_from_state(session)
    total += migrate_risk_events(session)
    total += migrate_position_checks(session)

    print(f"\nTotal records migrated: {total}")
    print("Migration complete!")
    print(f"Database: data/trading.db")

    session.close()


if __name__ == "__main__":
    main()