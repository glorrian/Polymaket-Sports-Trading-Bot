"""Environment-driven config for trading engine."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(slots=True)
class TradingConfig:
    trading_mode: str = "paper"
    cycle_interval_seconds: int = 60
    stake_per_trade_usd: float = 25.0
    max_concurrent_positions: int = 5
    max_daily_loss_usd: float = 100.0
    min_liquidity_usd: float = 2000.0
    max_spread: float = 0.03
    min_profit_threshold: float = 0.02
    min_confidence: float = 0.75
    max_signal_age_minutes: int = 20
    cooldown_seconds: int = 300
    fee_bps: float = 30.0
    slippage_bps: float = 10.0
    max_fill_ratio: float = 1.0
    stop_loss_pct: float = 0.12
    take_profit_pct: float = 0.2
    max_holding_minutes: int = 180
    dry_run: bool = False
    refresh_comparison_each_cycle: bool = False
    comparison_data_path: str = "data/arbitrage_comparison.json"
    journal_dir: str = "data/trading"
    enable_live_trading: bool = False
    live_private_key: str = ""
    live_proxy_address: str = ""
    price_feed_source: str = "ws"
    polymarket_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    ws_quote_stale_ms: int = 5000
    ws_warmup_timeout_ms: int = 2000
    paper_execution_use_live_quote: bool = True

    @classmethod
    def from_env(cls) -> "TradingConfig":
        return cls(
            trading_mode=os.getenv("TRADING_MODE", "paper").strip().lower(),
            cycle_interval_seconds=int(os.getenv("TRADING_CYCLE_SECONDS", "60")),
            stake_per_trade_usd=float(os.getenv("TRADING_STAKE_USD", "25")),
            max_concurrent_positions=int(os.getenv("TRADING_MAX_POSITIONS", "5")),
            max_daily_loss_usd=float(os.getenv("TRADING_MAX_DAILY_LOSS_USD", "100")),
            min_liquidity_usd=float(os.getenv("TRADING_MIN_LIQUIDITY_USD", "2000")),
            max_spread=float(os.getenv("TRADING_MAX_SPREAD", "0.03")),
            min_profit_threshold=float(os.getenv("TRADING_MIN_PROFIT", "0.02")),
            min_confidence=float(os.getenv("TRADING_MIN_CONFIDENCE", "0.75")),
            max_signal_age_minutes=int(os.getenv("TRADING_MAX_SIGNAL_AGE_MIN", "20")),
            cooldown_seconds=int(os.getenv("TRADING_COOLDOWN_SECONDS", "300")),
            fee_bps=float(os.getenv("TRADING_FEE_BPS", "30")),
            slippage_bps=float(os.getenv("TRADING_SLIPPAGE_BPS", "10")),
            max_fill_ratio=float(os.getenv("TRADING_MAX_FILL_RATIO", "1.0")),
            stop_loss_pct=float(os.getenv("TRADING_STOP_LOSS_PCT", "0.12")),
            take_profit_pct=float(os.getenv("TRADING_TAKE_PROFIT_PCT", "0.20")),
            max_holding_minutes=int(os.getenv("TRADING_MAX_HOLD_MIN", "180")),
            dry_run=os.getenv("TRADING_DRY_RUN", "false").strip().lower() == "true",
            refresh_comparison_each_cycle=os.getenv("TRADING_REFRESH_COMPARE", "false").strip().lower() == "true",
            comparison_data_path=os.getenv("TRADING_COMPARISON_PATH", "data/arbitrage_comparison.json"),
            journal_dir=os.getenv("TRADING_JOURNAL_DIR", "data/trading"),
            enable_live_trading=os.getenv("ENABLE_LIVE_TRADING", "false").strip().lower() == "true",
            # Backward-compatible aliases:
            # PRIVATE_KEY/PK and POLYMARKET_PROXY_ADDRESS/BROWSER_ADDRESS
            live_private_key=(os.getenv("PRIVATE_KEY") or os.getenv("PK") or "").strip(),
            live_proxy_address=(os.getenv("POLYMARKET_PROXY_ADDRESS") or os.getenv("BROWSER_ADDRESS") or "").strip(),
            price_feed_source=os.getenv("PRICE_FEED_SOURCE", "ws").strip().lower(),
            polymarket_ws_url=os.getenv(
                "POLYMARKET_WS_URL",
                "wss://ws-subscriptions-clob.polymarket.com/ws/market",
            ).strip(),
            ws_quote_stale_ms=int(os.getenv("WS_QUOTE_STALE_MS", "5000")),
            ws_warmup_timeout_ms=int(os.getenv("WS_WARMUP_TIMEOUT_MS", "2000")),
            paper_execution_use_live_quote=os.getenv(
                "PAPER_EXECUTION_USE_LIVE_QUOTE", "true"
            ).strip().lower() == "true",
        )

    def validate(self) -> None:
        if self.trading_mode not in {"paper", "live"}:
            raise ValueError("TRADING_MODE must be one of: paper, live")
        if self.trading_mode == "live" and not self.enable_live_trading:
            raise ValueError("Live mode requires ENABLE_LIVE_TRADING=true")
        if self.trading_mode == "live" and not self.live_private_key:
            raise ValueError(
                "Live mode blocked: PRIVATE_KEY (or PK) is not set. "
                "Set wallet key before enabling live auto-trading."
            )
        if self.trading_mode == "live" and not self.live_proxy_address:
            raise ValueError(
                "Live mode blocked: POLYMARKET_PROXY_ADDRESS (or BROWSER_ADDRESS) is not set. "
                "Set proxy wallet address before enabling live auto-trading."
            )
        if self.stake_per_trade_usd <= 0:
            raise ValueError("TRADING_STAKE_USD must be > 0")
        if self.max_concurrent_positions < 1:
            raise ValueError("TRADING_MAX_POSITIONS must be >= 1")
        if self.min_profit_threshold < 0:
            raise ValueError("TRADING_MIN_PROFIT must be >= 0")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("Fee/slippage bps cannot be negative")
        if self.price_feed_source not in {"ws", "gamma", "disabled"}:
            raise ValueError("PRICE_FEED_SOURCE must be one of: ws, gamma, disabled")
        if self.ws_quote_stale_ms < 1:
            raise ValueError("WS_QUOTE_STALE_MS must be >= 1")
        if self.ws_warmup_timeout_ms < 0:
            raise ValueError("WS_WARMUP_TIMEOUT_MS must be >= 0")
