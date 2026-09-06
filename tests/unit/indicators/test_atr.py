"""ATR / TrueRange 单元测试 —— 真实波幅口径正确性 + 预热期边界。

★ 锁定这条规则的原因：仓位算法（SizingRequest.atr）与止损计算都依赖 ATR，
  口径错了整个风控失真。验证分三层：

1. 长度/预热期形状（无业务）
2. TrueRange 的逐项公式（含首日 high-low、含跳空扩展）
3. ATR 与 Wilder 平滑层的一致性（用独立参考实现）
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quant_v2.indicators._smoothing import wilder_smooth
from quant_v2.indicators.atr import atr, true_range

pytestmark = pytest.mark.unit


def d(v: str) -> Decimal:
    return Decimal(v)


# ============================================================================
# true_range
# ============================================================================


def test_tr_length_matches_input() -> None:
    highs = [d("10"), d("11"), d("12")]
    lows = [d("9"), d("10"), d("11")]
    closes = [d("9.5"), d("10.5"), d("11.5")]
    result = true_range(highs, lows, closes)
    assert len(result) == 3


def test_tr_first_bar_uses_high_minus_low() -> None:
    """首根 bar 用 `high - low`，没有前收盘。"""
    highs = [d("10")]
    lows = [d("8")]
    closes = [d("9.5")]
    result = true_range(highs, lows, closes)
    assert result == [d("2")]


def test_tr_picks_max_of_three_candidates() -> None:
    """TR[i] = max(high-low, |high-prev_close|, |low-prev_close|)。"""
    highs = [d("10"), d("12")]
    lows = [d("9"), d("10")]
    closes = [d("9.5"), d("11")]
    result = true_range(highs, lows, closes)
    # 第二天：high-low=2, |high-prev|=2.5, |low-prev|=0.5 → 取 2.5
    assert result == [d("1"), d("2.5")]


def test_tr_handles_gap_up() -> None:
    """跳空高开：|high - prev_close| 通常大于 high-low。"""
    highs = [d("10"), d("15")]
    lows = [d("9"), d("14.5")]
    closes = [d("10"), d("14.8")]
    result = true_range(highs, lows, closes)
    # 第二天：high-low=0.5, |high-prev|=5, |low-prev|=4.5 → 取 5
    assert result[1] == d("5")


def test_tr_clamped_to_zero() -> None:
    """★ 负数候选值被夹到 0：若 high<low（数据脏），TR 不会变负。"""
    highs = [d("10"), d("9")]
    lows = [d("9"), d("10")]  # 第二根 high=9, low=10（脏数据）
    closes = [d("10"), d("10")]
    result = true_range(highs, lows, closes)
    # 第二天：high-low=-1（脏），|high-prev|=1，|low-prev|=0 → max(0,1,0)=1；min 与 0 取 max=1
    assert result[1] == d("1")


def test_tr_length_mismatch_raises() -> None:
    """三条序列长度不一致 → 抛 ValueError（禁止静默截断）。"""
    with pytest.raises(ValueError, match="长度必须一致"):
        true_range([d("10")], [d("9")], [d("9.5"), d("10.5")])


def test_tr_prefix_alignment_required() -> None:
    """三条序列的预热期（前置 None 数）必须一致。

    长度必须先一致才能比对预热期：两个 highs/lows 是 [None, x]，
    closes 是 [x]，长度一致；但预热期长度不同 → 触发预热期校验。
    """
    with pytest.raises(ValueError, match="预热期长度必须一致"):
        true_range([None, d("10")], [None, d("9")], [d("9.5"), d("10.5")])


def test_tr_hole_after_warmup_raises() -> None:
    """预热期之后出现空洞 → 抛 ValueError（与 prepare_series 一致）。"""
    with pytest.raises(ValueError, match="空洞"):
        true_range([d("10"), None, d("12")], [d("9"), None, d("11")], [d("9.5"), None, d("11.5")])


# ============================================================================
# atr
# ============================================================================


def test_atr_period_must_be_positive() -> None:
    """n <= 0 抛 ValueError。"""
    with pytest.raises(ValueError, match="周期必须为正"):
        atr([d("10")], [d("9")], [d("9.5")], n=0)


def test_atr_first_n_minus_1_are_none() -> None:
    """前 n-1 项为 None（与 Wilder 平滑的预热期口径一致）。"""
    highs = [d(str(10 + i)) for i in range(20)]
    lows = [d(str(9 + i)) for i in range(20)]
    closes = [d(str(9.5 + i)) for i in range(20)]
    result = atr(highs, lows, closes, n=14)
    # n=14 → 前 13 项 None；下标 14 开始有值
    assert result[:13] == [None] * 13
    assert result[13] is not None
    assert all(v is not None for v in result[13:])


def test_atr_equivalent_to_independent_reference() -> None:
    """★ 对照独立参考实现：手工算 TR、再用 Wilder 公式逐项递推。

    这是 golden test 的功能等价版（不引外部数据源），确认 atr() 内部
    没有悄悄加常数或偏移。
    """
    highs = [d("10"), d("12"), d("11"), d("13"), d("12")]
    lows = [d("9"), d("10"), d("9.5"), d("11"), d("10")]
    closes = [d("9.5"), d("11"), d("10.5"), d("12"), d("11")]

    # 1) 手工 TR
    tr: list[Decimal] = [highs[0] - lows[0]]
    for i in range(1, len(highs)):
        candidate = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr.append(max(candidate, d("0")))

    # 2) Wilder 平滑（n=3 便于逐项核对）
    n = 3
    seed = sum(tr[:n]) / d(n)
    expected: list[Decimal | None] = [None] * (n - 1) + [seed]
    for i in range(n, len(tr)):
        prev = expected[i - 1]
        assert prev is not None
        next_val = (prev * d(n - 1) + tr[i]) / d(n)
        expected.append(next_val)

    # 3) 调 atr() 验证一致
    result = atr(highs, lows, closes, n=n)
    for got, want in zip(result, expected, strict=True):
        assert got == want, f"分项不等：got={got}, want={want}"


def test_atr_uses_wilder_smoothing_not_simple_ma() -> None:
    """★ ATR 必须用 Wilder 递推，不能用简单移动平均（这是 v1 真实 bug）。"""
    # 构造一段波动率突变的样本：前 5 个 TR 极小，后 5 个 TR 极大
    highs = [
        d("10"),
        d("10.1"),
        d("10.2"),
        d("10.1"),
        d("10.2"),
        d("100"),
        d("105"),
        d("110"),
        d("108"),
        d("112"),
    ]
    lows = [
        d("9.9"),
        d("10"),
        d("10.1"),
        d("10"),
        d("10.1"),
        d("50"),
        d("60"),
        d("70"),
        d("75"),
        d("80"),
    ]
    closes = [
        d("10"),
        d("10.05"),
        d("10.15"),
        d("10.05"),
        d("10.15"),
        d("75"),
        d("85"),
        d("95"),
        d("90"),
        d("100"),
    ]
    n = 5
    result = atr(highs, lows, closes, n=n)
    # 手工算 TR
    tr: list[Decimal] = [highs[0] - lows[0]]
    for i in range(1, len(highs)):
        hi_lo = highs[i] - lows[i]
        hi_prev_close = abs(highs[i] - closes[i - 1])
        lo_prev_close = abs(lows[i] - closes[i - 1])
        tr.append(max(hi_lo, hi_prev_close, lo_prev_close, d("0")))
    expected = wilder_smooth(tr, n)
    # ATR 内部也应输出同一组数（仅对齐 pre-None）
    for got, want in zip(result[n - 1 :], expected[n - 1 :], strict=True):
        assert got == want


def test_atr_length_matches_input() -> None:
    """ATR 输出长度 = 输入长度。"""
    highs = [d("10"), d("11"), d("12")]
    lows = [d("9"), d("10"), d("11")]
    closes = [d("9.5"), d("10.5"), d("11.5")]
    result = atr(highs, lows, closes, n=2)
    assert len(result) == 3


def test_atr_constant_series_zero_atr() -> None:
    """常数序列（无波动）→ ATR 收敛到 0。"""
    n = 4
    highs = [d("10")] * 10
    lows = [d("10")] * 10
    closes = [d("10")] * 10
    result = atr(highs, lows, closes, n=n)
    for v in result[n - 1 :]:
        assert v == d("0")
