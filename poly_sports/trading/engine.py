"""Auto-trading orchestration loop for paper/live adapters."""

import asyncio
import json
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from poly_sports.data_fetching.fetch_odds_comparison import main as refresh_comparison_pipeline
from poly_sports.db.history_capture import is_data_capture_enabled, maybe_capture_data_run
from poly_sports.db.history_repository import HistoryRepository
from poly_sports.market_data import PolymarketWsPriceFeed, PriceQuote, parse_clob_token_ids
from poly_sports.db.repository import TradingRepository
from poly_sports.processing.arbitrage_calculation import detect_arbitrage_opportunities
from poly_sports.utils.file_utils import load_json
from poly_sports.utils.logger import logger

from .config import TradingConfig
from .decision_engine import (
    build_signals,
    latest_price_map_from_opportunities,
    opportunity_from_dict,
    should_open_signal,
)
from .execution import PaperExecutionAdapter, PolymarketLiveExecutionAdapter
from .models import ExecutionResult, OrderIntent, Position, Signal, utc_now_iso
from .position_manager import PositionManager
from .risk_engine import RiskEngine

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


class AutoTraderEngine:
    """Coordinates data->signal->risk->execute->monitor->journal."""

    def __init__(self, config: TradingConfig, session_factory) -> None:
        self.config = config
        self.config.validate()
        self._session_factory = session_factory
        self.risk = RiskEngine(config)
        self.position_manager = PositionManager(config)
        self.positions: Dict[str, Position] = {}
        self.seen_signal_ids: set[str] = set()
        self.realized_pnl_today = 0.0
        self._cycle_count = 0
        self._comparison_interval = 3
        self._market_slugs: Dict[str, str] = {}
        self._last_live_price_snapshots: List[Dict[str, Any]] = []
        self._last_live_raw_payloads: List[Dict[str, Any]] = []
        self.price_feed: Optional[PolymarketWsPriceFeed] = None
        if config.price_feed_source == "ws":
            self.price_feed = PolymarketWsPriceFeed(
                ws_url=config.polymarket_ws_url,
                quote_stale_ms=config.ws_quote_stale_ms,
            )

        if config.trading_mode == "paper":
            self.execution_adapter = PaperExecutionAdapter(config)
        else:
            from .execution import PolymarketLiveExecutionAdapter
            self.execution_adapter = PolymarketLiveExecutionAdapter()

    async def run_cycle(self) -> Dict[str, int]:
        self._cycle_count += 1
        need_comparison = (self._cycle_count % self._comparison_interval == 1)
        capture_enabled = is_data_capture_enabled(default=True)

        opened = 0
        denied = 0
        skipped_duplicate = 0
        signals_count = 0
        closed = 0
        summary: Dict[str, int] = {}

        async with self._session_factory() as session:
            repo = TradingRepository(session)
            history_repo = HistoryRepository(session)
            run_id: Optional[str] = None
            if capture_enabled:
                run_id = await history_repo.start_data_run(
                    run_type="auto_trader_cycle",
                    source="auto_trader",
                    config={
                        **asdict(self.config),
                        "cycle_count": self._cycle_count,
                        "need_comparison": need_comparison,
                    },
                )

            try:
                if self._cycle_count == 1:
                    self.positions = {p.position_id: p for p in await repo.get_open_positions()}
                    self.seen_signal_ids = await repo.get_seen_signal_ids()
                    self.realized_pnl_today = await repo.get_realized_pnl_today()

                if need_comparison:
                    comparison_data = self._load_comparison_data(run_id=run_id, capture_enabled=capture_enabled)
                    token_lookup = self._build_token_lookup_from_comparison(comparison_data)
                    if capture_enabled and run_id:
                        await history_repo.save_raw_payload(
                            source="file_cache",
                            endpoint=self.config.comparison_data_path,
                            request_params={"kind": "trading_comparison_input"},
                            payload=comparison_data,
                            run_id=run_id,
                        )
                        await history_repo.save_comparison_snapshots(comparison_data, run_id=run_id)

                    raw_opps = detect_arbitrage_opportunities(
                        comparison_data,
                        min_profit_threshold=self.config.min_profit_threshold,
                        min_liquidity=self.config.min_liquidity_usd,
                    )
                    if capture_enabled and run_id:
                        await history_repo.save_opportunity_snapshots(raw_opps, run_id=run_id)

                    opportunities = [opportunity_from_dict(row) for row in raw_opps]
                    cycle_bucket = self._build_cycle_bucket()
                    signals = build_signals(opportunities, cycle_bucket)
                    self._attach_signal_token_ids(signals, token_lookup)
                    await self._subscribe_signal_tokens(signals)
                    signals_count = len(signals)

                    for signal in signals:
                        await repo.save_signal(signal)
                        if not should_open_signal(signal.signal_id, self.seen_signal_ids):
                            skipped_duplicate += 1
                            await repo.save_risk_event(
                                event_id=f"risk-{signal.signal_id}",
                                signal_id=signal.signal_id,
                                market_id=signal.market_id,
                                allow=False,
                                reason_code="duplicate_signal",
                                message="Signal already processed earlier.",
                                details={},
                                created_at=utc_now_iso(),
                            )
                            continue

                        realized_pnl = await repo.get_realized_pnl_today()
                        decision = self.risk.evaluate_entry(
                            signal=signal,
                            open_positions=self.positions.values(),
                            realized_pnl_today_usd=realized_pnl,
                        )
                        await repo.save_risk_event(
                            event_id=f"risk-{signal.signal_id}",
                            signal_id=signal.signal_id,
                            market_id=signal.market_id,
                            allow=decision.allow,
                            reason_code=decision.reason_code,
                            message=decision.message,
                            details=decision.details,
                            created_at=utc_now_iso(),
                        )
                        if not decision.allow:
                            denied += 1
                            continue

                        requested_price, price_metadata = await self._resolve_live_order_price(
                            signal,
                            fallback_price=signal.suggested_price,
                        )

                        intent = OrderIntent(
                            signal_id=signal.signal_id,
                            market_id=signal.market_id,
                            event_id=signal.event_id,
                            outcome_name=signal.outcome_name,
                            side=signal.side,
                            order_type="ENTRY",
                            requested_price=requested_price,
                            requested_size_usd=self.config.stake_per_trade_usd,
                            created_at=utc_now_iso(),
                            metadata={"cycle_bucket": cycle_bucket, **price_metadata},
                        )
                        await repo.save_order(intent)

                        if self.config.dry_run:
                            dry_run_fill = ExecutionResult(
                                ok=True,
                                order_id=f"entry-{signal.signal_id}",
                                signal_id=signal.signal_id,
                                market_id=signal.market_id,
                                side=signal.side,
                                order_type="ENTRY",
                                filled_size_usd=0.0,
                                fill_price=0.0,
                                fees_usd=0.0,
                                slippage_bps=0.0,
                                timestamp=utc_now_iso(),
                                status="dry_run_skipped",
                            )
                            await repo.save_fill(dry_run_fill)
                            continue

                        exec_result = self.execution_adapter.execute(intent)
                        await repo.save_fill(exec_result)
                        if exec_result.ok and exec_result.filled_size_usd > 0:
                            pos = self.position_manager.open_position(signal, exec_result)
                            self.positions[pos.position_id] = pos
                            await repo.save_position(pos)
                            await repo.save_position_check(
                                check_id=f"check-{pos.position_id}-entry",
                                position_id=pos.position_id,
                                latest_price=pos.entry_price,
                                unrealized_pnl_usd=0.0,
                                should_exit=False,
                                exit_reason="entry",
                                checked_at=utc_now_iso(),
                            )
                            opened += 1
                else:
                    logger.info("Skipping Odds API refresh this cycle (monitoring only)")

                closed = await self._monitor_open_positions_async(
                    repo,
                    history_repo=history_repo if capture_enabled else None,
                    run_id=run_id,
                )

                summary = {
                    "signals": signals_count,
                    "opened": opened,
                    "closed": closed,
                    "denied": denied,
                    "duplicates": skipped_duplicate,
                    "open_positions": len([p for p in self.positions.values() if p.is_open()]),
                }
                if capture_enabled and run_id:
                    await history_repo.finish_data_run(run_id, status="completed", summary=summary)
            except Exception as exc:
                if capture_enabled and run_id:
                    await session.rollback()
                    await history_repo.finish_data_run(
                        run_id,
                        status="failed",
                        summary={
                            "signals": signals_count,
                            "opened": opened,
                            "closed": closed,
                            "denied": denied,
                            "duplicates": skipped_duplicate,
                        },
                        error=str(exc),
                    )
                raise

        logger.info(f"Auto-trader cycle summary: {summary}")
        return summary

    async def _monitor_open_positions_async(
        self,
        repo: TradingRepository,
        history_repo: Optional[HistoryRepository] = None,
        run_id: Optional[str] = None,
    ) -> int:
        live_prices = await self._fetch_live_prices_async()
        if history_repo is not None and run_id:
            for raw_payload in self._last_live_raw_payloads:
                await history_repo.save_raw_payload(run_id=run_id, **raw_payload)
            await history_repo.save_live_price_snapshots(
                self._last_live_price_snapshots,
                run_id=run_id,
            )
        closed = 0
        for position in list(self.positions.values()):
            if not position.is_open():
                continue
            latest_price = live_prices.get((position.market_id, position.outcome_name))
            decision = self.position_manager.evaluate_exit(position, latest_price)
            if not decision.should_exit:
                if decision.latest_price is not None:
                    unrealized = position.size_usd * ((decision.latest_price / position.entry_price) - 1)
                    position.unrealized_pnl_usd = round(unrealized, 8)
                await repo.save_position_check(
                    check_id=f"check-{position.position_id}-{self._cycle_count}",
                    position_id=position.position_id,
                    latest_price=decision.latest_price or 0.0,
                    unrealized_pnl_usd=position.unrealized_pnl_usd,
                    should_exit=False,
                    exit_reason=decision.reason,
                    checked_at=utc_now_iso(),
                )
                continue

            intent = OrderIntent(
                signal_id=position.signal_id,
                market_id=position.market_id,
                event_id=position.event_id,
                outcome_name=position.outcome_name,
                side="SELL" if position.side == "BUY" else "BUY",
                order_type="EXIT",
                requested_price=decision.latest_price or position.entry_price,
                requested_size_usd=position.size_usd,
                created_at=utc_now_iso(),
                metadata={
                    "exit_reason": decision.reason,
                    **self._metadata_from_position_quote(position, decision.latest_price),
                },
            )

            if self.config.dry_run:
                continue

            exec_result = self.execution_adapter.execute(intent)
            await repo.save_fill(exec_result)
            if exec_result.ok:
                closed_position = self.position_manager.close_position(
                    position, exec_result, exit_reason=decision.reason,
                )
                self.positions[closed_position.position_id] = closed_position
                self.realized_pnl_today += closed_position.realized_pnl_usd
                await repo.update_position(closed_position)
                await repo.save_position_check(
                    check_id=f"check-{closed_position.position_id}-{self._cycle_count}",
                    position_id=closed_position.position_id,
                    latest_price=decision.latest_price or 0.0,
                    unrealized_pnl_usd=0.0,
                    should_exit=True,
                    exit_reason=decision.reason,
                    checked_at=utc_now_iso(),
                )
                self.risk.mark_market_cooldown(position.market_id)
                closed += 1
        return closed

    def _build_token_lookup_from_comparison(self, comparison_data: List[dict]) -> Dict[Tuple[str, str], str]:
        lookup: Dict[Tuple[str, str], str] = {}
        for row in comparison_data:
            market_id = str(row.get("pm_market_id", "") or "")
            outcomes_raw = row.get("pm_market_outcomes", [])
            try:
                outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else list(outcomes_raw or [])
            except (json.JSONDecodeError, TypeError):
                outcomes = []
            token_ids = parse_clob_token_ids(row.get("pm_clobTokenIds") or row.get("pm_clob_token_ids"))
            for idx, outcome_name in enumerate(outcomes):
                if market_id and idx < len(token_ids):
                    lookup[(market_id, str(outcome_name))] = token_ids[idx]
        return lookup

    def _attach_signal_token_ids(self, signals: List[Signal], token_lookup: Dict[Tuple[str, str], str]) -> None:
        for signal in signals:
            token_id = token_lookup.get((signal.market_id, signal.outcome_name))
            if token_id:
                signal.metadata["token_id"] = token_id

    async def _subscribe_signal_tokens(self, signals: List[Signal]) -> None:
        if not self.price_feed or not self.config.paper_execution_use_live_quote:
            return
        asset_metadata: Dict[str, Dict[str, Any]] = {}
        for signal in signals:
            token_id = signal.metadata.get("token_id")
            if not token_id:
                continue
            asset_metadata[str(token_id)] = {
                "market_id": signal.market_id,
                "event_id": signal.event_id,
                "outcome_name": signal.outcome_name,
            }
        if not asset_metadata:
            return
        await self.price_feed.subscribe_assets(asset_metadata)
        await self.price_feed.wait_for_assets(asset_metadata.keys(), self.config.ws_warmup_timeout_ms)

    async def _resolve_live_order_price(self, signal: Signal, fallback_price: float) -> Tuple[float, Dict[str, Any]]:
        token_id = signal.metadata.get("token_id")
        if not self.config.paper_execution_use_live_quote or not token_id:
            return fallback_price, {}

        quote = self.price_feed.get_quote_by_asset(str(token_id)) if self.price_feed else None
        price, metadata = self._price_from_quote(quote, signal.side)
        if price is not None:
            metadata["token_id"] = str(token_id)
            return price, metadata

        clob_price = await asyncio.to_thread(self._fetch_clob_rest_price, str(token_id), signal.side)
        if clob_price is not None:
            return clob_price, {"token_id": str(token_id), "quote_source": "clob_rest"}

        return fallback_price, {"token_id": str(token_id), "quote_source": "strategy_fallback"}

    def _price_from_quote(self, quote: Optional[PriceQuote], side: str) -> Tuple[Optional[float], Dict[str, Any]]:
        if quote is None or quote.is_stale(self.config.ws_quote_stale_ms):
            return None, {}
        price = quote.executable_price(side)
        if price is None or price <= 0:
            return None, {}
        return price, {
            "quote_source": "polymarket_ws_market",
            "best_bid": quote.best_bid,
            "best_ask": quote.best_ask,
            "midpoint": quote.midpoint,
            "last_trade_price": quote.last_trade_price,
            "quote_age_ms": round(quote.age_ms(), 2),
        }

    def _metadata_from_position_quote(self, position: Position, latest_price: Optional[float]) -> Dict[str, Any]:
        token_id = position.metadata.get("token_id")
        metadata: Dict[str, Any] = {}
        if token_id:
            metadata["token_id"] = token_id
        quote = self.price_feed.get_quote_by_asset(str(token_id)) if self.price_feed and token_id else None
        if quote and not quote.is_stale(self.config.ws_quote_stale_ms):
            metadata.update(
                {
                    "quote_source": "polymarket_ws_market",
                    "best_bid": quote.best_bid,
                    "best_ask": quote.best_ask,
                    "midpoint": quote.midpoint,
                    "quote_age_ms": round(quote.age_ms(), 2),
                }
            )
        elif latest_price:
            metadata["quote_source"] = "price_monitor"
        return metadata

    def _load_comparison_data(
        self,
        run_id: Optional[str] = None,
        capture_enabled: bool = True,
    ) -> List[dict]:
        if self.config.refresh_comparison_each_cycle:
            logger.info("Refreshing comparison data pipeline...")
            with maybe_capture_data_run(
                "odds_comparison_pipeline",
                "auto_trader",
                config=asdict(self.config),
                run_id=run_id,
                start_run=False,
                enabled=capture_enabled,
            ):
                refresh_comparison_pipeline()
        data = load_json(self.config.comparison_data_path)
        if not isinstance(data, list):
            raise ValueError("Comparison data must be a list")
        return data

    def _build_cycle_bucket(self) -> str:
        now = datetime.now(timezone.utc)
        minute_bucket = (now.minute // max(1, self.config.cycle_interval_seconds // 60)) * max(
            1, self.config.cycle_interval_seconds // 60
        )
        return now.replace(minute=minute_bucket, second=0, microsecond=0).isoformat()

    def _fetch_clob_rest_price(self, token_id: str, side: str) -> Optional[float]:
        try:
            query = urllib.parse.urlencode({"token_id": token_id, "side": side.upper()})
            url = f"{CLOB_API}/price?{query}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode())
            return float(payload["price"]) if payload.get("price") is not None else None
        except Exception:
            return None

    async def _fetch_live_prices_async(self) -> Dict[Tuple[str, str], float]:
        self._last_live_price_snapshots = []
        self._last_live_raw_payloads = []
        result: Dict[Tuple[str, str], float] = {}

        if self.price_feed:
            asset_metadata: Dict[str, Dict[str, Any]] = {}
            for position in self.positions.values():
                if not position.is_open():
                    continue
                token_id = position.metadata.get("token_id")
                if not token_id:
                    continue
                asset_metadata[str(token_id)] = {
                    "market_id": position.market_id,
                    "event_id": position.event_id,
                    "outcome_name": position.outcome_name,
                }
            if asset_metadata:
                await self.price_feed.subscribe_assets(asset_metadata)
                await self.price_feed.wait_for_assets(asset_metadata.keys(), self.config.ws_warmup_timeout_ms)
                for position in self.positions.values():
                    if not position.is_open():
                        continue
                    token_id = position.metadata.get("token_id")
                    quote = self.price_feed.get_quote_by_asset(str(token_id)) if token_id else None
                    exit_side = "SELL" if position.side == "BUY" else "BUY"
                    price, _ = self._price_from_quote(quote, exit_side)
                    if price is not None:
                        result[(position.market_id, position.outcome_name)] = price

                for raw_event in self.price_feed.drain_raw_events():
                    self._last_live_raw_payloads.append(raw_event)
                self._last_live_price_snapshots.extend(self.price_feed.quote_snapshots())

        if self.config.price_feed_source != "disabled":
            gamma_prices = await asyncio.to_thread(self._fetch_gamma_live_prices)
            for key, value in gamma_prices.items():
                result.setdefault(key, value)
        return result

    def _fetch_gamma_live_prices(self) -> Dict[Tuple[str, str], float]:
        open_list = [p for p in self.positions.values() if p.is_open()]
        if not open_list:
            return {}
        result: Dict[Tuple[str, str], float] = {}
        market_ids = list({p.market_id for p in open_list})
        for mid in market_ids:
            try:
                url = f"{GAMMA_API}/markets/{mid}"
                req = urllib.request.Request(url, headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                })
                with urllib.request.urlopen(req, timeout=5) as resp:
                    market = json.loads(resp.read().decode())
                self._last_live_raw_payloads.append(
                    {
                        "source": "polymarket_gamma",
                        "endpoint": url,
                        "request_params": {"market_id": mid, "kind": "live_market"},
                        "payload": market,
                        "status_code": getattr(resp, "status", None),
                    }
                )
                slug = market.get("slug")
                if slug:
                    self._market_slugs[mid] = slug
                prices_raw = market.get("outcomePrices", "[]")
                outcome_prices = json.loads(prices_raw) if isinstance(prices_raw, str) else list(prices_raw or [])
                try:
                    token_ids_raw = market.get("clobTokenIds", "[]")
                    token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else list(token_ids_raw or [])
                except (json.JSONDecodeError, TypeError):
                    token_ids = []
                outcomes_raw = market.get("outcomes", "[]")
                try:
                    outcomes = json.loads(outcomes_raw)
                except (json.JSONDecodeError, TypeError):
                    outcomes = [s.strip() for s in str(outcomes_raw).split(",")]
                for i, name in enumerate(outcomes):
                    if i < len(outcome_prices):
                        price = float(outcome_prices[i])
                        self._last_live_price_snapshots.append(
                            {
                                "market_id": mid,
                                "event_id": market.get("event_id") or market.get("eventId"),
                                "outcome_name": name,
                                "token_id": token_ids[i] if i < len(token_ids) else None,
                                "price": price,
                                "bid": market.get("bestBid"),
                                "ask": market.get("bestAsk"),
                                "spread": market.get("spread"),
                                "source": "polymarket_gamma",
                                "payload": {
                                    "market_id": mid,
                                    "slug": slug,
                                    "outcome_index": i,
                                    "outcome_name": name,
                                    "outcome_price": price,
                                },
                            }
                        )
                        if price > 0:
                            result[(mid, name)] = price
            except Exception:
                pass
        logger.info(f"Live prices fetched for {len(result)} outcomes from Gamma API")
        return result
