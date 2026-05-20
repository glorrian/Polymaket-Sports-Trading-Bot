"""Auto-trading orchestration loop for paper/live adapters."""

import asyncio
import json
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from poly_sports.data_fetching.fetch_odds_comparison import main as refresh_comparison_pipeline
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

        if config.trading_mode == "paper":
            self.execution_adapter = PaperExecutionAdapter(config)
        else:
            from .execution import PolymarketLiveExecutionAdapter
            self.execution_adapter = PolymarketLiveExecutionAdapter()

    async def _init_from_db(self) -> None:
        """Load open positions and seen signals from database."""
        async with self._session_factory() as session:
            repo = TradingRepository(session)
            self.positions = {p.position_id: p for p in await repo.get_open_positions()}
            self.seen_signal_ids = await repo.get_seen_signal_ids()
            self.realized_pnl_today = await repo.get_realized_pnl_today()

    async def run_cycle(self) -> Dict[str, int]:
        self._cycle_count += 1
        need_comparison = (self._cycle_count % self._comparison_interval == 1)

        opened = 0
        denied = 0
        skipped_duplicate = 0
        signals_count = 0

        async with self._session_factory() as session:
            repo = TradingRepository(session)

            if self._cycle_count == 1:
                self.positions = {p.position_id: p for p in await repo.get_open_positions()}
                self.seen_signal_ids = await repo.get_seen_signal_ids()
                self.realized_pnl_today = await repo.get_realized_pnl_today()

            if need_comparison:
                comparison_data = self._load_comparison_data()
                raw_opps = detect_arbitrage_opportunities(
                    comparison_data,
                    min_profit_threshold=self.config.min_profit_threshold,
                    min_liquidity=self.config.min_liquidity_usd,
                )
                opportunities = [opportunity_from_dict(row) for row in raw_opps]
                cycle_bucket = self._build_cycle_bucket()
                signals = build_signals(opportunities, cycle_bucket)
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

                    intent = OrderIntent(
                        signal_id=signal.signal_id,
                        market_id=signal.market_id,
                        event_id=signal.event_id,
                        outcome_name=signal.outcome_name,
                        side=signal.side,
                        order_type="ENTRY",
                        requested_price=signal.suggested_price,
                        requested_size_usd=self.config.stake_per_trade_usd,
                        created_at=utc_now_iso(),
                        metadata={"cycle_bucket": cycle_bucket},
                    )
                    await repo.save_order(intent)

                    if self.config.dry_run:
                        dry_run_fill = ExecutionResult(
                            ok=True,
                            order_id=intent.signal_id.replace("sig", "ord"),
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

            closed = await self._monitor_open_positions_async(repo)

        summary = {
            "signals": signals_count,
            "opened": opened,
            "closed": closed,
            "denied": denied,
            "duplicates": skipped_duplicate,
            "open_positions": len([p for p in self.positions.values() if p.is_open()]),
        }
        logger.info(f"Auto-trader cycle summary: {summary}")
        return summary

    async def _monitor_open_positions_async(self, repo: TradingRepository) -> int:
        live_prices = self._fetch_live_prices()
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
                metadata={"exit_reason": decision.reason},
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

    def _load_comparison_data(self) -> List[dict]:
        if self.config.refresh_comparison_each_cycle:
            logger.info("Refreshing comparison data pipeline...")
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

    def _fetch_live_prices(self) -> Dict[Tuple[str, str], float]:
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
                slug = market.get("slug")
                if slug:
                    self._market_slugs[mid] = slug
                outcome_prices = json.loads(market.get("outcomePrices", "[]"))
                outcomes_raw = market.get("outcomes", "[]")
                try:
                    outcomes = json.loads(outcomes_raw)
                except (json.JSONDecodeError, TypeError):
                    outcomes = [s.strip() for s in str(outcomes_raw).split(",")]
                for i, name in enumerate(outcomes):
                    if i < len(outcome_prices):
                        price = float(outcome_prices[i])
                        if price > 0:
                            result[(mid, name)] = price
            except Exception:
                pass
        logger.info(f"Live prices fetched for {len(result)} outcomes from Gamma API")
        return result