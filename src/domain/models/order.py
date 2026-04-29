from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.domain.enums import OrderSide, OrderStatus, OrderType
from src.domain.ids import BrokerOrderId, OrderId, SignalId, StrategyId


@dataclass(frozen=True)
class OrderIntent:
    order_id: OrderId
    strategy_id: StrategyId
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    timestamp: datetime
    limit_price: Decimal | None = None
    source_signal_id: SignalId | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Order:
    order_id: OrderId
    broker_order_id: BrokerOrderId
    strategy_id: StrategyId
    symbol: str
    side: OrderSide
    quantity: Decimal
    filled_quantity: Decimal
    order_type: OrderType
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    limit_price: Decimal | None = None
    average_fill_price: Decimal | None = None
