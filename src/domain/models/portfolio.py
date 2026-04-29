from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    market_value: Decimal
    updated_at: datetime


@dataclass(frozen=True)
class Portfolio:
    cash: Decimal
    total_value: Decimal
    positions: dict[str, Position] = field(default_factory=dict)
    updated_at: datetime | None = None


@dataclass(frozen=True)
class AccountState:
    account_id: str
    cash_available: Decimal
    equity: Decimal
    positions: dict[str, Position] = field(default_factory=dict)
    updated_at: datetime | None = None
