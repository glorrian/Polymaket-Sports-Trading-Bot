"""Context-local helpers for optional historical data capture."""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, Iterator, Optional

from poly_sports.db.database import get_sync_session
from poly_sports.db.models import Base
from poly_sports.db.history_repository import HistoryRepository
from poly_sports.utils.logger import logger

_CURRENT_CAPTURE: ContextVar[Optional["SyncHistoryCapture"]] = ContextVar(
    "poly_sports_history_capture",
    default=None,
)


def is_data_capture_enabled(default: bool = True) -> bool:
    value = os.getenv("DATA_CAPTURE_ENABLED")
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _config_to_dict(config: Optional[Any]) -> Dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, dict):
        return dict(config)
    if is_dataclass(config):
        return asdict(config)
    if hasattr(config, "__dict__"):
        return dict(config.__dict__)
    return {"value": str(config)}


class SyncHistoryCapture:
    """Synchronous capture writer stored in a context variable."""

    def __init__(
        self,
        run_type: str,
        source: str,
        config: Optional[Any] = None,
        run_id: Optional[str] = None,
        start_run: bool = True,
    ) -> None:
        self.run_type = run_type
        self.source = source
        self.config = _config_to_dict(config)
        self.run_id = run_id
        self.start_run = start_run
        self.summary: Dict[str, Any] = {}
        self._session = None
        self._repo: Optional[HistoryRepository] = None
        self._token = None

    def __enter__(self) -> "SyncHistoryCapture":
        self._session = get_sync_session()
        Base.metadata.create_all(self._session.get_bind())
        self._repo = HistoryRepository(self._session)
        if self.start_run:
            self.run_id = self._repo.start_data_run_sync(
                run_type=self.run_type,
                source=self.source,
                config=self.config,
                run_id=self.run_id,
            )
        self._token = _CURRENT_CAPTURE.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.start_run and self._repo and self.run_id:
                status = "failed" if exc else "completed"
                self._repo.finish_data_run_sync(
                    self.run_id,
                    status=status,
                    summary=self.summary,
                    error=str(exc) if exc else None,
                )
        finally:
            if self._token is not None:
                _CURRENT_CAPTURE.reset(self._token)
            if self._session is not None:
                self._session.close()

    @property
    def repo(self) -> HistoryRepository:
        if self._repo is None:
            raise RuntimeError("Capture context has not been entered")
        return self._repo

    def set_summary(self, summary: Dict[str, Any]) -> None:
        self.summary = dict(summary or {})

    def update_summary(self, **items: Any) -> None:
        self.summary.update(items)

    def save_raw_payload(
        self,
        source: str,
        endpoint: str,
        payload: Any,
        request_params: Optional[Dict[str, Any]] = None,
        status: str = "ok",
        status_code: Optional[int] = None,
    ) -> Optional[str]:
        try:
            return self.repo.save_raw_payload_sync(
                source=source,
                endpoint=endpoint,
                payload=payload,
                request_params=request_params,
                run_id=self.run_id,
                status=status,
                status_code=status_code,
            )
        except Exception as exc:
            logger.info(f"Historical raw payload capture skipped: {exc}")
            return None

    def save_polymarket_market_snapshots(
        self,
        markets: Iterable[Dict[str, Any]],
        raw_payload_id: Optional[str] = None,
    ) -> int:
        try:
            return self.repo.save_polymarket_market_snapshots_sync(
                markets,
                run_id=self.run_id,
                raw_payload_id=raw_payload_id,
            )
        except Exception as exc:
            logger.info(f"Historical Polymarket snapshot capture skipped: {exc}")
            return 0

    def save_sportsbook_event_snapshots(
        self,
        sport_key: str,
        events: Iterable[Dict[str, Any]],
        raw_payload_id: Optional[str] = None,
    ) -> int:
        try:
            return self.repo.save_sportsbook_event_snapshots_sync(
                sport_key,
                events,
                run_id=self.run_id,
                raw_payload_id=raw_payload_id,
            )
        except Exception as exc:
            logger.info(f"Historical sportsbook event capture skipped: {exc}")
            return 0

    def save_sportsbook_odds_snapshots(
        self,
        sport_key: str,
        odds_events: Iterable[Dict[str, Any]],
        raw_payload_id: Optional[str] = None,
    ) -> int:
        try:
            return self.repo.save_sportsbook_odds_snapshots_sync(
                sport_key,
                odds_events,
                run_id=self.run_id,
                raw_payload_id=raw_payload_id,
            )
        except Exception as exc:
            logger.info(f"Historical sportsbook odds capture skipped: {exc}")
            return 0

    def save_event_match_snapshots(self, sport_key: str, matches: Iterable[Dict[str, Any]]) -> int:
        try:
            return self.repo.save_event_match_snapshots_sync(sport_key, matches, run_id=self.run_id)
        except Exception as exc:
            logger.info(f"Historical event match capture skipped: {exc}")
            return 0

    def save_comparison_snapshots(self, rows: Iterable[Dict[str, Any]]) -> int:
        try:
            return self.repo.save_comparison_snapshots_sync(rows, run_id=self.run_id)
        except Exception as exc:
            logger.info(f"Historical comparison capture skipped: {exc}")
            return 0

    def save_opportunity_snapshots(self, rows: Iterable[Dict[str, Any]]) -> int:
        try:
            return self.repo.save_opportunity_snapshots_sync(rows, run_id=self.run_id)
        except Exception as exc:
            logger.info(f"Historical opportunity capture skipped: {exc}")
            return 0


def current_capture() -> Optional[SyncHistoryCapture]:
    return _CURRENT_CAPTURE.get()


@contextmanager
def maybe_capture_data_run(
    run_type: str,
    source: str,
    config: Optional[Any] = None,
    run_id: Optional[str] = None,
    start_run: bool = True,
    enabled: Optional[bool] = None,
) -> Iterator[Optional[SyncHistoryCapture]]:
    """Create a capture run unless capture is disabled or one is already active."""
    active = current_capture()
    if active is not None:
        yield active
        return
    if enabled is None:
        enabled = is_data_capture_enabled(default=True)
    if not enabled:
        yield None
        return
    with SyncHistoryCapture(
        run_type=run_type,
        source=source,
        config=config,
        run_id=run_id,
        start_run=start_run,
    ) as capture:
        yield capture


def capture_raw_payload(
    source: str,
    endpoint: str,
    payload: Any,
    request_params: Optional[Dict[str, Any]] = None,
    status: str = "ok",
    status_code: Optional[int] = None,
) -> Optional[str]:
    capture = current_capture()
    if capture is None:
        return None
    return capture.save_raw_payload(source, endpoint, payload, request_params, status, status_code)


def capture_polymarket_market_snapshots(
    markets: Iterable[Dict[str, Any]],
    raw_payload_id: Optional[str] = None,
) -> int:
    capture = current_capture()
    if capture is None:
        return 0
    return capture.save_polymarket_market_snapshots(markets, raw_payload_id=raw_payload_id)


def capture_sportsbook_event_snapshots(
    sport_key: str,
    events: Iterable[Dict[str, Any]],
    raw_payload_id: Optional[str] = None,
) -> int:
    capture = current_capture()
    if capture is None:
        return 0
    return capture.save_sportsbook_event_snapshots(sport_key, events, raw_payload_id=raw_payload_id)


def capture_sportsbook_odds_snapshots(
    sport_key: str,
    odds_events: Iterable[Dict[str, Any]],
    raw_payload_id: Optional[str] = None,
) -> int:
    capture = current_capture()
    if capture is None:
        return 0
    return capture.save_sportsbook_odds_snapshots(sport_key, odds_events, raw_payload_id=raw_payload_id)


def capture_event_match_snapshots(sport_key: str, matches: Iterable[Dict[str, Any]]) -> int:
    capture = current_capture()
    if capture is None:
        return 0
    return capture.save_event_match_snapshots(sport_key, matches)


def capture_comparison_snapshots(rows: Iterable[Dict[str, Any]]) -> int:
    capture = current_capture()
    if capture is None:
        return 0
    return capture.save_comparison_snapshots(rows)
