"""唐奇安通道（Donchian Channel）—— 突破策略的通道基准。

提供两个变体，因为**用错变体是突破策略最常见的未来函数之一**：

- `donchian()`：含当前 bar 的 n 日通道。用于**判断当前是否处于通道突破状态**。
- `donchian_prior()`：不含当前 bar 的 n 日通道。用于**生成入场信号** ——
  如果用它自己的当前 bar 计算上轨，那么"收盘价 > 上轨"永远成立（或永远不成立），
  信号就废了。

★ 这条区分写进函数名的原因：v1 的 `breakout_scorer.py` 里四道互相矛盾的
最小长度门槛，本质上就是没把"判定用的窗口"和"信号用的窗口"分开。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from quant_v2.indicators._smoothing import prepare_series

__all__ = ["DonchianResult", "donchian", "donchian_prior"]


@dataclass(frozen=True)
class DonchianResult:
    """唐奇安通道。三条等长、按下标对齐；预热期为 `None`。"""

    upper: tuple[Decimal | None, ...]  # 上轨（区间最高）
    lower: tuple[Decimal | None, ...]  # 下轨（区间最低）
    middle: tuple[Decimal | None, ...]  # 中轨（上下轨中点）

    def __len__(self) -> int:
        """序列长度。"""
        return len(self.upper)


def donchian(
    highs: Sequence[Decimal | None],
    lows: Sequence[Decimal | None],
    n: int = 20,
) -> DonchianResult:
    """含当前 bar 的 n 日唐奇安通道。

    首个有效值出现在下标 `n - 1`（相对首个有效输入）。

    Args:
        highs: 最高价序列（允许前缀 `None`）。
        lows: 最低价序列。
        n: 通道周期，默认 20。

    Returns:
        `DonchianResult(upper, lower, middle)`。

    Raises:
        ValueError: `n` 非正、长度不一致，或预热期之后出现空洞。
    """
    if n <= 0:
        raise ValueError(f"通道周期必须为正，收到 {n}")
    if len(highs) != len(lows):
        raise ValueError(f"highs/lows 长度必须一致：{len(highs)} vs {len(lows)}")

    high_start, dense_highs = prepare_series(highs)
    _, dense_lows = prepare_series(lows)

    upper: list[Decimal | None] = [None] * len(highs)
    lower: list[Decimal | None] = [None] * len(highs)
    middle: list[Decimal | None] = [None] * len(highs)

    if len(dense_highs) < n:
        return DonchianResult(upper=tuple(upper), lower=tuple(lower), middle=tuple(middle))

    for offset in range(n - 1, len(dense_highs)):
        window_highs = dense_highs[offset - n + 1 : offset + 1]
        window_lows = dense_lows[offset - n + 1 : offset + 1]
        high_value = max(window_highs)
        low_value = min(window_lows)
        index = high_start + offset
        upper[index] = high_value
        lower[index] = low_value
        middle[index] = (high_value + low_value) / Decimal(2)

    return DonchianResult(upper=tuple(upper), lower=tuple(lower), middle=tuple(middle))


def donchian_prior(
    highs: Sequence[Decimal | None],
    lows: Sequence[Decimal | None],
    n: int = 20,
) -> DonchianResult:
    """**不含**当前 bar 的 n 日唐奇安通道 —— 生成突破入场信号用这个。

    含义：`upper[i] = max(high[i-n .. i-1])`，即用 i 之前的 n 根 bar 定上轨，
    再拿第 i 根 bar 的价格去比。首个有效值出现在下标 `n`。

    Args:
        highs: 最高价序列（允许前缀 `None`）。
        lows: 最低价序列。
        n: 通道周期，默认 20。

    Returns:
        `DonchianResult(upper, lower, middle)`；下标 `0..n-1` 为 `None`。
    """
    if n <= 0:
        raise ValueError(f"通道周期必须为正，收到 {n}")
    if len(highs) != len(lows):
        raise ValueError(f"highs/lows 长度必须一致：{len(highs)} vs {len(lows)}")

    high_start, dense_highs = prepare_series(highs)
    _, dense_lows = prepare_series(lows)

    upper: list[Decimal | None] = [None] * len(highs)
    lower: list[Decimal | None] = [None] * len(highs)
    middle: list[Decimal | None] = [None] * len(highs)

    if len(dense_highs) <= n:
        return DonchianResult(upper=tuple(upper), lower=tuple(lower), middle=tuple(middle))

    for offset in range(n, len(dense_highs)):
        window_highs = dense_highs[offset - n : offset]
        window_lows = dense_lows[offset - n : offset]
        high_value = max(window_highs)
        low_value = min(window_lows)
        index = high_start + offset
        upper[index] = high_value
        lower[index] = low_value
        middle[index] = (high_value + low_value) / Decimal(2)

    return DonchianResult(upper=tuple(upper), lower=tuple(lower), middle=tuple(middle))
