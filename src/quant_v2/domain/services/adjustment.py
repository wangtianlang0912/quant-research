"""复权三视图换算（D-03）—— 核心算法，有 golden 测试。

**为什么这个模块存在**：v1 的复权是"零处理"。

- `local_csv_adapter.py:56` 只是把调用方传入的 `adjust_type` **当标签贴到 Bar 上**，
  数据原样返回 —— 你请求 QFQ，它返回未复权数据并告诉你"这是 QFQ"。
- 更糟的是 `backtest_runner.py:203` 调用 `get_bars` 时压根不传 `adjust_type`，
  默认 `AdjustType.NONE` —— **全项目 QFQ/HFQ 从未被请求过一次**。

v2 的解法分两层：

1. **类型层**：`BarRequest.adjust` 无默认值，不显式声明口径就构造不出请求。
2. **算法层**：本模块提供唯一一份换算公式，`BarPanel.to_view()` 只能调它。

## 换算定义

记 `f_i` 为第 i 根 bar 的**累积后复权因子**（`Bar.adj_factor`），
`f_last` 为序列最后一个因子，则价格缩放系数 `k_i` 为：

| 口径 | `k_i` | 不变的那一天 |
| --- | --- | --- |
| `RAW` | `1` | — |
| `BACKWARD`（后复权） | `f_i` | 上市首日价格 = 真实历史价 |
| `FORWARD`（前复权） | `f_i / f_last` | **最新一日价格 = 真实最新价** |

★ 10 送 10 除权案例（close 20 → 10，adj_factor 1 → 2）：

    RAW      = [20, 10]     ← 有 -50% 的假跳空
    BACKWARD = [20, 20]     ← 连续
    FORWARD  = [10, 10]     ← 连续

三条可验证不变量（见 `tests/regression/test_adjustment_golden.py`）：

1. `FORWARD[-1] == RAW[-1]`（前复权以末日为基准）
2. `BACKWARD[i] / FORWARD[i]` 恒定 == `f_last`（三视图可互算）
3. `BACKWARD[i] / RAW[i] == f_i`

> **与设计文档 §4.1 的一处口径差异**：设计稿写
> "BACKWARD / FORWARD = adj_factor / adj_factor_last 恒定"。
> 按上式实际计算得到的是 `BACKWARD[i]/FORWARD[i] == f_last`（常量），
> 而 `f_i / f_last` 是随 i 变化的量，两者不可能同时成立。
> 这里采用标准口径（前复权末日锚定真实价），并以"三视图可互算"
> （`convert_view` 往返误差 < 1e-6）作为验收判据 —— 它比那句公式更本质。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from quant_v2.domain.errors import AdjustmentError
from quant_v2.domain.models.bar import AdjustType

__all__ = [
    "ONE",
    "adjust_series",
    "convert_view",
    "price_scale_factors",
    "validate_adj_factors",
]

ONE: Decimal = Decimal("1")


def validate_adj_factors(adj_factors: Sequence[Decimal]) -> None:
    """校验复权因子序列。

    Args:
        adj_factors: 累积后复权因子序列。

    Raises:
        AdjustmentError: 序列为空、含 ≤ 0 的值，或不是 Decimal。
    """
    if not adj_factors:
        raise AdjustmentError("复权因子序列为空：空序列会让后续除法静默产生空结果")
    for index, factor in enumerate(adj_factors):
        if not isinstance(factor, Decimal):
            raise AdjustmentError(
                f"adj_factors[{index}] 必须是 Decimal（禁止 float 渗进金额计算），"
                f"收到 {type(factor).__name__}"
            )
        if factor <= 0:
            raise AdjustmentError(f"adj_factors[{index}] 必须为正，收到 {factor}")


def price_scale_factors(
    adj_factors: Sequence[Decimal],
    adjust: AdjustType,
) -> tuple[Decimal, ...]:
    """计算每根 bar 的价格缩放系数 `k_i`。

    Args:
        adj_factors: 累积后复权因子序列，与 bar 序列等长。
        adjust: 复权口径，**必须显式传入**（不允许默认不复权）。

    Returns:
        与输入等长的缩放系数元组。

    Raises:
        AdjustmentError: 因子序列非法。
    """
    validate_adj_factors(adj_factors)
    if adjust is AdjustType.RAW:
        return tuple(ONE for _ in adj_factors)
    if adjust is AdjustType.BACKWARD:
        return tuple(adj_factors)
    # FORWARD：以序列末日为基准，保证最新价 === 真实最新价
    last = adj_factors[-1]
    return tuple(factor / last for factor in adj_factors)


def adjust_series(
    values: Sequence[Decimal],
    adj_factors: Sequence[Decimal],
    adjust: AdjustType,
) -> tuple[Decimal, ...]:
    """把原始价格序列换算到指定复权口径。

    Args:
        values: 原始（RAW）价格序列。
        adj_factors: 与 `values` 等长的复权因子序列。
        adjust: 目标复权口径。

    Raises:
        AdjustmentError: 长度不匹配或因子非法。
    """
    if len(values) != len(adj_factors):
        raise AdjustmentError(
            f"values 与 adj_factors 长度不匹配：{len(values)} vs {len(adj_factors)}"
        )
    factors = price_scale_factors(adj_factors, adjust)
    return tuple(value * factor for value, factor in zip(values, factors, strict=True))


def convert_view(
    values: Sequence[Decimal],
    *,
    from_adjust: AdjustType,
    to_adjust: AdjustType,
    adj_factors: Sequence[Decimal],
) -> tuple[Decimal, ...]:
    """在两种复权口径之间互算 —— "三视图可互算"验收的实现。

    这是比单看某个视图更硬的判据：如果换算公式有偏，
    `RAW → BACKWARD → RAW` 的往返不会回到原值。

    Args:
        values: `from_adjust` 口径下的值序列。
        from_adjust: 源口径。
        to_adjust: 目标口径。
        adj_factors: 与 `values` 等长的复权因子序列。

    Returns:
        `to_adjust` 口径下的值序列。
    """
    if len(values) != len(adj_factors):
        raise AdjustmentError(
            f"values 与 adj_factors 长度不匹配：{len(values)} vs {len(adj_factors)}"
        )
    # ★ 换算方向：**先除源口径系数还原成 RAW，再乘目标口径系数**。
    #   （写成 `k_from / k_to` 方向就反了。而 `X→Y→X` 往返测试抓不到这个错误 ——
    #   往返在比值取反时依然自洽。抓它必须靠"换算结果 == 对该口径直接换算"的交叉校验，
    #   见 tests/golden/test_adjustment_golden.py::TestRoundTrip::test_换算结果与直接换算一致）
    k_from = price_scale_factors(adj_factors, from_adjust)
    k_to = price_scale_factors(adj_factors, to_adjust)
    return tuple(value * kt / kf for value, kf, kt in zip(values, k_from, k_to, strict=True))
