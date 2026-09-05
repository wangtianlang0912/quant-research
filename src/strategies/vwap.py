"""
VWAP 策略 (成交量加权平均价)
价格低于 VWAP 一定百分比时买入，高于时卖出。
"""
from __future__ import annotations
from decimal import Decimal
import uuid

from src.domain.enums import SignalDirection
from src.domain.ids import SignalId, StrategyId
from src.domain.models.signal import Signal
from src.domain.models.strategy import StrategyMetadata, StrategyContext
from src.strategies.base import BaseStrategy


class VwapStrategy(BaseStrategy):
    """VWAP 策略 — 滚动窗口版本

    使用最近 N 根 K 线（默认10日）的量价加权均价作为基准，
    避免多日累积 VWAP 在趋势行情中产生极端偏离值。

    参数:
        deviation_pct: 偏离阈值(%)，价格偏离 VWAP 超过此值触发信号
        window: 滚动计算 VWAP 的 K 线数量（默认 10）
        max_dev: 极端偏离上限(%)，偏离超过此值视为异常跳过（默认 15%）
    """
    def __init__(
        self,
        strategy_id: str = "vwap",
        name: str = "VWAP",
        version: str = "0.2.0",
        deviation_pct: float = 1.0,
        window: int = 10,
        max_dev: float = 15.0,
    ) -> None:
        super().__init__(
            _metadata=StrategyMetadata(
                strategy_id=StrategyId(strategy_id), name=name, version=version, author="copilot",
            )
        )
        self.deviation_pct = deviation_pct / 100.0
        self.window = window
        self.max_dev = max_dev / 100.0
        self._current_direction: SignalDirection | None = None

    def on_bar(self, context: StrategyContext) -> list[Signal]:
        bars = context.bars
        if len(bars) < self.window:
            return []

        # 只取窗口内的 bars 做滚动 VWAP
        recent = bars[-self.window:]

        cum_pv = Decimal("0")
        cum_vol = Decimal("0")
        for b in recent:
            cum_pv += b.close * b.volume
            cum_vol += b.volume

        vwap = float(cum_pv / cum_vol) if cum_vol > 0 else float(recent[-1].close)
        latest = recent[-1]
        price = float(latest.close)
        dev = (price - vwap) / vwap

        # 极端偏离跳过：视为数据异常或噪音（如当日跳空、派息除权等）
        if abs(dev) > self.max_dev:
            return []

        if dev < -self.deviation_pct:
            new_dir = SignalDirection.LONG
            reason = f"close({price:.2f}) < VWAP({vwap:.2f}) 偏离{dev:.2%}"
        elif dev > self.deviation_pct:
            new_dir = SignalDirection.SHORT
            reason = f"close({price:.2f}) > VWAP({vwap:.2f}) 偏离{dev:.2%}"
        elif abs(dev) < self.deviation_pct * 0.3 and self._current_direction is not None:
            new_dir = SignalDirection.FLAT
            reason = f"close回归VWAP 偏离{dev:.2%}"
        else:
            return []

        if new_dir == self._current_direction:
            return []
        self._current_direction = new_dir

        return [Signal(
            signal_id=SignalId(str(uuid.uuid4())),
            strategy_id=context.metadata.strategy_id,
            symbol=latest.symbol,
            timestamp=latest.timestamp,
            direction=new_dir,
            strength=Decimal("1.0"),
            reason=reason,
            metadata={"vwap": f"{vwap:.4f}", "deviation": f"{dev:.4f}", "window": str(self.window)},
        )]
