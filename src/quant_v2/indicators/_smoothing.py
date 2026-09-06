"""指标库内部共享工具 —— 只有跨指标复用的几段纯数学。

★ 单独成文件是为了**避免重复实现**（诊断 #12：v1 有两套扫描器，
因子/指标各写一份，70% 重复，改一个忘另一个）。

这里只放三段真正共用的东西：

1. `prepare_series` —— 预热期（前缀 `None`）的统一处理
2. `wilder_smooth` —— Wilder 平滑（RSI 与 ATR 共用）
3. `ZERO` —— Decimal 零点常量

不放"看起来通用但实际会分化"的东西：两个指标一旦开始各自演化，
共享函数就会变成互相拖累的耦合点。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

__all__ = ["ZERO", "prepare_series", "wilder_smooth"]

ZERO: Decimal = Decimal("0")


def prepare_series(values: Sequence[Decimal | None]) -> tuple[int, tuple[Decimal, ...]]:
    """校验并提取连续有效值段。

    约定：**`None` 只允许出现在序列前缀**（预热期）。
    中间出现空洞说明上游拼接错了，必须报错而不是跳过去 ——
    跳过去会让"缺了 3 天数据"变成一个悄悄偏掉的指标。

    Args:
        values: 可能带前缀 `None` 的数值序列。

    Returns:
        `(首个有效值的下标, 去前缀后的连续值元组)`。
        全为 `None` 时返回 `(len(values), ())`。

    Raises:
        ValueError: 前缀之后仍出现 `None`。
    """
    total = len(values)
    start = 0
    while start < total and values[start] is None:
        start += 1

    dense: list[Decimal] = []
    for index in range(start, total):
        value = values[index]
        if value is None:
            raise ValueError(
                f"values[{index}] 为 None：指标输入只允许**前缀**缺值（预热期），"
                f"第 {start} 项之后不允许再出现空洞"
            )
        dense.append(value)
    return (start, tuple(dense))


def wilder_smooth(values: Sequence[Decimal], n: int) -> list[Decimal | None]:
    """Wilder 平滑（即 Wilder 意义上的"移动平均"）。

    递推式（Wilder 原版，不是简单移动平均）：

        out[n-1] = mean(values[0..n-1])           # 种子：前 n 项的简单均值
        out[i]   = (out[i-1] * (n - 1) + values[i]) / n

    等价于 `EMA(alpha = 1/n)`，但**种子用简单均值** —— 这个差别在
    RSI/ATR 上会被放大，v1 用简单均值代替 Wilder 平滑是其实证缺陷之一。

    Args:
        values: 无 `None` 的数值序列。
        n: 平滑周期。

    Returns:
        与输入等长的列表；前 `n-1` 项为 `None`。
    """
    if n <= 0:
        raise ValueError(f"平滑周期必须为正，收到 {n}")

    out: list[Decimal | None] = [None] * len(values)
    if len(values) < n:
        return out

    seed = sum(values[:n], ZERO) / Decimal(n)
    out[n - 1] = seed

    prev = seed
    decay = Decimal(n - 1)
    divisor = Decimal(n)
    for index in range(n, len(values)):
        prev = (prev * decay + values[index]) / divisor
        out[index] = prev
    return out
