"""Trading repository — maps domain dataclasses to SQLAlchemy models."""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from poly_sports.db.models import (
    Fill as FillModel,
    Order as OrderModel,
    Position as PositionModel,
    PositionCheck as PositionCheckModel,
    RiskEvent as RiskEventModel,
    Signal as SignalModel,
)
from poly_sports.trading.models import (
    ExecutionResult,
    OrderIntent,
    Position,
    Signal,
)


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"Cannot parse timestamp: {value!r}")


class TradingRepository:
    """Async repository for all trading entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_signal(self, signal: Signal) -> None:
        """Persist a Signal record (upsert — replaces on conflict)."""
        from sqlalchemy import select
        from poly_sports.db.models import Signal as SignalModel

        result = await self._session.execute(
            select(SignalModel).where(SignalModel.signal_id == signal.signal_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.market_id = signal.market_id
            existing.event_id = signal.event_id
            existing.outcome_name = signal.outcome_name
            existing.side = signal.side
            existing.order_type = signal.order_type
            existing.suggested_price = signal.suggested_price
            existing.target_price = signal.target_price
            existing.confidence = signal.confidence
            existing.expected_profit_pct = signal.expected_profit_pct
            existing.liquidity = signal.liquidity
            existing.spread = signal.spread
            existing.created_at = _parse_ts(signal.created_at)
            existing.metadata_json = signal.metadata
        else:
            model = SignalModel(
                signal_id=signal.signal_id,
                market_id=signal.market_id,
                event_id=signal.event_id,
                outcome_name=signal.outcome_name,
                side=signal.side,
                order_type=signal.order_type,
                suggested_price=signal.suggested_price,
                target_price=signal.target_price,
                confidence=signal.confidence,
                expected_profit_pct=signal.expected_profit_pct,
                liquidity=signal.liquidity,
                spread=signal.spread,
                created_at=_parse_ts(signal.created_at),
                metadata_json=signal.metadata,
            )
            self._session.add(model)
        await self._session.commit()

    async def save_order(self, order: OrderIntent) -> None:
        """Persist an OrderIntent record (upsert on duplicate order_id)."""
        from sqlalchemy import select
        from poly_sports.db.models import Order as OrderModel

        order_id = f"{order.order_type.lower()}-{order.signal_id}"

        result = await self._session.execute(
            select(OrderModel).where(OrderModel.order_id == order_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.signal_id = order.signal_id
            existing.market_id = order.market_id
            existing.event_id = order.event_id
            existing.outcome_name = order.outcome_name
            existing.side = order.side
            existing.order_type = order.order_type
            existing.requested_price = order.requested_price
            existing.requested_size_usd = order.requested_size_usd
            existing.created_at = _parse_ts(order.created_at)
            existing.metadata_json = order.metadata
        else:
            model = OrderModel(
                order_id=order_id,
                signal_id=order.signal_id,
                market_id=order.market_id,
                event_id=order.event_id,
                outcome_name=order.outcome_name,
                side=order.side,
                order_type=order.order_type,
                requested_price=order.requested_price,
                requested_size_usd=order.requested_size_usd,
                created_at=_parse_ts(order.created_at),
                metadata_json=order.metadata,
            )
            self._session.add(model)
        await self._session.commit()

    async def save_fill(self, fill: ExecutionResult) -> None:
        """Persist an ExecutionResult record."""
        model = FillModel(
            fill_id=f"fill-{fill.order_id}",
            order_id=fill.order_id,
            signal_id=fill.signal_id,
            market_id=fill.market_id,
            side=fill.side,
            order_type=fill.order_type,
            filled_size_usd=fill.filled_size_usd,
            fill_price=fill.fill_price,
            fees_usd=fill.fees_usd,
            slippage_bps=fill.slippage_bps,
            timestamp=_parse_ts(fill.timestamp),
            status=fill.status,
            error=fill.error,
            metadata_json=fill.metadata,
        )
        self._session.add(model)
        await self._session.commit()

    async def save_position(self, position: Position) -> None:
        """Persist or update a Position record."""
        existing = await self._session.get(PositionModel, position.position_id)
        if existing:
            existing.status = position.status
            existing.exit_price = position.exit_price
            existing.exit_time = _parse_ts(position.exit_time) if position.exit_time else None
            existing.exit_reason = position.exit_reason
            existing.exit_fees_usd = position.exit_fees_usd
            existing.realized_pnl_usd = position.realized_pnl_usd
            existing.unrealized_pnl_usd = position.unrealized_pnl_usd
        else:
            model = PositionModel(
                position_id=position.position_id,
                signal_id=position.signal_id,
                market_id=position.market_id,
                event_id=position.event_id,
                outcome_name=position.outcome_name,
                side=position.side,
                status=position.status,
                size_usd=position.size_usd,
                entry_price=position.entry_price,
                entry_time=_parse_ts(position.entry_time),
                target_price=position.target_price,
                stop_loss_price=position.stop_loss_price,
                take_profit_price=position.take_profit_price,
                max_holding_minutes=position.max_holding_minutes,
                entry_fees_usd=position.entry_fees_usd,
                exit_price=position.exit_price,
                exit_time=_parse_ts(position.exit_time) if position.exit_time else None,
                exit_reason=position.exit_reason,
                exit_fees_usd=position.exit_fees_usd,
                realized_pnl_usd=position.realized_pnl_usd,
                unrealized_pnl_usd=position.unrealized_pnl_usd,
                metadata_json=position.metadata,
            )
            self._session.add(model)
        await self._session.commit()

    async def save_risk_event(self, event_id: str, signal_id: str, market_id: str, allow: bool,
                               reason_code: str, message: str, details: Dict[str, Any],
                               created_at: str) -> None:
        """Persist a RiskDecision record."""
        model = RiskEventModel(
            event_id=event_id,
            signal_id=signal_id,
            market_id=market_id,
            allow=allow,
            reason_code=reason_code,
            message=message,
            details_json=details,
            created_at=_parse_ts(created_at),
        )
        self._session.add(model)
        await self._session.commit()

    async def save_position_check(self, check_id: str, position_id: str, latest_price: float,
                                  unrealized_pnl_usd: float, should_exit: bool,
                                  exit_reason: Optional[str], checked_at: str) -> None:
        """Persist a PositionCheck record."""
        model = PositionCheckModel(
            check_id=check_id,
            position_id=position_id,
            latest_price=latest_price,
            unrealized_pnl_usd=unrealized_pnl_usd,
            should_exit=should_exit,
            exit_reason=exit_reason,
            checked_at=_parse_ts(checked_at),
        )
        self._session.add(model)
        await self._session.commit()

    async def get_open_positions(self) -> List[Position]:
        """Return all OPEN positions as domain dataclasses."""
        result = await self._session.execute(
            select(PositionModel).where(PositionModel.status == "OPEN")
        )
        return [self._model_to_position(row) for row in result.scalars().all()]

    async def get_position_by_id(self, position_id: str) -> Optional[Position]:
        """Get a single position by ID."""
        row = await self._session.get(PositionModel, position_id)
        if row is None:
            return None
        return self._model_to_position(row)

    async def get_signal_by_id(self, signal_id: str) -> Optional[Signal]:
        """Get a signal by ID or None."""
        row = await self._session.get(SignalModel, signal_id)
        if row is None:
            return None
        return Signal(
            signal_id=row.signal_id,
            market_id=row.market_id,
            event_id=row.event_id,
            outcome_name=row.outcome_name,
            side=row.side,
            order_type=row.order_type,
            suggested_price=row.suggested_price,
            target_price=row.target_price,
            confidence=row.confidence,
            expected_profit_pct=row.expected_profit_pct,
            liquidity=row.liquidity,
            spread=row.spread,
            created_at=row.created_at.isoformat().replace("+00:00", "Z") if row.created_at else "",
            metadata=row.metadata_json or {},
        )

    async def get_seen_signal_ids(self) -> Set[str]:
        """Return set of signal_ids that have an ENTRY order."""
        result = await self._session.execute(
            select(OrderModel.signal_id).where(OrderModel.order_type == "ENTRY")
        )
        return set(result.scalars().all())

    async def get_realized_pnl_today(self) -> float:
        """Sum realized PnL for closed positions with exit_time today (UTC)."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self._session.execute(
            select(func.coalesce(func.sum(PositionModel.realized_pnl_usd), 0.0))
            .where(PositionModel.status == "CLOSED")
            .where(PositionModel.exit_time >= today_start)
        )
        return float(result.scalar() or 0.0)

    async def update_position(self, position: Position) -> None:
        """Update an existing position."""
        await self.save_position(position)

    def _model_to_position(self, row: PositionModel) -> Position:
        return Position(
            position_id=row.position_id,
            signal_id=row.signal_id,
            market_id=row.market_id,
            event_id=row.event_id,
            outcome_name=row.outcome_name,
            side=row.side,
            status=row.status,
            size_usd=row.size_usd,
            entry_price=row.entry_price,
            entry_time=row.entry_time.isoformat().replace("+00:00", "Z") if row.entry_time else "",
            target_price=row.target_price,
            stop_loss_price=row.stop_loss_price,
            take_profit_price=row.take_profit_price,
            max_holding_minutes=row.max_holding_minutes,
            entry_fees_usd=row.entry_fees_usd or 0.0,
            exit_price=row.exit_price,
            exit_time=row.exit_time.isoformat().replace("+00:00", "Z") if row.exit_time else None,
            exit_reason=row.exit_reason,
            exit_fees_usd=row.exit_fees_usd or 0.0,
            realized_pnl_usd=row.realized_pnl_usd or 0.0,
            unrealized_pnl_usd=row.unrealized_pnl_usd or 0.0,
            metadata=row.metadata_json or {},
        )