"""Donchian 通道单元测试 —— 重点锁死"含/不含当前 bar"两种变体的差异。

★ v1 反例：breakout_scorer.py 同时用两种口径生成信号，导致
  "突破当前上轨" 用的是同一个窗口计算上下轨，信号永远成立 —— 年化 200%。
  本测试的核心是确认两个变体的下标与窗口边界**严格不重合**。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quant_v2.indicators.donchian import donchian, donchian_prior

pytestmark = pytest.mark.unit


def d(v: str) -> Decimal:
    return Decimal(v)


def test_donchian_period_must_be_positive() -> None:
    """n <= 0 抛 ValueError。"""
    with pytest.raises(ValueError, match="通道周期必须为正"):
        donchian([d("10")], [d("9")], n=0)


def test_donchian_prior_period_must_be_positive() -> None:
    with pytest.raises(ValueError, match="通道周期必须为正"):
        donchian_prior([d("10")], [d("9")], n=0)


def test_donchian_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="长度必须一致"):
        donchian([d("10"), d("11")], [d("9")])


def test_donchian_prior_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="长度必须一致"):
        donchian_prior([d("10"), d("11")], [d("9")])


# ============================================================================
# 含当前 bar —— donchian()
# ============================================================================


def test_donchian_first_valid_index_is_n_minus_1() -> None:
    """含当前 bar 时，首个有效下标 = n - 1。"""
    highs = [d(str(10 + i)) for i in range(10)]
    lows = [d(str(9 + i)) for i in range(10)]
    n = 5
    result = donchian(highs, lows, n=n)
    assert result.upper[: n - 1] == (None,) * (n - 1)
    assert result.upper[n - 1] is not None


def test_donchian_includes_current_bar_high() -> None:
    """含当前 bar：当前 bar 的 high 必须进入 max 计算。"""
    # 让当前 bar 的 high 是 5 根内的最大值
    highs = [d("10"), d("11"), d("9"), d("10"), d("15")]  # 第 5 根是峰值
    lows = [d("9"), d("10"), d("8"), d("9"), d("14")]
    result = donchian(highs, lows, n=5)
    assert result.upper[4] == d("15")


def test_donchian_length_matches_input() -> None:
    """输出三条序列长度 = 输入长度。"""
    highs = [d(str(10 + i)) for i in range(8)]
    lows = [d(str(9 + i)) for i in range(8)]
    result = donchian(highs, lows, n=3)
    assert len(result) == 8
    assert len(result.upper) == 8
    assert len(result.lower) == 8
    assert len(result.middle) == 8


def test_donchian_middle_is_midpoint() -> None:
    """中轨 = (上轨 + 下轨) / 2。"""
    highs = [d("12"), d("11"), d("13"), d("14"), d("10")]
    lows = [d("8"), d("7"), d("9"), d("10"), d("6")]
    result = donchian(highs, lows, n=3)
    for upper, lower, mid in zip(result.upper, result.lower, result.middle, strict=True):
        if upper is not None and lower is not None and mid is not None:
            assert mid == (upper + lower) / d("2")


def test_donchian_too_short_returns_all_none() -> None:
    """输入不足 n 根 → 全部 None（不抛错，但结果不可用）。"""
    highs = [d("10"), d("11")]
    lows = [d("9"), d("10")]
    result = donchian(highs, lows, n=5)
    assert result.upper == (None, None)


def test_donchian_hole_after_warmup_raises() -> None:
    """预热期后空洞 → 抛 ValueError。"""
    with pytest.raises(ValueError, match="空洞"):
        donchian(
            [d("10"), d("11"), None, d("13"), d("14")],
            [d("9"), d("10"), None, d("11"), d("12")],
            n=3,
        )


# ============================================================================
# 不含当前 bar —— donchian_prior()
# ============================================================================


def test_donchian_prior_first_valid_index_is_n() -> None:
    """★ 不含当前 bar：首个有效下标 = n（不是 n-1！这是两种变体的本质区别）。"""
    highs = [d(str(10 + i)) for i in range(10)]
    lows = [d(str(9 + i)) for i in range(10)]
    n = 5
    result = donchian_prior(highs, lows, n=n)
    assert result.upper[:n] == (None,) * n
    assert result.upper[n] is not None


def test_donchian_prior_excludes_current_bar_high() -> None:
    """★ 当前 bar 的 high 不应进入 max 计算 —— 不然信号就是未来函数。

    样本长度 = n + 1，确保 prior 在最后一根有值。
    """
    highs = [d("10"), d("11"), d("9"), d("10"), d("10"), d("100")]
    lows = [d("9"), d("10"), d("8"), d("9"), d("9"), d("50")]
    n = 5
    result = donchian_prior(highs, lows, n=n)
    # 当前 bar 在下标 5，prior 上轨应基于下标 0..4 的 max = 11（不含第 5 根 100）
    assert result.upper[5] == d("11")


def test_donchian_prior_too_short_returns_all_none() -> None:
    """输入不足 n+1 根 → 全部 None。"""
    highs = [d("10"), d("11"), d("12")]
    lows = [d("9"), d("10"), d("11")]
    result = donchian_prior(highs, lows, n=5)
    assert result.upper == (None, None, None)


# ============================================================================
# 含/不含 当前 bar 的差异 —— 这才是真正的回归防线
# ============================================================================


def test_two_variants_disagree_on_breakout_bar() -> None:
    """★ 在突破发生的那根 bar 上，两种变体给出的上轨**不同**。

    这是 v1 真实 bug 的回归防线：如果两个函数上轨相同，
    就说明其中之一含了未来数据。

    样本长度 = n + 1，确保 prior 在最后一根有值（prior 要求 len > n）。
    """
    highs = [d("10"), d("11"), d("9"), d("10"), d("10"), d("100")]
    lows = [d("9"), d("10"), d("8"), d("9"), d("9"), d("50")]
    n = 5
    inclusive = donchian(highs, lows, n=n)
    exclusive = donchian_prior(highs, lows, n=n)
    # 突破 bar（下标 5）：
    # 含当前 bar → 上轨 = 100（含自己）
    # 不含当前 bar → 上轨 = 11（不含自己）
    assert inclusive.upper[5] == d("100")
    assert exclusive.upper[5] == d("11")
    # 两条不能相等 —— 也就是这一行就是这个测试想锁死的核心
    assert inclusive.upper[5] != exclusive.upper[5]
