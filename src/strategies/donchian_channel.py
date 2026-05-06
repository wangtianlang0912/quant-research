"""
唐奇安通道策略 (Donchian Channel)
价格突破 N 日最高价 → 做多；跌破 M 日最低价 → 平仓。
"""
from __future__ import annotations
from decimal import Decimal
import uuid

from src.domain.enums import SignalDirection
from src.domain.ids import SignalId, StrategyId
from src.domain.models.signal import Signal
from src.domain.models.strategy import StrategyMetadata, StrategyContext
from src.strategies.base import BaseStrategy


class DonchianChannelStrategy(BaseStrategy):
    def __init__(
        self,
        strategy_id: str = "donchian_channel",
        name: str = "Donchian Channel",
        version: str = "0.1.0",
        channel_period: int = 20,
        exit_period: int = 10,
    ) -> None:
        super().__init__(
            _metadata=StrategyMetadata(
                strategy_id=StrategyId(strategy_id), name=name, version=version, author="copilot",
            )
        )
        self.channel_period = channel_period
        self.exit_period = exit_period
        self._current_direction: SignalDirection | None = None

    def on_bar(self, context: StrategyContext) -> list[Signal]:
        bars = context.bars
        if len(bars) < self.channel_period:
            return []

        latest = bars[-1]
        price = float(latest.close)

        channel_bars = bars[-self.channel_period:]
        exit_bars = bars[-self.exit_period:]

        channel_high = max(float(b.high) for b in channel_bars)
        channel_low = min(float(b.low) for b in channel_bars)
        exit_low = min(float(b.low) for b in exit_bars)

        if price > channel_high and self._current_direction != SignalDirection.LONG:
            self._current_direction = SignalDirection.LONG
            reason = f"突破上轨 {price:.2f} > {channel_high:.2f}"
            return [Signal(
                signal_id=SignalId(str(uuid.uuid4())),
                strategy_id=context.metadata.strategy_id,
                symbol=latest.symbol,
                timestamp=latest.timestamp,
                direction=SignalDirection.LONG,
                strength=Decimal("1.0"),
                reason=reason,
                metadata={"channel_high": f"{channel_high:.4f}", "channel_low": f"{channel_low:.4f}"},
            )]
        elif price < exit_low and self._current_direction == SignalDirection.LONG:
            self._current_direction = SignalDirection.FLAT
            reason = f"跌破退出下轨 {price:.2f} < {exit_low:.2f}"
            return [Signal(
                signal_id=SignalId(str(uuid.uuid4())),
                strategy_id=context.metadata.strategy_id,
                symbol=latest.symbol,
                timestamp=latest.timestamp,
                direction=SignalDirection.FLAT,
                strength=Decimal("1.0"),
                reason=reason,
                metadata={"exit_low": f"{exit_low:.4f}"},
            )]

        return []
