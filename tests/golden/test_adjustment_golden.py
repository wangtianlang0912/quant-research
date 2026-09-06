"""复权三视图 golden 测试（D-03）。

★ 这是 v2 对 v1「复权零处理」的根治验收。v1 的
`local_csv_adapter.py:56` 把 `adjust_type` 当标签贴上去、数据原样返回，
`backtest_runner.py:203` 甚至从不传 `adjust_type` —— QFQ/HFQ 从未被真正请求过。

验收判据（比"某个视图看起来对"更硬）：

1. **10 送 10 除权案例**：RAW 有 -50% 假跳空，BACKWARD / FORWARD 都连续
2. **末日锚定**：`FORWARD[-1] == RAW[-1]`（前复权以最新价为真实价）
3. **首日锚定**：`BACKWARD[0] == RAW[0]`（后复权以历史价为真实价）
4. **三视图可互算**：任意 `X → Y → X` 往返误差 < 1e-6
5. **比例恒定**：`BACKWARD[i] / FORWARD[i] == f_last`（常量）
"""

from __future__ import annotations

from decimal import Decimal
from itertools import permutations

import pytest

from quant_v2.domain.errors import AdjustmentError
from quant_v2.domain.models.bar import AdjustType
from quant_v2.domain.services.adjustment import (
    adjust_series,
    convert_view,
    price_scale_factors,
    validate_adj_factors,
)

pytestmark = pytest.mark.golden

TOLERANCE = Decimal("1e-6")

# 10 送 10：close 20 → 10，累积后复权因子 1 → 2
SPLIT_CLOSES = [Decimal("20"), Decimal("10")]
SPLIT_FACTORS = [Decimal("1"), Decimal("2")]

# 一段含两次除权的价格序列（10 送 10，随后 10 派 1 元近似为因子 2 → 2.1）
MULTI_CLOSES = [Decimal("20"), Decimal("10"), Decimal("9.5"), Decimal("10.5")]
MULTI_FACTORS = [Decimal("1"), Decimal("2"), Decimal("2"), Decimal("2.1")]


def assert_close(actual: Decimal, expected: Decimal, label: str) -> None:
    diff = abs(actual - expected)
    assert diff < TOLERANCE, f"{label}：{actual} vs {expected}（差 {diff} ≥ {TOLERANCE}）"


class TestSplitCase:
    """10 送 10 除权：最经典的"假跳空"案例。"""

    def test_RAW_保留百分之五十的假跳空(self) -> None:
        raw = adjust_series(SPLIT_CLOSES, SPLIT_FACTORS, AdjustType.RAW)
        assert raw == (Decimal("20"), Decimal("10")), "RAW 必须保留真实成交价（含除权跳空）"

    def test_BACKWARD_连续(self) -> None:
        backward = adjust_series(SPLIT_CLOSES, SPLIT_FACTORS, AdjustType.BACKWARD)
        assert backward == (Decimal("20"), Decimal("20"))

    def test_FORWARD_连续(self) -> None:
        forward = adjust_series(SPLIT_CLOSES, SPLIT_FACTORS, AdjustType.FORWARD)
        assert forward == (Decimal("10"), Decimal("10"))

    def test_三视图两两比值恒定(self) -> None:
        """BACKWARD[i] / FORWARD[i] == f_last，与 i 无关。"""
        backward = adjust_series(SPLIT_CLOSES, SPLIT_FACTORS, AdjustType.BACKWARD)
        forward = adjust_series(SPLIT_CLOSES, SPLIT_FACTORS, AdjustType.FORWARD)
        f_last = SPLIT_FACTORS[-1]
        for i, (b, f) in enumerate(zip(backward, forward, strict=True)):
            assert_close(b / f, f_last, f"下标 {i} 的 BACKWARD/FORWARD")


class TestAnchoring:
    def test_FORWARD_末日等于真实最新价(self) -> None:
        """★ 前复权的定义性判据：最新一日价格必须是真实成交价。

        否则前端显示的"现价"与行情软件对不上，用户会立刻失去信任。
        """
        for closes, factors in ((SPLIT_CLOSES, SPLIT_FACTORS), (MULTI_CLOSES, MULTI_FACTORS)):
            forward = adjust_series(closes, factors, AdjustType.FORWARD)
            assert_close(forward[-1], closes[-1], "FORWARD 末日锚定")

    def test_BACKWARD_首日等于真实历史价(self) -> None:
        for closes, factors in ((SPLIT_CLOSES, SPLIT_FACTORS), (MULTI_CLOSES, MULTI_FACTORS)):
            backward = adjust_series(closes, factors, AdjustType.BACKWARD)
            assert_close(backward[0], closes[0], "BACKWARD 首日锚定")

    def test_无除权时三视图完全相等(self) -> None:
        closes = [Decimal("10"), Decimal("11"), Decimal("12")]
        factors = [Decimal("1")] * 3
        for adjust in AdjustType:
            view = adjust_series(closes, factors, adjust)
            assert view == tuple(closes), f"{adjust.value} 在无除权时不应改变价格"


class TestRoundTrip:
    """三视图互算：换算公式若有偏，往返回不到原值。"""

    @pytest.mark.parametrize(("from_adjust", "to_adjust"), list(permutations(AdjustType, 2)))
    def test_任意两视图往返误差小于1e_6(
        self, from_adjust: AdjustType, to_adjust: AdjustType
    ) -> None:
        source = adjust_series(MULTI_CLOSES, MULTI_FACTORS, from_adjust)
        converted = convert_view(
            source,
            from_adjust=from_adjust,
            to_adjust=to_adjust,
            adj_factors=MULTI_FACTORS,
        )
        back = convert_view(
            converted,
            from_adjust=to_adjust,
            to_adjust=from_adjust,
            adj_factors=MULTI_FACTORS,
        )
        for i, (origin, returned) in enumerate(zip(source, back, strict=True)):
            assert_close(returned, origin, f"{from_adjust.value}→{to_adjust.value}→回 下标 {i}")

    def test_换算结果与直接换算一致(self) -> None:
        """convert_view 必须等于"先还原 RAW 再换算到目标口径"。"""
        for target in AdjustType:
            direct = adjust_series(MULTI_CLOSES, MULTI_FACTORS, target)
            via_convert = convert_view(
                MULTI_CLOSES,
                from_adjust=AdjustType.RAW,
                to_adjust=target,
                adj_factors=MULTI_FACTORS,
            )
            for i, (a, b) in enumerate(zip(direct, via_convert, strict=True)):
                assert_close(a, b, f"{target.value} 直接换算 vs convert_view 下标 {i}")


class TestScaleFactors:
    def test_RAW_缩放系数恒为一(self) -> None:
        assert price_scale_factors(MULTI_FACTORS, AdjustType.RAW) == (
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
        )

    def test_BACKWARD_缩放系数即因子本身(self) -> None:
        assert price_scale_factors(MULTI_FACTORS, AdjustType.BACKWARD) == tuple(MULTI_FACTORS)

    def test_FORWARD_末日系数为一(self) -> None:
        factors = price_scale_factors(MULTI_FACTORS, AdjustType.FORWARD)
        assert_close(factors[-1], Decimal("1"), "FORWARD 末日缩放系数")


class TestValidation:
    def test_空因子序列报错(self) -> None:
        with pytest.raises(AdjustmentError, match="序列为空"):
            validate_adj_factors([])

    def test_非正因子报错(self) -> None:
        with pytest.raises(AdjustmentError, match="必须为正"):
            validate_adj_factors([Decimal("1"), Decimal("0")])

    def test_float渗透报错(self) -> None:
        """★ ARCH013：金额计算里不许出现 float，这里再兜一层运行时检查。"""
        with pytest.raises(AdjustmentError, match="必须是 Decimal"):
            validate_adj_factors([Decimal("1"), 2.0])  # type: ignore[list-item]

    def test_长度不匹配报错(self) -> None:
        with pytest.raises(AdjustmentError, match="长度不匹配"):
            adjust_series([Decimal("1")], [Decimal("1"), Decimal("2")], AdjustType.RAW)
