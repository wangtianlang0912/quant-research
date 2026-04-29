from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.domain.enums import OrderStatus
from src.domain.ids import BrokerOrderId, OrderId


@dataclass(frozen=True)
class Fill:
    order_id: OrderId
    broker_order_id: BrokerOrderId
    symbol: str
    fill_price: Decimal
    fill_quantity: Decimal
    commission: Decimal
    slippage: Decimal
    timestamp: datetime


@dataclass(frozen=True)
class ExecutionReport:
    order_id: OrderId
    broker_order_id: BrokerOrderId
    status: OrderStatus
    message: str
    timestamp: datetime
