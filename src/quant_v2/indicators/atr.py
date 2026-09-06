"""真实波幅（TR）与平均真实波幅（ATR）—— Wilder 口径。

ATR 是仓位计算（波动率目标 / 风险平价）与止损设置的输入，
因此它的口径必须与 `SizingRequest.atr` 的消费者一致。

## 口径

    TR[0] = high[0] - low[0]                       # 首根 bar 没有前收盘
    TR[i] = max(high[i] - low[i],
                |high[i] - close[i-1]|,
                |low[i]  - close[i-1]|)            # i >= 1
    ATR   = wilder_smooth(TR, n)

首个有效值出现在下标 `n - 1`（因为 TR 从下标 0 就有值）。

⚠ 有些实现让 TR 从下标 1 开始（首日无 TR），那样 ATR 的首个有效值在下标 `n`。
本库采用"首日用 high-low"的做法：**多给一个样本，且首日的 high-low 本来就是
当天真实波幅的合理下界**。差异只影响最开头的 n 个值，不影响稳态。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from quant_v2.indicators._smoothing import ZERO, prepare_series, wilder_smooth

__all__ = ["atr", "true_range"]


def true_range(
    highs: Sequence[Decimal | None],
    lows: Sequence[Decimal | None],
    closes: Sequence[Decimal | None],
) -> list[Decimal | None]:
    """真实波幅序列。

    Args:
        highs: 最高价序列（允许前缀 `None`，三条序列前缀长度需一致）。
        lows: 最低价序列。
        closes: 收盘价序列。

    Returns:
        与输入等长的 TR 列表；首根 bar 用 `high - low`。

    Raises:
        ValueError: 三条序列长度不一致，或预热期之后出现空洞。
    """
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError(
            f"highs/lows/closes 长度必须一致：{len(highs)} / {len(lows)} / {len(closes)}"
        )

    high_start, dense_highs = prepare_series(highs)
    low_start, dense_lows = prepare_series(lows)
    close_start, dense_closes = prepare_series(closes)
    if not (high_start == low_start == close_start):
        raise ValueError(
            f"highs/lows/closes 的预热期长度必须一致：{high_start} / {low_start} / {close_start}"
        )

    out: list[Decimal | None] = [None] * len(highs)
    if not dense_highs:
        return out

    out[high_start] = dense_highs[0] - dense_lows[0]
    for offset in range(1, len(dense_highs)):
        high = dense_highs[offset]
        low = dense_lows[offset]
        prev_close = dense_closes[offset - 1]
        candidate = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        out[high_start + offset] = candidate if candidate > ZERO else ZERO
    return out


def atr(
    highs: Sequence[Decimal | None],
    lows: Sequence[Decimal | None],
    closes: Sequence[Decimal | None],
    n: int = 14,
) -> list[Decimal | None]:
    """平均真实波幅（Wilder 平滑）。

    Args:
        highs: 最高价序列。
        lows: 最低价序列。
        closes: 收盘价序列。
        n: 平滑周期，默认 14。

    Returns:
        与输入等长的 ATR 列表；前 `n-1` 项为 `None`。
    """
    if n <= 0:
        raise ValueError(f"周期必须为正，收到 {n}")
    tr = true_range(highs, lows, closes)
    _, dense_tr = prepare_series(tr)
    smoothed = wilder_smooth(dense_tr, n)

    out: list[Decimal | None] = [None] * len(highs)
    start = 0
    while start < len(tr) and tr[start] is None:
        start += 1
    for offset, value in enumerate(smoothed):
        if value is not None:
            out[start + offset] = value
    return out
