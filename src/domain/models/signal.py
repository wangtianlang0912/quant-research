from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.domain.enums import SignalDirection
from src.domain.ids import SignalId, StrategyId


@dataclass(frozen=True)
class Signal:
    signal_id: SignalId
    strategy_id: StrategyId
    symbol: str
    timestamp: datetime
    direction: SignalDirection
    strength: Decimal
    reason: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TargetPosition:
    strategy_id: StrategyId
    symbol: str
    timestamp: datetime
    target_weight: Decimal | None = None
    target_quantity: Decimal | None = None
    reason: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
