"""Append-only historical data repository for ingest and backtest datasets."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, Iterator, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from poly_sports.db.models import (
    ComparisonSnapshot,
    DataRun,
    EventMatchSnapshot,
    LivePriceSnapshot,
    PolymarketMarketSnapshot,
    RawPayload,
    SportsbookEventSnapshot,
    SportsbookOddsSnapshot,
    OpportunitySnapshot,
)

SENSITIVE_KEYS = {
    "apikey",
    "api_key",
    "odds_api_key",
    "odds_api_keys",
    "private_key",
    "pk",
    "live_private_key",
    "live_proxy_address",
    "proxy_address",
    "polymarket_proxy_address",
    "browser_address",
}
REDACTED = "[REDACTED]"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:24]}"


def parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def safe_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_json_safe(value: Any) -> Any:
    """Convert common runtime values into JSON-serializable structures."""
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def redact_secrets(value: Any) -> Any:
    """Redact known credential fields without altering ordinary bookmaker keys."""
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            redacted[str(key)] = REDACTED if normalized in SENSITIVE_KEYS else redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def sanitize_json(value: Any) -> Any:
    return redact_secrets(to_json_safe(value))


def canonical_json(value: Any) -> str:
    return json.dumps(sanitize_json(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def payload_size(value: Any) -> int:
    return len(canonical_json(value).encode("utf-8"))


def row_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, list):
            return len(data)
        return 1
    return 0


def parse_json_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _market_token_ids(market: Dict[str, Any]) -> List[Optional[str]]:
    token_ids = parse_json_list(market.get("clobTokenIds"))
    if not token_ids:
        tokens = market.get("tokens") or []
        if isinstance(tokens, list):
            token_ids = [
                token.get("token_id") or token.get("id")
                for token in tokens
                if isinstance(token, dict) and (token.get("token_id") or token.get("id"))
            ]
    return [_string_or_none(token_id) for token_id in token_ids]


def _iter_polymarket_markets(items: Iterable[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    for item in items or []:
        if not isinstance(item, dict):
            continue
        nested_markets = item.get("markets")
        if isinstance(nested_markets, list):
            for market in nested_markets:
                if not isinstance(market, dict):
                    continue
                row = dict(market)
                row.setdefault("event_id", item.get("id"))
                row.setdefault("event_title", item.get("title"))
                row.setdefault("homeTeamName", item.get("homeTeamName"))
                row.setdefault("awayTeamName", item.get("awayTeamName"))
                row.setdefault("startTime", item.get("startTime", item.get("eventDate")))
                row.setdefault("eventDate", item.get("eventDate"))
                row.setdefault("event_liquidity", item.get("liquidity"))
                row.setdefault("event_volume", item.get("volume"))
                yield row
        else:
            yield item


class HistoryRepository:
    """Persist historical ingest data with one commit per logical batch."""

    def __init__(self, session: AsyncSession | Session) -> None:
        self._session = session

    async def start_data_run(
        self,
        run_type: str,
        source: str,
        config: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        started_at: Optional[datetime] = None,
    ) -> str:
        run_id = self._add_data_run(run_type, source, config, run_id, started_at)
        await self._session.commit()
        return run_id

    def start_data_run_sync(
        self,
        run_type: str,
        source: str,
        config: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        started_at: Optional[datetime] = None,
    ) -> str:
        run_id = self._add_data_run(run_type, source, config, run_id, started_at)
        self._session.commit()
        return run_id

    def _add_data_run(
        self,
        run_type: str,
        source: str,
        config: Optional[Dict[str, Any]],
        run_id: Optional[str],
        started_at: Optional[datetime],
    ) -> str:
        run_id = run_id or new_id("run")
        model = DataRun(
            run_id=run_id,
            run_type=run_type,
            source=source,
            status="running",
            started_at=started_at or utc_now(),
            config_json=sanitize_json(config or {}),
            summary_json={},
        )
        self._session.add(model)
        return run_id

    async def finish_data_run(
        self,
        run_id: str,
        status: str = "completed",
        summary: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        finished_at: Optional[datetime] = None,
    ) -> None:
        row = await self._session.get(DataRun, run_id)
        if row is not None:
            self._finish_data_run_model(row, status, summary, error, finished_at)
            await self._session.commit()

    def finish_data_run_sync(
        self,
        run_id: str,
        status: str = "completed",
        summary: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        finished_at: Optional[datetime] = None,
    ) -> None:
        row = self._session.get(DataRun, run_id)
        if row is not None:
            self._finish_data_run_model(row, status, summary, error, finished_at)
            self._session.commit()

    def _finish_data_run_model(
        self,
        row: DataRun,
        status: str,
        summary: Optional[Dict[str, Any]],
        error: Optional[str],
        finished_at: Optional[datetime],
    ) -> None:
        row.status = status
        row.finished_at = finished_at or utc_now()
        row.summary_json = sanitize_json(summary or {})
        row.error = error

    async def save_raw_payload(
        self,
        source: str,
        endpoint: str,
        payload: Any,
        request_params: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        status: str = "ok",
        status_code: Optional[int] = None,
        captured_at: Optional[datetime] = None,
    ) -> str:
        payload_id = self._add_raw_payload(
            source, endpoint, payload, request_params, run_id, status, status_code, captured_at
        )
        await self._session.commit()
        return payload_id

    def save_raw_payload_sync(
        self,
        source: str,
        endpoint: str,
        payload: Any,
        request_params: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        status: str = "ok",
        status_code: Optional[int] = None,
        captured_at: Optional[datetime] = None,
    ) -> str:
        payload_id = self._add_raw_payload(
            source, endpoint, payload, request_params, run_id, status, status_code, captured_at
        )
        self._session.commit()
        return payload_id

    def _add_raw_payload(
        self,
        source: str,
        endpoint: str,
        payload: Any,
        request_params: Optional[Dict[str, Any]],
        run_id: Optional[str],
        status: str,
        status_code: Optional[int],
        captured_at: Optional[datetime],
    ) -> str:
        clean_payload = sanitize_json(payload)
        payload_id = new_id("raw")
        model = RawPayload(
            payload_id=payload_id,
            run_id=run_id,
            source=source,
            endpoint=endpoint,
            request_params_json=sanitize_json(request_params or {}),
            status=status,
            status_code=safe_int(status_code),
            payload_hash=payload_hash(clean_payload),
            payload_size_bytes=payload_size(clean_payload),
            row_count=row_count(clean_payload),
            captured_at=captured_at or utc_now(),
            payload_json=clean_payload,
        )
        self._session.add(model)
        return payload_id

    async def save_polymarket_market_snapshots(
        self,
        markets: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        raw_payload_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_polymarket_market_snapshots(markets, run_id, raw_payload_id, captured_at)
        await self._session.commit()
        return count

    def save_polymarket_market_snapshots_sync(
        self,
        markets: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        raw_payload_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_polymarket_market_snapshots(markets, run_id, raw_payload_id, captured_at)
        self._session.commit()
        return count

    def _add_polymarket_market_snapshots(
        self,
        markets: Iterable[Dict[str, Any]],
        run_id: Optional[str],
        raw_payload_id: Optional[str],
        captured_at: Optional[datetime],
    ) -> int:
        captured_at = captured_at or utc_now()
        count = 0
        for market in _iter_polymarket_markets(markets):
            outcomes = parse_json_list(market.get("market_outcomes", market.get("outcomes")))
            prices = parse_json_list(market.get("market_outcomePrices", market.get("outcomePrices")))
            tokens = _market_token_ids(market)
            row_count_limit = max(len(outcomes), len(prices), len(tokens), 1)
            for idx in range(row_count_limit):
                model = PolymarketMarketSnapshot(
                    snapshot_id=new_id("pm"),
                    run_id=run_id,
                    raw_payload_id=raw_payload_id,
                    event_id=_string_or_none(market.get("event_id")),
                    market_id=_string_or_none(market.get("market_id", market.get("id"))),
                    condition_id=_string_or_none(market.get("conditionId", market.get("condition_id"))),
                    outcome_index=idx if row_count_limit > 1 else None,
                    outcome_name=_string_or_none(outcomes[idx]) if idx < len(outcomes) else None,
                    token_id=tokens[idx] if idx < len(tokens) else None,
                    outcome_price=safe_float(prices[idx]) if idx < len(prices) else None,
                    last_trade_price=safe_float(market.get("lastTradePrice")),
                    best_bid=safe_float(market.get("bestBid")),
                    best_ask=safe_float(market.get("bestAsk")),
                    spread=safe_float(market.get("spread")),
                    liquidity=safe_float(
                        market.get("market_liquidityNum", market.get("liquidityNum", market.get("liquidity")))
                    ),
                    volume=safe_float(market.get("market_volumeNum", market.get("volumeNum", market.get("volume")))),
                    captured_at=captured_at,
                    market_json=sanitize_json(market),
                )
                self._session.add(model)
                count += 1
        return count

    async def save_sportsbook_event_snapshots(
        self,
        sport_key: str,
        events: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        raw_payload_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_sportsbook_event_snapshots(sport_key, events, run_id, raw_payload_id, captured_at)
        await self._session.commit()
        return count

    def save_sportsbook_event_snapshots_sync(
        self,
        sport_key: str,
        events: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        raw_payload_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_sportsbook_event_snapshots(sport_key, events, run_id, raw_payload_id, captured_at)
        self._session.commit()
        return count

    def _add_sportsbook_event_snapshots(
        self,
        sport_key: str,
        events: Iterable[Dict[str, Any]],
        run_id: Optional[str],
        raw_payload_id: Optional[str],
        captured_at: Optional[datetime],
    ) -> int:
        captured_at = captured_at or utc_now()
        count = 0
        for event in events or []:
            if not isinstance(event, dict):
                continue
            model = SportsbookEventSnapshot(
                snapshot_id=new_id("sbe"),
                run_id=run_id,
                raw_payload_id=raw_payload_id,
                odds_event_id=_string_or_none(event.get("id")),
                sport_key=_string_or_none(event.get("sport_key", sport_key)),
                home_team=_string_or_none(event.get("home_team")),
                away_team=_string_or_none(event.get("away_team")),
                commence_time=parse_ts(event.get("commence_time")),
                captured_at=captured_at,
                event_json=sanitize_json(event),
            )
            self._session.add(model)
            count += 1
        return count

    async def save_sportsbook_odds_snapshots(
        self,
        sport_key: str,
        odds_events: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        raw_payload_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_sportsbook_odds_snapshots(sport_key, odds_events, run_id, raw_payload_id, captured_at)
        await self._session.commit()
        return count

    def save_sportsbook_odds_snapshots_sync(
        self,
        sport_key: str,
        odds_events: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        raw_payload_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_sportsbook_odds_snapshots(sport_key, odds_events, run_id, raw_payload_id, captured_at)
        self._session.commit()
        return count

    def _add_sportsbook_odds_snapshots(
        self,
        sport_key: str,
        odds_events: Iterable[Dict[str, Any]],
        run_id: Optional[str],
        raw_payload_id: Optional[str],
        captured_at: Optional[datetime],
    ) -> int:
        captured_at = captured_at or utc_now()
        count = 0
        for event in odds_events or []:
            if not isinstance(event, dict):
                continue
            event_sport = event.get("sport_key", sport_key)
            for bookmaker in event.get("bookmakers", []) or []:
                if not isinstance(bookmaker, dict):
                    continue
                for market in bookmaker.get("markets", []) or []:
                    if not isinstance(market, dict):
                        continue
                    for outcome in market.get("outcomes", []) or []:
                        if not isinstance(outcome, dict):
                            continue
                        model = SportsbookOddsSnapshot(
                            snapshot_id=new_id("sbo"),
                            run_id=run_id,
                            raw_payload_id=raw_payload_id,
                            odds_event_id=_string_or_none(event.get("id")),
                            sport_key=_string_or_none(event_sport),
                            bookmaker_key=_string_or_none(bookmaker.get("key", bookmaker.get("bookmaker_key"))),
                            bookmaker_title=_string_or_none(bookmaker.get("title", bookmaker.get("bookmaker_title"))),
                            market_key=_string_or_none(market.get("key", market.get("market_key"))),
                            outcome_name=_string_or_none(outcome.get("name")),
                            price=safe_float(outcome.get("price")),
                            point=safe_float(outcome.get("point")),
                            captured_at=captured_at,
                            odds_json=sanitize_json(
                                {"event": event, "bookmaker": bookmaker, "market": market, "outcome": outcome}
                            ),
                        )
                        self._session.add(model)
                        count += 1
        return count

    async def save_event_match_snapshots(
        self,
        sport_key: str,
        matches: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_event_match_snapshots(sport_key, matches, run_id, captured_at)
        await self._session.commit()
        return count

    def save_event_match_snapshots_sync(
        self,
        sport_key: str,
        matches: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_event_match_snapshots(sport_key, matches, run_id, captured_at)
        self._session.commit()
        return count

    def _add_event_match_snapshots(
        self,
        sport_key: str,
        matches: Iterable[Dict[str, Any]],
        run_id: Optional[str],
        captured_at: Optional[datetime],
    ) -> int:
        captured_at = captured_at or utc_now()
        count = 0
        for match in matches or []:
            pm_event = match.get("pm_event", {}) if isinstance(match, dict) else {}
            odds_event = match.get("odds_event", {}) if isinstance(match, dict) else {}
            if not isinstance(pm_event, dict) or not isinstance(odds_event, dict):
                continue
            model = EventMatchSnapshot(
                match_id=new_id("match"),
                run_id=run_id,
                pm_event_id=_string_or_none(pm_event.get("event_id", pm_event.get("id"))),
                pm_market_id=_string_or_none(pm_event.get("market_id", pm_event.get("id"))),
                odds_event_id=_string_or_none(odds_event.get("id")),
                sport_key=_string_or_none(odds_event.get("sport_key", sport_key)),
                confidence=float(match.get("confidence", 0.0) or 0.0),
                pm_home_team=_string_or_none(pm_event.get("homeTeamName")),
                pm_away_team=_string_or_none(pm_event.get("awayTeamName")),
                odds_home_team=_string_or_none(odds_event.get("home_team")),
                odds_away_team=_string_or_none(odds_event.get("away_team")),
                matched_at=captured_at,
                match_json=sanitize_json(match),
            )
            self._session.add(model)
            count += 1
        return count

    async def save_comparison_snapshots(
        self,
        comparison_rows: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_comparison_snapshots(comparison_rows, run_id, captured_at)
        await self._session.commit()
        return count

    def save_comparison_snapshots_sync(
        self,
        comparison_rows: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_comparison_snapshots(comparison_rows, run_id, captured_at)
        self._session.commit()
        return count

    def _add_comparison_snapshots(
        self,
        comparison_rows: Iterable[Dict[str, Any]],
        run_id: Optional[str],
        captured_at: Optional[datetime],
    ) -> int:
        captured_at = captured_at or utc_now()
        count = 0
        for row in comparison_rows or []:
            if not isinstance(row, dict):
                continue
            model = ComparisonSnapshot(
                snapshot_id=new_id("cmp"),
                run_id=run_id,
                pm_event_id=_string_or_none(row.get("pm_event_id")),
                pm_market_id=_string_or_none(row.get("pm_market_id")),
                odds_event_id=_string_or_none(row.get("odds_api_event_id")),
                sport_key=_string_or_none(row.get("odds_api_sport_key")),
                match_confidence=safe_float(row.get("match_confidence")),
                sportsbook_count=int(row.get("sportsbook_count", 0) or 0),
                captured_at=captured_at,
                comparison_json=sanitize_json(row),
            )
            self._session.add(model)
            count += 1
        return count

    async def save_opportunity_snapshots(
        self,
        opportunities: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_opportunity_snapshots(opportunities, run_id, captured_at)
        await self._session.commit()
        return count

    def save_opportunity_snapshots_sync(
        self,
        opportunities: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_opportunity_snapshots(opportunities, run_id, captured_at)
        self._session.commit()
        return count

    def _add_opportunity_snapshots(
        self,
        opportunities: Iterable[Dict[str, Any]],
        run_id: Optional[str],
        captured_at: Optional[datetime],
    ) -> int:
        captured_at = captured_at or utc_now()
        count = 0
        for row in opportunities or []:
            if not isinstance(row, dict):
                continue
            matched = row.get("matched_outcomes")
            first_match = matched[0] if isinstance(matched, list) and matched else {}
            model = OpportunitySnapshot(
                opportunity_id=new_id("opp"),
                run_id=run_id,
                signal_id=_string_or_none(row.get("signal_id")),
                pm_event_id=_string_or_none(row.get("pm_event_id")),
                pm_market_id=_string_or_none(row.get("pm_market_id")),
                odds_event_id=_string_or_none(row.get("odds_api_event_id")),
                outcome_name=_string_or_none(first_match.get("pm_outcome") if isinstance(first_match, dict) else None),
                opportunity_type=_string_or_none(row.get("opportunity_type")),
                profit_margin=safe_float(row.get("profit_margin")),
                delta_difference=safe_float(row.get("delta_difference")),
                pm_price=safe_float(first_match.get("pm_price") if isinstance(first_match, dict) else None),
                target_probability=safe_float(
                    first_match.get("sb_implied_prob") if isinstance(first_match, dict) else None
                ),
                liquidity=safe_float(row.get("pm_liquidity", row.get("liquidity"))),
                spread=safe_float(row.get("pm_spread")),
                confidence=safe_float(row.get("match_confidence")),
                created_at=captured_at,
                opportunity_json=sanitize_json(row),
            )
            self._session.add(model)
            count += 1
        return count

    async def save_live_price_snapshots(
        self,
        price_rows: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_live_price_snapshots(price_rows, run_id, captured_at)
        await self._session.commit()
        return count

    def save_live_price_snapshots_sync(
        self,
        price_rows: Iterable[Dict[str, Any]],
        run_id: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> int:
        count = self._add_live_price_snapshots(price_rows, run_id, captured_at)
        self._session.commit()
        return count

    def _add_live_price_snapshots(
        self,
        price_rows: Iterable[Dict[str, Any]],
        run_id: Optional[str],
        captured_at: Optional[datetime],
    ) -> int:
        default_captured_at = captured_at or utc_now()
        count = 0
        for row in price_rows or []:
            if not isinstance(row, dict):
                continue
            row_captured_at = parse_ts(row.get("captured_at")) or default_captured_at
            model = LivePriceSnapshot(
                snapshot_id=new_id("live"),
                run_id=run_id,
                position_id=_string_or_none(row.get("position_id")),
                market_id=_string_or_none(row.get("market_id")),
                event_id=_string_or_none(row.get("event_id")),
                outcome_name=_string_or_none(row.get("outcome_name")),
                token_id=_string_or_none(row.get("token_id")),
                price=safe_float(row.get("price")),
                bid=safe_float(row.get("bid")),
                ask=safe_float(row.get("ask")),
                spread=safe_float(row.get("spread")),
                source=_string_or_none(row.get("source")) or "polymarket_gamma",
                captured_at=row_captured_at,
                payload_json=sanitize_json(row.get("payload", row)),
            )
            self._session.add(model)
            count += 1
        return count

    def iter_comparison_snapshots(
        self,
        start_at: datetime,
        end_at: datetime,
        sport_key: Optional[str] = None,
        market_id: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        stmt = select(ComparisonSnapshot).where(
            ComparisonSnapshot.captured_at >= start_at,
            ComparisonSnapshot.captured_at <= end_at,
        )
        if sport_key:
            stmt = stmt.where(ComparisonSnapshot.sport_key == sport_key)
        if market_id:
            stmt = stmt.where(ComparisonSnapshot.pm_market_id == market_id)
        stmt = stmt.order_by(ComparisonSnapshot.captured_at.asc())
        for row in self._session.execute(stmt).scalars():
            yield {
                "snapshot_id": row.snapshot_id,
                "run_id": row.run_id,
                "captured_at": row.captured_at.isoformat(),
                "pm_event_id": row.pm_event_id,
                "pm_market_id": row.pm_market_id,
                "odds_event_id": row.odds_event_id,
                "sport_key": row.sport_key,
                "match_confidence": row.match_confidence,
                "sportsbook_count": row.sportsbook_count,
                "comparison": row.comparison_json,
            }

    def iter_live_price_snapshots(
        self,
        start_at: datetime,
        end_at: datetime,
        market_id: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        stmt = select(LivePriceSnapshot).where(
            LivePriceSnapshot.captured_at >= start_at,
            LivePriceSnapshot.captured_at <= end_at,
        )
        if market_id:
            stmt = stmt.where(LivePriceSnapshot.market_id == market_id)
        stmt = stmt.order_by(LivePriceSnapshot.captured_at.asc())
        for row in self._session.execute(stmt).scalars():
            yield {
                "snapshot_id": row.snapshot_id,
                "run_id": row.run_id,
                "captured_at": row.captured_at.isoformat(),
                "position_id": row.position_id,
                "market_id": row.market_id,
                "event_id": row.event_id,
                "outcome_name": row.outcome_name,
                "token_id": row.token_id,
                "price": row.price,
                "bid": row.bid,
                "ask": row.ask,
                "spread": row.spread,
                "source": row.source,
                "payload": row.payload_json,
            }
