"""指标 golden 测试 —— 对照**独立实现**而不是"自己算一遍"。

★ 关键区别：如果 golden 值来自被测代码本身，那测试只是把 bug 固化成常量。
这里的参考值有两个独立来源：

1. **Wilder《New Concepts in Technical Trading Systems》的 RSI 示例**
   （StockCharts 等公开教材转载的同一组数据）—— 外部真值
2. **用 `fractions.Fraction` 重写的一份精算参考实现** —— 不复用被测代码的
   任何函数（不调 `ema()` / `wilder_smooth()`），且用有理数避免 Decimal 精度取舍
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from quant_v2.indicators.macd import macd
from quant_v2.indicators.rsi import rsi

pytestmark = pytest.mark.golden

# ============================================================================
# 参考实现（独立，用 Fraction 精算）
# ============================================================================


def ref_ema(values: list[Fraction], n: int) -> list[Fraction | None]:
    """EMA 参考实现：`alpha = 2/(n+1)`，种子为前 n 项简单均值。"""
    out: list[Fraction | None] = [None] * len(values)
    if len(values) < n:
        return out
    alpha = Fraction(2, n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * alpha + prev * (1 - alpha)
        out[i] = prev
    return out


def ref_macd(
    closes: list[Fraction], *, fast: int, slow: int, signal: int
) -> tuple[list[Fraction | None], list[Fraction | None], list[Fraction | None]]:
    """MACD 参考实现：DIF = EMA_fast - EMA_slow，DEA = EMA_signal(DIF)。"""
    f_fast = ref_ema(closes, fast)
    f_slow = ref_ema(closes, slow)
    dif: list[Fraction | None] = [
        None if (a is None or b is None) else a - b for a, b in zip(f_fast, f_slow, strict=True)
    ]
    start = next((i for i, v in enumerate(dif) if v is not None), None)
    if start is None:
        return dif, [None] * len(closes), [None] * len(closes)
    dea_dense = ref_ema([v for v in dif[start:] if v is not None], signal)  # type: ignore[misc]
    dea: list[Fraction | None] = [None] * len(closes)
    for offset, value in enumerate(dea_dense):
        dea[start + offset] = value
    hist: list[Fraction | None] = [
        None if (d is None or s is None) else d - s for d, s in zip(dif, dea, strict=True)
    ]
    return dif, dea, hist


def ref_rsi_wilder(closes: list[Fraction], n: int) -> list[Fraction | None]:
    """Wilder RSI 参考实现：gain/loss 分别做 Wilder 平滑。"""
    out: list[Fraction | None] = [None] * len(closes)
    gains: list[Fraction] = []
    losses: list[Fraction] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, Fraction(0)))
        losses.append(max(-delta, Fraction(0)))
    if len(gains) < n:
        return out

    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    out[n] = _rsi_from(avg_gain, avg_loss)
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        out[i + 1] = _rsi_from(avg_gain, avg_loss)
    return out


def _rsi_from(avg_gain: Fraction, avg_loss: Fraction) -> Fraction:
    if avg_loss == 0:
        return Fraction(100) if avg_gain > 0 else Fraction(50)
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def close_enough(actual: Decimal | None, expected: Fraction | None, tol: Decimal) -> bool:
    if (actual is None) != (expected is None):
        return False
    if actual is None or expected is None:
        return True
    # Fraction → Decimal：取足够精度后再比，避免转换本身引入误差
    approx = Decimal(expected.numerator) / Decimal(expected.denominator)
    return abs(actual - approx) < tol


# ============================================================================
# MACD
# ============================================================================

MACD_CLOSES = [
    "10",
    "10.5",
    "11",
    "10.8",
    "11.5",
    "12",
    "11.8",
    "12.5",
    "13",
    "12.8",
    "13.5",
    "14",
    "13.8",
    "14.5",
    "15",
    "15.5",
    "15.2",
    "16",
    "16.5",
    "16.2",
    "17",
    "17.5",
    "17.2",
    "18",
    "18.5",
    "18.2",
    "19",
    "19.5",
    "19.2",
    "20",
    "20.5",
    "20.2",
    "21",
    "21.5",
    "21.2",
    "22",
]


class TestMacdGolden:
    def test_与Fraction精算参考实现逐点一致(self) -> None:
        closes = [Decimal(v) for v in MACD_CLOSES]
        result = macd(closes, fast=12, slow=26, signal=9)
        f_closes = [Fraction(v) for v in MACD_CLOSES]
        ref_dif, ref_dea, ref_hist = ref_macd(f_closes, fast=12, slow=26, signal=9)

        tol = Decimal("1e-9")
        for i in range(len(closes)):
            assert close_enough(result.dif[i], ref_dif[i], tol), f"dif[{i}]"
            assert close_enough(result.dea[i], ref_dea[i], tol), f"dea[{i}]"
            assert close_enough(result.hist[i], ref_hist[i], tol), f"hist[{i}]"

    def test_hist恒等于dif减dea(self) -> None:
        """柱状图的定义式 —— 若有任何一处对不上，说明三条线被错位拼接了。"""
        closes = [Decimal(v) for v in MACD_CLOSES]
        result = macd(closes)
        for i in range(len(closes)):
            dif, dea, hist = result.dif[i], result.dea[i], result.hist[i]
            # HIST 需要 DIF 与 DEA 同时可用；DEA 的预热期比 DIF 长（见 test_预热期长度符合定义）
            if dif is None or dea is None:
                assert hist is None, f"下标 {i}：DEA 尚在预热，HIST 不应有值"
                continue
            assert hist is not None, f"下标 {i}：DIF 与 DEA 都已就绪，HIST 不应为 None"
            assert abs(hist - (dif - dea)) < Decimal("1e-24"), f"hist[{i}] ≠ dif - dea"

    def test_预热期长度符合定义(self) -> None:
        """DIF 首个有效值在 slow-1；DEA 在其之上再预热 signal-1 个有效值。"""
        closes = [Decimal(v) for v in MACD_CLOSES]
        result = macd(closes, fast=12, slow=26, signal=9)
        first_dif = next(i for i, v in enumerate(result.dif) if v is not None)
        first_dea = next(i for i, v in enumerate(result.dea) if v is not None)
        assert first_dif == 25, f"DIF 首个有效值应为 26-1=25，实际 {first_dif}"
        assert first_dea == 33, f"DEA 应在 DIF 之上再预热 8 项，实际 {first_dea}"

    def test_三条线等长且等于输入(self) -> None:
        closes = [Decimal(v) for v in MACD_CLOSES]
        result = macd(closes)
        assert len(result) == len(closes)
        assert len(result.dea) == len(closes)
        assert len(result.hist) == len(closes)

    def test_fast不小于slow报错(self) -> None:
        """快线周期 ≥ 慢线时，金叉死叉的符号含义会反转 —— 必须拒绝。"""
        closes = [Decimal(v) for v in MACD_CLOSES]
        with pytest.raises(ValueError, match="fast"):
            macd(closes, fast=26, slow=12)


# ============================================================================
# RSI —— Wilder 教材示例（外部真值）
# ============================================================================

# Wilder / StockCharts 公开教材的 RSI(14) 示例收盘价
WILDER_CLOSES = [
    44.34,
    44.09,
    44.15,
    43.61,
    44.33,
    44.83,
    45.10,
    45.42,
    45.84,
    46.08,
    45.89,
    46.03,
    45.61,
    46.28,
    46.28,
    46.00,
    46.03,
    46.41,
    46.22,
    45.64,
    46.21,
    46.25,
    45.71,
    46.45,
    45.78,
    45.35,
    44.03,
    44.18,
    44.22,
    44.57,
    43.42,
    42.66,
    43.13,
]

# 教材公布的 RSI(14) 值（从下标 14 起）
WILDER_RSI_14 = [
    70.53,
    66.32,
    66.55,
    69.41,
    66.36,
    57.97,
    62.93,
    63.26,
    56.06,
    62.38,
    54.71,
    50.42,
    39.99,
    41.46,
    41.87,
    45.46,
    37.30,
    33.08,
    37.77,
]


class TestRsiGolden:
    def test_与Wilder教材公布值一致(self) -> None:
        """★ 外部真值对照。

        容差取 0.15：教材表格把中间结果（平均涨跌）四舍五入到两位小数后继续递推，
        累计下来有约 0.03~0.07 的偏差。这是我们**故意不模仿**的做法 ——
        v2 全程用 Decimal 精算，不引入中间取整。
        """
        closes = [Decimal(str(v)) for v in WILDER_CLOSES]
        out = rsi(closes, 14)
        for offset, expected in enumerate(WILDER_RSI_14):
            index = 14 + offset
            actual = out[index]
            assert actual is not None, f"RSI[{index}] 不应为 None"
            assert abs(actual - Decimal(str(expected))) < Decimal("0.15"), (
                f"RSI[{index}]={actual:.4f} vs 教材值 {expected}"
            )

    def test_与Fraction精算参考实现一致(self) -> None:
        closes = [Decimal(str(v)) for v in WILDER_CLOSES]
        out = rsi(closes, 14)
        ref = ref_rsi_wilder([Fraction(str(v)) for v in WILDER_CLOSES], 14)
        tol = Decimal("1e-9")
        for i in range(len(closes)):
            assert close_enough(out[i], ref[i], tol), f"RSI[{i}]={out[i]} vs 参考 {ref[i]}"

    def test_全程上涨趋近100(self) -> None:
        closes = [Decimal(10) + Decimal(i) for i in range(40)]
        out = rsi(closes, 14)
        last = out[-1]
        assert last is not None and last == Decimal(100), f"只涨不跌时 RSI 应为 100，实际 {last}"

    def test_全程下跌趋近0(self) -> None:
        closes = [Decimal(50) - Decimal(i) for i in range(40)]
        out = rsi(closes, 14)
        last = out[-1]
        assert last is not None and last == Decimal(0), f"只跌不涨时 RSI 应为 0，实际 {last}"

    def test_横盘不动取中性值50(self) -> None:
        """★ 0/0 无定义，但给 100 会让用户误以为是极强上涨趋势。

        这个"取 50"是本项目的显式约定（见 rsi.py 模块 docstring），
        测试把它固定下来，避免后人改成 0 或 100。
        """
        closes = [Decimal(20)] * 30
        out = rsi(closes, 14)
        last = out[-1]
        assert last == Decimal(50), f"完全无波动时应为中性 50，实际 {last}"

    def test_预热期长度符合定义(self) -> None:
        closes = [Decimal(str(v)) for v in WILDER_CLOSES]
        out = rsi(closes, 14)
        first = next(i for i, v in enumerate(out) if v is not None)
        assert first == 14, f"RSI(14) 首个有效值应在下标 14，实际 {first}"
