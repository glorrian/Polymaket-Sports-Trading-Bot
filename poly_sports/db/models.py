"""SQLAlchemy 2.0 Declarative models for trading bot."""

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    type_annotation_map = {
        dict: JSON,
    }


class Signal(Base):
    """Generated trading signals from arbitrage detection."""

    __tablename__ = "signals"

    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    market_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    outcome_name: Mapped[str] = mapped_column(String(256))
    side: Mapped[str] = mapped_column(String(4))  # BUY or SELL
    order_type: Mapped[str] = mapped_column(String(8))  # ENTRY or EXIT
    suggested_price: Mapped[float] = mapped_column(Float)
    target_price: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    expected_profit_pct: Mapped[float] = mapped_column(Float)
    liquidity: Mapped[float] = mapped_column(Float)
    spread: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    orders: Mapped[list["Order"]] = relationship(back_populates="signal")
    risk_events: Mapped[list["RiskEvent"]] = relationship(back_populates="signal")
    positions: Mapped[list["Position"]] = relationship(back_populates="signal")

    __table_args__ = (Index("ix_signals_market_event", "market_id", "event_id"),)


class Order(Base):
    """Order intent after risk engine approval."""

    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), ForeignKey("signals.signal_id"), index=True)
    market_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(64))
    outcome_name: Mapped[str] = mapped_column(String(256))
    side: Mapped[str] = mapped_column(String(4))
    order_type: Mapped[str] = mapped_column(String(8))
    requested_price: Mapped[float] = mapped_column(Float)
    requested_size_usd: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    signal: Mapped["Signal"] = relationship(back_populates="orders")
    fills: Mapped[list["Fill"]] = relationship(back_populates="order")


class Fill(Base):
    """Execution result from order adapter."""

    __tablename__ = "fills"

    fill_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), ForeignKey("orders.order_id"), index=True)
    signal_id: Mapped[str] = mapped_column(String(64), index=True)
    market_id: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(4))
    order_type: Mapped[str] = mapped_column(String(8))
    filled_size_usd: Mapped[float] = mapped_column(Float)
    fill_price: Mapped[float] = mapped_column(Float)
    fees_usd: Mapped[float] = mapped_column(Float)
    slippage_bps: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(32), default="filled")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    order: Mapped["Order"] = relationship(back_populates="fills")


class Position(Base):
    """Open or closed trading positions."""

    __tablename__ = "positions"

    position_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), ForeignKey("signals.signal_id"), index=True)
    market_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    outcome_name: Mapped[str] = mapped_column(String(256))
    side: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(8), default="OPEN", index=True)  # OPEN or CLOSED
    size_usd: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    target_price: Mapped[float] = mapped_column(Float)
    stop_loss_price: Mapped[float] = mapped_column(Float)
    take_profit_price: Mapped[float] = mapped_column(Float)
    max_holding_minutes: Mapped[int] = mapped_column(Integer)
    entry_fees_usd: Mapped[float] = mapped_column(Float, default=0.0)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    exit_fees_usd: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    signal: Mapped["Signal"] = relationship(back_populates="positions")
    position_checks: Mapped[list["PositionCheck"]] = relationship(back_populates="position")

    __table_args__ = (
        Index("ix_positions_market_status", "market_id", "status"),
    )


class RiskEvent(Base):
    """Risk engine decision log."""

    __tablename__ = "risk_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), ForeignKey("signals.signal_id"), index=True)
    market_id: Mapped[str] = mapped_column(String(64), index=True)
    allow: Mapped[bool] = mapped_column(Boolean)
    reason_code: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    details_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    signal: Mapped["Signal"] = relationship(back_populates="risk_events")


class PositionCheck(Base):
    """Hourly position monitoring log."""

    __tablename__ = "position_checks"

    check_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position_id: Mapped[str] = mapped_column(String(64), ForeignKey("positions.position_id"), index=True)
    latest_price: Mapped[float] = mapped_column(Float)
    unrealized_pnl_usd: Mapped[float] = mapped_column(Float)
    should_exit: Mapped[bool] = mapped_column(Boolean)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    position: Mapped["Position"] = relationship(back_populates="position_checks")


class DataRun(Base):
    """One ingest, comparison, or trading cycle run."""

    __tablename__ = "data_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    config_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    summary_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    raw_payloads: Mapped[list["RawPayload"]] = relationship(back_populates="run")


class RawPayload(Base):
    """Full captured raw payload from an API response, cache read, or strategy input."""

    __tablename__ = "raw_payloads"

    payload_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("data_runs.run_id"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(64), index=True)
    endpoint: Mapped[str] = mapped_column(Text)
    request_params_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="ok", index=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    payload_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    payload_json: Mapped[Any] = mapped_column(JSON)

    run: Mapped[Optional["DataRun"]] = relationship(back_populates="raw_payloads")

    __table_args__ = (
        Index("ix_raw_payloads_source_captured", "source", "captured_at"),
    )


class PolymarketMarketSnapshot(Base):
    """Normalized Polymarket Gamma market/outcome/price snapshot."""

    __tablename__ = "polymarket_market_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("data_runs.run_id"), nullable=True, index=True)
    raw_payload_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("raw_payloads.payload_id"), nullable=True, index=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    market_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    condition_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    outcome_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    outcome_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    token_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    outcome_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_trade_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    best_bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    best_ask: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spread: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    liquidity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    market_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_pm_market_snapshots_market_time", "market_id", "captured_at"),
        Index("ix_pm_market_snapshots_event_time", "event_id", "captured_at"),
    )


class SportsbookEventSnapshot(Base):
    """Normalized The Odds API event metadata snapshot."""

    __tablename__ = "sportsbook_event_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("data_runs.run_id"), nullable=True, index=True)
    raw_payload_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("raw_payloads.payload_id"), nullable=True, index=True)
    odds_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    sport_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    home_team: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    away_team: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    commence_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_sb_event_snapshots_event_time", "odds_event_id", "captured_at"),
    )


class SportsbookOddsSnapshot(Base):
    """Normalized bookmaker/market/outcome odds snapshot from The Odds API."""

    __tablename__ = "sportsbook_odds_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("data_runs.run_id"), nullable=True, index=True)
    raw_payload_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("raw_payloads.payload_id"), nullable=True, index=True)
    odds_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    sport_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    bookmaker_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    bookmaker_title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    market_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    outcome_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    point: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    odds_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_sb_odds_snapshots_event_time", "odds_event_id", "captured_at"),
        Index("ix_sb_odds_snapshots_outcome_time", "outcome_name", "captured_at"),
    )


class EventMatchSnapshot(Base):
    """Event matching decision between Polymarket and The Odds API."""

    __tablename__ = "event_match_snapshots"

    match_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("data_runs.run_id"), nullable=True, index=True)
    pm_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    pm_market_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    odds_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    sport_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    pm_home_team: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    pm_away_team: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    odds_home_team: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    odds_away_team: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    matched_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    match_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_event_match_snapshots_pm_odds", "pm_event_id", "odds_event_id"),
    )


class ComparisonSnapshot(Base):
    """Merged strategy input row from Polymarket and sportsbook data."""

    __tablename__ = "comparison_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("data_runs.run_id"), nullable=True, index=True)
    pm_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    pm_market_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    odds_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    sport_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    match_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sportsbook_count: Mapped[int] = mapped_column(Integer, default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    comparison_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_comparison_snapshots_market_time", "pm_market_id", "captured_at"),
        Index("ix_comparison_snapshots_sport_time", "sport_key", "captured_at"),
    )


class OpportunitySnapshot(Base):
    """Strategy opportunity row generated from comparison data."""

    __tablename__ = "opportunity_snapshots"

    opportunity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("data_runs.run_id"), nullable=True, index=True)
    signal_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    pm_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    pm_market_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    odds_event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    outcome_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    opportunity_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    profit_margin: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta_difference: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pm_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    liquidity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spread: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    opportunity_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_opportunity_snapshots_market_time", "pm_market_id", "created_at"),
    )


class LivePriceSnapshot(Base):
    """Live price snapshot fetched while monitoring positions."""

    __tablename__ = "live_price_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("data_runs.run_id"), nullable=True, index=True)
    position_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    market_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    outcome_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    token_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ask: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    spread: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="polymarket_gamma", index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_live_price_snapshots_market_time", "market_id", "captured_at"),
        Index("ix_live_price_snapshots_outcome_time", "outcome_name", "captured_at"),
    )
