"""Polymarket CLOB WebSocket market data feed."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import aiohttp

from poly_sports.utils.logger import logger

POLYMARKET_MARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_clob_token_ids(value: Any) -> List[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None and str(item)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item is not None and str(item)]
    return []


def _best_bid(levels: Iterable[Dict[str, Any]]) -> Optional[float]:
    prices = [price for price in (parse_float(level.get("price")) for level in levels or []) if price is not None]
    return max(prices) if prices else None


def _best_ask(levels: Iterable[Dict[str, Any]]) -> Optional[float]:
    prices = [price for price in (parse_float(level.get("price")) for level in levels or []) if price is not None]
    return min(prices) if prices else None


@dataclass(slots=True)
class PriceQuote:
    asset_id: str
    market_id: Optional[str] = None
    event_id: Optional[str] = None
    outcome_name: Optional[str] = None
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    last_trade_price: Optional[float] = None
    last_trade_side: Optional[str] = None
    spread: Optional[float] = None
    tick_size: Optional[float] = None
    ws_timestamp: Optional[str] = None
    received_at: datetime = field(default_factory=utc_now)
    source: str = "polymarket_ws_market"
    raw_event_type: Optional[str] = None

    @property
    def midpoint(self) -> Optional[float]:
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2
        return self.last_trade_price

    def executable_price(self, side: str) -> Optional[float]:
        if side.upper() == "BUY":
            return self.best_ask if self.best_ask is not None else self.midpoint
        if side.upper() == "SELL":
            return self.best_bid if self.best_bid is not None else self.midpoint
        return self.midpoint

    def age_ms(self, now: Optional[datetime] = None) -> float:
        now = now or utc_now()
        return max(0.0, (now - self.received_at).total_seconds() * 1000)

    def is_stale(self, stale_ms: int, now: Optional[datetime] = None) -> bool:
        return self.age_ms(now=now) > stale_ms

    def snapshot(self) -> Dict[str, Any]:
        data = asdict(self)
        data["midpoint"] = self.midpoint
        data["price"] = self.midpoint
        data["bid"] = self.best_bid
        data["ask"] = self.best_ask
        data["token_id"] = self.asset_id
        data["received_at"] = self.received_at.isoformat()
        data["captured_at"] = self.received_at.isoformat()
        return data


class PolymarketWsPriceFeed:
    """Maintains latest top-of-book quotes from the public Polymarket market WS."""

    def __init__(
        self,
        ws_url: str = POLYMARKET_MARKET_WS_URL,
        quote_stale_ms: int = 5000,
        heartbeat_seconds: float = 10.0,
        reconnect_seconds: float = 2.0,
    ) -> None:
        self.ws_url = ws_url
        self.quote_stale_ms = quote_stale_ms
        self.heartbeat_seconds = heartbeat_seconds
        self.reconnect_seconds = reconnect_seconds
        self.quotes: Dict[str, PriceQuote] = {}
        self.asset_metadata: Dict[str, Dict[str, Any]] = {}
        self._raw_events: List[Dict[str, Any]] = []
        self._running = False
        self._ready = asyncio.Event()
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="polymarket-ws-price-feed")

    async def stop(self) -> None:
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def subscribe_assets(self, asset_metadata: Dict[str, Dict[str, Any]]) -> None:
        clean_metadata = {str(asset_id): dict(meta or {}) for asset_id, meta in asset_metadata.items() if asset_id}
        if not clean_metadata:
            return
        async with self._lock:
            new_asset_ids = [asset_id for asset_id in clean_metadata if asset_id not in self.asset_metadata]
            self.asset_metadata.update(clean_metadata)
            for asset_id, metadata in clean_metadata.items():
                if asset_id in self.quotes:
                    self._apply_metadata(self.quotes[asset_id], metadata)
        await self.start()
        if self._ws and not self._ws.closed and new_asset_ids:
            await self._send_subscription(new_asset_ids, operation="subscribe")

    async def wait_for_assets(self, asset_ids: Iterable[str], timeout_ms: int) -> bool:
        asset_list = [str(asset_id) for asset_id in asset_ids if asset_id]
        if not asset_list:
            return False
        deadline = asyncio.get_running_loop().time() + max(0, timeout_ms) / 1000
        while True:
            if any(asset_id in self.quotes for asset_id in asset_list):
                return True
            if timeout_ms <= 0 or asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.05)

    def get_quote_by_asset(self, asset_id: str) -> Optional[PriceQuote]:
        return self.quotes.get(str(asset_id))

    def get_quote_for_outcome(self, market_id: str, outcome_name: str) -> Optional[PriceQuote]:
        market_key = str(market_id)
        outcome_key = str(outcome_name).lower()
        for quote in self.quotes.values():
            if quote.market_id == market_key and (quote.outcome_name or "").lower() == outcome_key:
                return quote
        return None

    def get_execution_price(self, market_id: str, outcome_name: str, side: str) -> Optional[float]:
        quote = self.get_quote_for_outcome(market_id, outcome_name)
        if not quote or quote.is_stale(self.quote_stale_ms):
            return None
        return quote.executable_price(side)

    def drain_raw_events(self) -> List[Dict[str, Any]]:
        events = self._raw_events
        self._raw_events = []
        return events

    def quote_snapshots(self) -> List[Dict[str, Any]]:
        return [quote.snapshot() for quote in self.quotes.values()]

    async def _run(self) -> None:
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.ws_url, heartbeat=None) as ws:
                        self._ws = ws
                        self._ready.set()
                        if self.asset_metadata:
                            await self._send_subscription(list(self.asset_metadata.keys()))
                        self._heartbeat_task = asyncio.create_task(self._heartbeat())
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                if msg.data == "PONG":
                                    continue
                                if msg.data.lower() == "ping":
                                    await ws.send_str("PONG")
                                    continue
                                await self._handle_text(msg.data)
                            elif msg.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.info(f"Polymarket WS price feed disconnected: {exc}")
            finally:
                self._ready.clear()
                self._ws = None
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                    self._heartbeat_task = None
            if self._running:
                await asyncio.sleep(self.reconnect_seconds)

    async def _heartbeat(self) -> None:
        while self._running and self._ws and not self._ws.closed:
            await asyncio.sleep(self.heartbeat_seconds)
            if self._ws and not self._ws.closed:
                await self._ws.send_str("PING")

    async def _send_subscription(self, asset_ids: List[str], operation: Optional[str] = None) -> None:
        if not self._ws or self._ws.closed or not asset_ids:
            return
        payload: Dict[str, Any] = {
            "assets_ids": asset_ids,
            "custom_feature_enabled": True,
        }
        if operation:
            payload["operation"] = operation
        else:
            payload["type"] = "market"
        await self._ws.send_str(json.dumps(payload))

    async def _handle_text(self, text: str) -> None:
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            return
        if isinstance(message, list):
            for item in message:
                if isinstance(item, dict):
                    self.apply_message(item)
            return
        if isinstance(message, dict):
            self.apply_message(message)

    def apply_message(self, message: Dict[str, Any]) -> Optional[PriceQuote]:
        event_type = message.get("event_type")
        if not event_type:
            return None
        self._raw_events.append(
            {
                "source": "polymarket_ws_market",
                "endpoint": self.ws_url,
                "request_params": {"event_type": event_type},
                "payload": message,
            }
        )
        if event_type == "book":
            return self._apply_book(message)
        if event_type == "price_change":
            self._apply_price_change(message)
            return None
        if event_type == "best_bid_ask":
            return self._apply_best_bid_ask(message)
        if event_type == "last_trade_price":
            return self._apply_last_trade_price(message)
        if event_type == "tick_size_change":
            return self._apply_tick_size_change(message)
        return None

    def _quote(self, asset_id: str, event_type: str, ws_timestamp: Any = None) -> PriceQuote:
        quote = self.quotes.get(asset_id)
        if quote is None:
            metadata = self.asset_metadata.get(asset_id, {})
            quote = PriceQuote(
                asset_id=asset_id,
                market_id=metadata.get("market_id"),
                event_id=metadata.get("event_id"),
                outcome_name=metadata.get("outcome_name"),
            )
            self.quotes[asset_id] = quote
        self._apply_metadata(quote, self.asset_metadata.get(asset_id, {}))
        quote.received_at = utc_now()
        quote.ws_timestamp = str(ws_timestamp) if ws_timestamp is not None else quote.ws_timestamp
        quote.raw_event_type = event_type
        return quote

    def _apply_metadata(self, quote: PriceQuote, metadata: Dict[str, Any]) -> None:
        quote.market_id = str(metadata.get("market_id")) if metadata.get("market_id") is not None else quote.market_id
        quote.event_id = str(metadata.get("event_id")) if metadata.get("event_id") is not None else quote.event_id
        outcome = metadata.get("outcome_name")
        quote.outcome_name = str(outcome) if outcome is not None else quote.outcome_name

    def _apply_book(self, message: Dict[str, Any]) -> Optional[PriceQuote]:
        asset_id = str(message.get("asset_id") or "")
        if not asset_id:
            return None
        quote = self._quote(asset_id, "book", message.get("timestamp"))
        quote.best_bid = _best_bid(message.get("bids", []))
        quote.best_ask = _best_ask(message.get("asks", []))
        quote.spread = self._spread(quote)
        return quote

    def _apply_price_change(self, message: Dict[str, Any]) -> None:
        for change in message.get("price_changes", []) or []:
            if not isinstance(change, dict):
                continue
            asset_id = str(change.get("asset_id") or "")
            if not asset_id:
                continue
            quote = self._quote(asset_id, "price_change", change.get("timestamp", message.get("timestamp")))
            best_bid = parse_float(change.get("best_bid"))
            best_ask = parse_float(change.get("best_ask"))
            if best_bid is not None:
                quote.best_bid = best_bid
            if best_ask is not None:
                quote.best_ask = best_ask
            quote.spread = self._spread(quote)

    def _apply_best_bid_ask(self, message: Dict[str, Any]) -> Optional[PriceQuote]:
        asset_id = str(message.get("asset_id") or "")
        if not asset_id:
            return None
        quote = self._quote(asset_id, "best_bid_ask", message.get("timestamp"))
        quote.best_bid = parse_float(message.get("best_bid"))
        quote.best_ask = parse_float(message.get("best_ask"))
        quote.spread = parse_float(message.get("spread")) or self._spread(quote)
        return quote

    def _apply_last_trade_price(self, message: Dict[str, Any]) -> Optional[PriceQuote]:
        asset_id = str(message.get("asset_id") or "")
        if not asset_id:
            return None
        quote = self._quote(asset_id, "last_trade_price", message.get("timestamp"))
        quote.last_trade_price = parse_float(message.get("price"))
        quote.last_trade_side = str(message.get("side") or "") or None
        return quote

    def _apply_tick_size_change(self, message: Dict[str, Any]) -> Optional[PriceQuote]:
        asset_id = str(message.get("asset_id") or "")
        if not asset_id:
            return None
        quote = self._quote(asset_id, "tick_size_change", message.get("timestamp"))
        quote.tick_size = parse_float(message.get("new_tick_size"))
        return quote

    def _spread(self, quote: PriceQuote) -> Optional[float]:
        if quote.best_bid is None or quote.best_ask is None:
            return quote.spread
        return max(0.0, quote.best_ask - quote.best_bid)
