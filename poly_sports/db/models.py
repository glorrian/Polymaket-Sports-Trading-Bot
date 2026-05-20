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