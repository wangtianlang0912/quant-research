from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import uuid

from src.domain.enums import SignalDirection
from src.domain.ids import SignalId, StrategyId
from src.domain.models.signal import Signal
from src.domain.models.strategy import StrategyContext, StrategyMetadata
from src.strategies.base import BaseStrategy


@dataclass
class TrendFollowingStrategy(BaseStrategy):
    short_window: int = 5
    long_window: int = 20

    def __init__(
        self,
        strategy_id: str = "trend_following",
        name: str = "Trend Following",
        version: str = "0.1.0",
        short_window: int = 5,
        long_window: int = 20,
    ) -> None:
        super().__init__(
            _metadata=StrategyMetadata(
                strategy_id=StrategyId(strategy_id),
                name=name,
                version=version,
                author="copilot",
            )
        )
        self.short_window = short_window
        self.long_window = long_window

    def on_bar(self, context: StrategyContext) -> list[Signal]:
        bars = context.bars
        if len(bars) < self.long_window:
            return []

        closes = [bar.close for bar in bars]
        short_ma = sum(closes[-self.short_window:]) / Decimal(str(self.short_window))
        long_ma = sum(closes[-self.long_window:]) / Decimal(str(self.long_window))
        latest = bars[-1]

        if short_ma > long_ma:
            direction = SignalDirection.LONG
            reason = f"short_ma({short_ma}) > long_ma({long_ma})"
        elif short_ma < long_ma:
            direction = SignalDirection.SHORT
            reason = f"short_ma({short_ma}) < long_ma({long_ma})"
        else:
            direction = SignalDirection.FLAT
            reason = f"short_ma({short_ma}) == long_ma({long_ma})"

        return [
            Signal(
                signal_id=SignalId(str(uuid.uuid4())),
                strategy_id=context.metadata.strategy_id,
                symbol=latest.symbol,
                timestamp=latest.timestamp,
                direction=direction,
                strength=Decimal("1.0"),
                reason=reason,
                metadata={
                    "short_window": str(self.short_window),
                    "long_window": str(self.long_window),
                },
            )
        ]
