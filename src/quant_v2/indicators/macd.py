"""MACD（指数平滑异同平均）—— 标准口径，向量化，有 golden 测试。

★ 这个文件是为根治 v1 的 `factor_scanner.py:58-72` `calc_macd` 而写的。
v1 的实现有四个问题，每一个都会让信号偏移：

1. **`dif` 用全序列一次 EMA 算，`difs` 却用前缀重算** —— 两条序列的样本基不同，
   却直接相减比较判金叉死叉。
2. **`difs` 被截断到 `len(closes) - 26` 个点** —— 序列长度对不上，
   后面的下标对齐全错。
3. **`dea` 以 `difs[0]` 作种子** —— 预热严重不足，开头几十个值偏差很大，
   而金叉死叉恰恰最容易出现在开头。
4. **循环内每次从头重算 EMA** —— O(n²)，5000 标的扫描时直接卡死。

v2 的实现：全序列向量化单次遍历（O(n)），标准 `alpha = 2/(n+1)`，
EMA 种子统一为前 n 项简单均值。

## 口径说明

- `dif = EMA(fast) - EMA(slow)`，首个有效值在下标 `slow - 1`
- `dea = EMA(dif, signal)`，首个有效值在下标 `slow + signal - 2`
- `hist = dif - dea`

  ⚠ 国内行情软件（通达信/同花顺）通常把柱状图画成 `2 × (dif - dea)`，
  本库输出**未放大**的 `dif - dea`。需要对齐国内软件的显示时自行乘 2 ——
  这里不内置放大系数，因为那会让"柱状图数值"与"金叉判据"混在一起。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from quant_v2.indicators.ema import ema

__all__ = ["MACDResult", "macd"]


@dataclass(frozen=True)
class MACDResult:
    """MACD 三条线。三条等长，按下标对齐；预热期为 `None`。"""

    dif: tuple[Decimal | None, ...]
    dea: tuple[Decimal | None, ...]
    hist: tuple[Decimal | None, ...]

    def __len__(self) -> int:
        """序列长度。"""
        return len(self.dif)


def macd(
    closes: Sequence[Decimal | None],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> MACDResult:
    """计算 MACD。

    Args:
        closes: 收盘价序列（允许前缀 `None`）。
        fast: 快线周期，默认 12。
        slow: 慢线周期，默认 26。
        signal: 信号线周期，默认 9。

    Returns:
        `MACDResult(dif, dea, hist)`，三条等长。

    Raises:
        ValueError: `fast >= slow`，或任一周期非正。
    """
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError(f"周期必须全部为正：fast={fast}, slow={slow}, signal={signal}")
    if fast >= slow:
        # 快线周期必须小于慢线，否则 dif 的符号含义会反转，金叉死叉判据全部失效
        raise ValueError(f"fast({fast}) 必须小于 slow({slow})")

    fast_line = ema(closes, fast)
    slow_line = ema(closes, slow)

    dif: list[Decimal | None] = [None] * len(closes)
    for index in range(len(closes)):
        fast_value = fast_line[index]
        slow_value = slow_line[index]
        if fast_value is not None and slow_value is not None:
            dif[index] = fast_value - slow_value

    # ★ dif 的前缀 None 由 ema() 的 prepare_series 正确处理：
    #   dea 会跳过预热期，从第 slow-1 项开始重新播种，不会引入偏差。
    dea_line = ema(dif, signal)

    hist: list[Decimal | None] = [None] * len(closes)
    for index in range(len(closes)):
        dif_value = dif[index]
        dea_value = dea_line[index]
        if dif_value is not None and dea_value is not None:
            hist[index] = dif_value - dea_value

    return MACDResult(dif=tuple(dif), dea=tuple(dea_line), hist=tuple(hist))
