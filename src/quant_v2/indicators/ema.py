"""指数移动平均（EMA）。

首个有效值出现在下标 `n - 1`（相对首个有效输入）。
**种子用前 n 项的简单均值** —— 这是标准口径，也是 MACD 能与通用行情软件对齐的前提。

★ v1 的 `calc_macd` 缺陷（诊断 #12）：`dea` 以 `difs[0]` 作种子，
预热严重不足，导致开头的几十个值与标准口径差得很远，
而金叉死叉恰恰最容易出现在开头。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from quant_v2.indicators._smoothing import ZERO, prepare_series

__all__ = ["ema"]


def ema(values: Sequence[Decimal | None], n: int) -> list[Decimal | None]:
    """指数移动平均，`alpha = 2 / (n + 1)`。

    递推式：

        out[n-1] = mean(values[0..n-1])                 # 种子：SMA
        out[i]   = values[i] * alpha + out[i-1] * (1 - alpha)

    Args:
        values: 数值序列；允许前缀 `None`（预热期）。
            ★ 这个设计让 MACD 可以直接把 `dif`（带前缀 None）喂进来算 `dea`。
        n: 周期。

    Returns:
        与输入等长的列表；前 `n-1` 项为 `None`（相对首个有效值）。

    Raises:
        ValueError: `n` 非正，或预热期之后出现空洞。
    """
    if n <= 0:
        raise ValueError(f"周期必须为正，收到 {n}")

    start, dense = prepare_series(values)
    out: list[Decimal | None] = [None] * len(values)
    if len(dense) < n:
        return out

    alpha = Decimal(2) / Decimal(n + 1)
    one_minus_alpha = Decimal(1) - alpha

    prev = sum(dense[:n], ZERO) / Decimal(n)
    out[start + n - 1] = prev

    for offset in range(n, len(dense)):
        prev = dense[offset] * alpha + prev * one_minus_alpha
        out[start + offset] = prev
    return out
