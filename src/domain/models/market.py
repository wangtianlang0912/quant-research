from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.domain.enums import AdjustType, Frequency


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    amount: Decimal | None = None
    frequency: Frequency = Frequency.DAY_1
    adjust_type: AdjustType = AdjustType.NONE
    source: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Quote:
    symbol: str
    timestamp: datetime
    bid: Decimal | None
    ask: Decimal | None
    last: Decimal | None
    volume: Decimal | None = None
    source: str = ""


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    timestamp: datetime
    latest_bar: Bar | None = None
    latest_quote: Quote | None = None
