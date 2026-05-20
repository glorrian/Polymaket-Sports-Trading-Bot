"""Export historical DB snapshots into replay-ready JSONL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from poly_sports.db.database import get_sync_session
from poly_sports.db.history_repository import HistoryRepository, parse_ts, sanitize_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export replay JSONL from historical SQLite snapshots")
    parser.add_argument("--start", required=True, help="Inclusive ISO timestamp, e.g. 2026-05-20T00:00:00Z")
    parser.add_argument("--end", required=True, help="Inclusive ISO timestamp, e.g. 2026-05-21T00:00:00Z")
    parser.add_argument("--sport-key", default=None, help="Optional sportsbook sport key filter")
    parser.add_argument("--market-id", default=None, help="Optional Polymarket market id filter")
    parser.add_argument("--output", default="data/replay_dataset.jsonl", help="Output JSONL path")
    return parser.parse_args()


def _tagged(kind: str, rows: Iterable[Dict]) -> Iterable[Dict]:
    for row in rows:
        yield {"type": kind, **row}


def main() -> None:
    args = parse_args()
    start_at = parse_ts(args.start)
    end_at = parse_ts(args.end)
    if start_at is None or end_at is None:
        raise SystemExit("--start and --end must be valid ISO timestamps")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    session = get_sync_session()
    try:
        repo = HistoryRepository(session)
        comparison_rows = repo.iter_comparison_snapshots(
            start_at,
            end_at,
            sport_key=args.sport_key,
            market_id=args.market_id,
        )
        live_rows = repo.iter_live_price_snapshots(
            start_at,
            end_at,
            market_id=args.market_id,
        )
        total = 0
        with open(output, "w", encoding="utf-8") as fh:
            for row in _tagged("comparison", comparison_rows):
                fh.write(json.dumps(sanitize_json(row), ensure_ascii=False) + "\n")
                total += 1
            for row in _tagged("live_price", live_rows):
                fh.write(json.dumps(sanitize_json(row), ensure_ascii=False) + "\n")
                total += 1
    finally:
        session.close()

    print(f"Exported {total} replay rows to {output}")


if __name__ == "__main__":
    main()
