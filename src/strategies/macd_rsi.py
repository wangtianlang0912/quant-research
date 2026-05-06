"""
MACD + RSI 组合策略
MACD 金叉 + RSI < 超买 → 买入；MACD 死叉 + RSI > 超卖 → 卖出。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
import uuid

from src.domain.enums import SignalDirection
from src.domain.ids import SignalId, StrategyId
from src.domain.models.signal import Signal
from src.domain.models.strategy import StrategyMetadata, StrategyContext
from src.strategies.base import BaseStrategy


class MacdRsiStrategy(BaseStrategy):
    def __init__(
        self,
        strategy_id: str = "macd_rsi",
        name: str = "MACD+RSI",
        version: str = "0.1.0",
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
    ) -> None:
        super().__init__(
            _metadata=StrategyMetadata(
                strategy_id=StrategyId(strategy_id), name=name, version=version, author="copilot",
            )
        )
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self._current_direction: SignalDirection | None = None
        self._prev_macd = None
        self._prev_sig = None
        self._ema_fast = None
        self._ema_slow = None

    def _update_ema(self, price: float):
        k_f = 2.0 / (self.macd_fast + 1)
        k_s = 2.0 / (self.macd_slow + 1)
        if self._ema_fast is None:
            self._ema_fast = price
            self._ema_slow = price
        else:
            self._ema_fast = price * k_f + self._ema_fast * (1 - k_f)
            self._ema_slow = price * k_s + self._ema_slow * (1 - k_s)

    def on_bar(self, context: StrategyContext) -> list[Signal]:
        bars = context.bars
        if len(bars) < self.macd_slow:
            return []

        latest = bars[-1]
        price = float(latest.close)

        # 累积更新 EMA（只处理最后一根，前面用初始值）
        # 为确保 EMA 收敛，用前 macd_slow 根数据初始化
        if self._ema_fast is None:
            for b in bars[-self.macd_slow:]:
                self._update_ema(float(b.close))
        else:
            self._update_ema(price)

        macd_val = self._ema_fast - self._ema_slow

        # Signal line EMA
        k = 2.0 / (self.macd_signal + 1)
        if not hasattr(self, '_sig_ema') or self._sig_ema is None:
            self._sig_ema = macd_val
        else:
            self._sig_ema = macd_val * k + self._sig_ema * (1 - k)

        # RSI
        rsi_closes = [float(b.close) for b in bars[-self.rsi_period:]]
        gains = losses = 0.0
        for i in range(1, len(rsi_closes)):
            d = rsi_closes[i] - rsi_closes[i - 1]
            if d > 0: gains += d
            else: losses -= d
        ag = gains / self.rsi_period
        al = losses / self.rsi_period
        rsi = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

        if self._prev_macd is not None and self._prev_sig is not None:
            golden = self._prev_macd <= self._prev_sig and macd_val > self._sig_ema
            dead = self._prev_macd >= self._prev_sig and macd_val < self._sig_ema

            if golden and rsi < self.rsi_overbought:
                new_dir = SignalDirection.LONG
                reason = f"MACD金叉 RSI={rsi:.1f}"
            elif dead and rsi > self.rsi_oversold:
                new_dir = SignalDirection.SHORT
                reason = f"MACD死叉 RSI={rsi:.1f}"
            else:
                self._prev_macd = macd_val
                self._prev_sig = self._sig_ema
                return []

            if new_dir != self._current_direction:
                self._current_direction = new_dir
                self._prev_macd = macd_val
                self._prev_sig = self._sig_ema
                return [Signal(
                    signal_id=SignalId(str(uuid.uuid4())),
                    strategy_id=context.metadata.strategy_id,
                    symbol=latest.symbol,
                    timestamp=latest.timestamp,
                    direction=new_dir,
                    strength=Decimal("1.0"),
                    reason=reason,
                    metadata={"macd": f"{macd_val:.4f}", "signal": f"{self._sig_ema:.4f}",
                              "rsi": f"{rsi:.2f}"},
                )]

        self._prev_macd = macd_val
        self._prev_sig = self._sig_ema
        return []
