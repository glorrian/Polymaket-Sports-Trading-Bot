"""Tests for append-only historical capture repository."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from poly_sports.db.history_repository import HistoryRepository
from poly_sports.db.models import (
    ComparisonSnapshot,
    EventMatchSnapshot,
    LivePriceSnapshot,
    PolymarketMarketSnapshot,
    RawPayload,
    SportsbookEventSnapshot,
    SportsbookOddsSnapshot,
)


@pytest.mark.asyncio
async def test_raw_payload_redacts_secrets_and_keeps_duplicates(in_memory_db):
    _, session = in_memory_db
    repo = HistoryRepository(session)
    run_id = await repo.start_data_run("test_run", "unit", config={"private_key": "secret"})

    for _ in range(2):
        await repo.save_raw_payload(
            source="odds_api",
            endpoint="https://example.test/odds",
            request_params={"apiKey": "secret", "bookmaker_key": "fanduel"},
            payload={"data": [{"id": "event-1"}], "ODDS_API_KEY": "secret"},
            run_id=run_id,
        )

    result = await session.execute(select(RawPayload).where(RawPayload.run_id == run_id))
    rows = result.scalars().all()

    assert len(rows) == 2
    assert rows[0].payload_hash == rows[1].payload_hash
    assert rows[0].request_params_json["apiKey"] == "[REDACTED]"
    assert rows[0].request_params_json["bookmaker_key"] == "fanduel"
    assert rows[0].payload_json["ODDS_API_KEY"] == "[REDACTED]"
    assert rows[0].row_count == 1


@pytest.mark.asyncio
async def test_history_repository_saves_normalized_snapshots(in_memory_db):
    _, session = in_memory_db
    repo = HistoryRepository(session)
    run_id = await repo.start_data_run("test_run", "unit")

    await repo.save_polymarket_market_snapshots(
        [{
            "event_id": "pm-event-1",
            "market_id": "pm-market-1",
            "conditionId": "cond-1",
            "market_outcomes": '["Team A", "Team B"]',
            "market_outcomePrices": '["0.55", "0.45"]',
            "clobTokenIds": '["tok-a", "tok-b"]',
            "market_liquidityNum": 1000,
            "spread": 0.02,
        }],
        run_id=run_id,
    )
    await repo.save_sportsbook_event_snapshots(
        "americanfootball_nfl",
        [{"id": "odds-event-1", "home_team": "Team A", "away_team": "Team B"}],
        run_id=run_id,
    )
    await repo.save_sportsbook_odds_snapshots(
        "americanfootball_nfl",
        [{
            "id": "odds-event-1",
            "bookmakers": [{
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [{"key": "h2h", "outcomes": [{"name": "Team A", "price": -110}]}],
            }],
        }],
        run_id=run_id,
    )
    await repo.save_event_match_snapshots(
        "americanfootball_nfl",
        [{
            "pm_event": {"event_id": "pm-event-1", "market_id": "pm-market-1"},
            "odds_event": {"id": "odds-event-1"},
            "confidence": 0.9,
        }],
        run_id=run_id,
    )
    await repo.save_comparison_snapshots(
        [{
            "pm_event_id": "pm-event-1",
            "pm_market_id": "pm-market-1",
            "odds_api_event_id": "odds-event-1",
            "odds_api_sport_key": "americanfootball_nfl",
            "match_confidence": 0.9,
            "sportsbook_count": 1,
        }],
        run_id=run_id,
    )
    await repo.save_live_price_snapshots(
        [{"market_id": "pm-market-1", "outcome_name": "Team A", "price": 0.56}],
        run_id=run_id,
    )

    for model, expected in [
        (PolymarketMarketSnapshot, 2),
        (SportsbookEventSnapshot, 1),
        (SportsbookOddsSnapshot, 1),
        (EventMatchSnapshot, 1),
        (ComparisonSnapshot, 1),
        (LivePriceSnapshot, 1),
    ]:
        result = await session.execute(select(model).where(model.run_id == run_id))
        assert len(result.scalars().all()) == expected


def test_sync_read_helpers_export_replay_rows(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from poly_sports.db.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine)
    session = Session()
    try:
        repo = HistoryRepository(session)
        run_id = repo.start_data_run_sync("test_run", "unit")
        repo.save_comparison_snapshots_sync(
            [{"pm_market_id": "m1", "odds_api_sport_key": "basketball_nba"}],
            run_id=run_id,
            captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        rows = list(
            repo.iter_comparison_snapshots(
                datetime(2025, 12, 31, tzinfo=timezone.utc),
                datetime(2026, 1, 2, tzinfo=timezone.utc),
                sport_key="basketball_nba",
                market_id="m1",
            )
        )
    finally:
        session.close()

    assert len(rows) == 1
    assert rows[0]["comparison"]["pm_market_id"] == "m1"
