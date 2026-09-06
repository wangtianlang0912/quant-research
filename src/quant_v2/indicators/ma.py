"""简单移动平均（SMA）。

首个有效值出现在下标 `n - 1`（需要 n 个样本才有第一个均值）。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from quant_v2.indicators._smoothing import ZERO, prepare_series

__all__ = ["sma"]


def sma(values: Sequence[Decimal | None], n: int) -> list[Decimal | None]:
    """简单移动平均。

    实现为**单次遍历的滑动和**（O(n)），不是对每个位置重算（O(n²)）。
    v1 的 `calc_macd` 就是因为在循环里每次从头重算 EMA 才变成 O(n²)。

    Args:
        values: 数值序列；允许前缀 `None`（预热期）。
        n: 窗口长度。

    Returns:
        与输入等长的列表；前 `n-1` 项为 `None`（相对**首个有效值**的位置）。

    Raises:
        ValueError: `n` 非正，或预热期之后出现空洞。
    """
    if n <= 0:
        raise ValueError(f"窗口长度必须为正，收到 {n}")

    start, dense = prepare_series(values)
    out: list[Decimal | None] = [None] * len(values)
    if len(dense) < n:
        return out

    window = sum(dense[:n], ZERO)
    divisor = Decimal(n)
    out[start + n - 1] = window / divisor

    for offset in range(n, len(dense)):
        window += dense[offset] - dense[offset - n]
        out[start + offset] = window / divisor
    return out
