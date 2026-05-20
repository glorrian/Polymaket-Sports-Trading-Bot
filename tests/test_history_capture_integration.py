"""Capture integration tests around mocked fetchers."""

from unittest.mock import Mock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from poly_sports.data_fetching.fetch_odds_api import fetch_odds
from poly_sports.data_fetching.fetch_sports_markets import fetch_sports_markets
from poly_sports.db.history_capture import maybe_capture_data_run
from poly_sports.db.models import PolymarketMarketSnapshot, RawPayload


def _session_factory(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'capture.db'}")
    Session = sessionmaker(engine)

    def _get_session():
        return Session()

    monkeypatch.setattr("poly_sports.db.history_capture.get_sync_session", _get_session)
    return Session


def test_polymarket_fetch_capture_records_raw_and_snapshots(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path, monkeypatch)

    response = Mock()
    response.status_code = 200
    response.raise_for_status = Mock()
    response.json.return_value = [
        {
            "id": "event-1",
            "title": "Team A vs. Team B",
            "tags": [{"label": "Sports"}],
            "markets": [{
                "id": "market-1",
                "outcomes": '["Team A", "Team B"]',
                "outcomePrices": '["0.55", "0.45"]',
                "clobTokenIds": '["tok-a", "tok-b"]',
            }],
        }
    ]

    with patch("poly_sports.data_fetching.fetch_sports_markets.requests.get", return_value=response):
        with maybe_capture_data_run("fetch_test", "unit") as capture:
            markets = fetch_sports_markets("https://gamma-api.polymarket.com", limit=50)
            run_id = capture.run_id

    session = Session()
    try:
        raw_count = len(session.execute(select(RawPayload).where(RawPayload.run_id == run_id)).scalars().all())
        snapshots = session.execute(
            select(PolymarketMarketSnapshot).where(PolymarketMarketSnapshot.run_id == run_id)
        ).scalars().all()
    finally:
        session.close()

    assert len(markets) == 1
    assert raw_count == 1
    assert len(snapshots) >= 2
    assert {row.outcome_name for row in snapshots} >= {"Team A", "Team B"}


def test_odds_api_capture_redacts_api_key(tmp_path, monkeypatch):
    Session = _session_factory(tmp_path, monkeypatch)

    response = Mock()
    response.status_code = 200
    response.raise_for_status = Mock()
    response.json.return_value = [{"id": "event-1", "bookmakers": []}]

    with patch("poly_sports.data_fetching.fetch_odds_api.requests.get", return_value=response):
        with maybe_capture_data_run("odds_test", "unit") as capture:
            rows = fetch_odds("basketball_nba", api_key="secret-key")
            run_id = capture.run_id

    session = Session()
    try:
        raw = session.execute(select(RawPayload).where(RawPayload.run_id == run_id)).scalar_one()
    finally:
        session.close()

    assert rows[0]["id"] == "event-1"
    assert raw.request_params_json["apiKey"] == "[REDACTED]"
    assert raw.payload_json[0]["id"] == "event-1"
