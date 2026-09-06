"""SMA / EMA / Wilder 平滑。

★ 这三段是全部指标的公共底座。它们错了，MACD / RSI / ATR 会一起错，
而且错得很隐蔽（曲线形状还在，只是数值偏了）。所以这里的断言刻意写得比业务代码还细。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from quant_v2.indicators._smoothing import ZERO, prepare_series, wilder_smooth
from quant_v2.indicators.ema import ema
from quant_v2.indicators.ma import sma

pytestmark = pytest.mark.unit


def dec(values: list[str]) -> list[Decimal | None]:
    return [Decimal(v) for v in values]


class TestSMA:
    def test_首个有效值出现在第_n_1_项(self) -> None:
        out = sma(dec(["1", "2", "3", "4", "5"]), 3)
        assert out[:2] == [None, None]
        assert out[2] == Decimal(2)  # (1+2+3)/3
        assert out[3] == Decimal(3)  # (2+3+4)/3
        assert out[4] == Decimal(4)  # (3+4+5)/3

    def test_长度与输入一致(self) -> None:
        out = sma(dec(["1", "2", "3"]), 5)
        assert len(out) == 3
        assert all(v is None for v in out)

    def test_常数序列等于自身(self) -> None:
        out = sma(dec(["7"] * 10), 4)
        assert all(v is None or v == Decimal(7) for v in out)

    def test_周期非正报错(self) -> None:
        with pytest.raises(ValueError, match="窗口长度必须为正"):
            sma(dec(["1", "2"]), 0)


class TestEMA:
    def test_种子是前_n_项简单均值(self) -> None:
        # EMA(3) 的首个有效值 = mean(1,2,3) = 2
        out = ema(dec(["1", "2", "3", "10"]), 3)
        assert out[2] == Decimal(2)

    def test_递推式逐项成立(self) -> None:
        values = dec(["1", "2", "3", "10", "4"])
        out = ema(values, 3)
        alpha = Decimal(2) / Decimal(4)  # 2/(n+1), n=3
        expected = out[2]
        assert expected is not None
        for i in range(3, len(values)):
            assert values[i] is not None
            expected = values[i] * alpha + expected * (Decimal(1) - alpha)
            assert out[i] is not None
            assert abs(out[i] - expected) < Decimal("1e-24"), f"下标 {i} 的 EMA 与递推式不符"

    def test_常数序列收敛到自身(self) -> None:
        out = ema(dec(["5"] * 40), 5)
        last = out[-1]
        assert last is not None
        assert abs(last - Decimal(5)) < Decimal("1e-24")

    def test_前缀None被跳过且长度不变(self) -> None:
        values: list[Decimal | None] = [None, None, *dec(["1", "2", "3", "4"])]
        out = ema(values, 3)
        assert len(out) == 6
        assert out[:4] == [None] * 4  # 前两项是输入 None，第三项是预热期起点错位
        assert out[4] is not None

    def test_预热期之后出现空洞报错(self) -> None:
        values: list[Decimal | None] = [Decimal(1), Decimal(2), None, Decimal(4)]
        with pytest.raises(ValueError, match="不允许再出现空洞"):
            ema(values, 2)


class TestWilderSmooth:
    def test_种子是简单均值_递推为Wilder式(self) -> None:
        gains = [Decimal(1), Decimal(2), Decimal(3), Decimal(10)]
        out = wilder_smooth(gains, 3)
        assert out[2] == Decimal(2)  # mean(1,2,3)
        n = Decimal(3)
        expected = out[2]
        assert expected is not None
        for i in range(3, len(gains)):
            expected = (expected * (n - 1) + gains[i]) / n
            assert out[i] is not None
            assert abs(out[i] - expected) < Decimal("1e-24")

    def test_Wilder平滑不等于简单移动平均(self) -> None:
        """★ 回归：v1 用简单均值代替 Wilder 平滑，是其实证缺陷之一。

        这两者必须**不相等**，否则说明有人又把它改回简单均值了。
        """
        gains = [Decimal(x) for x in (1, 4, 2, 8, 3, 9, 5, 7, 6, 11)]
        out = wilder_smooth(gains, 4)
        wilder_last = out[-1]
        assert wilder_last is not None
        sma_last = sum(gains[-4:], ZERO) / Decimal(4)
        assert wilder_last != sma_last, "Wilder 平滑退化成了简单移动平均"

    def test_周期非正报错(self) -> None:
        with pytest.raises(ValueError, match="平滑周期必须为正"):
            wilder_smooth([Decimal(1)], 0)


class TestPrepareSeries:
    def test_全None返回空段(self) -> None:
        start, dense = prepare_series([None, None])
        assert start == 2
        assert dense == ()

    def test_去前缀并保留首个有效下标(self) -> None:
        start, dense = prepare_series([None, Decimal(3), Decimal(4)])
        assert start == 1
        assert dense == (Decimal(3), Decimal(4))

    def test_中间空洞报错(self) -> None:
        with pytest.raises(ValueError, match="空洞"):
            prepare_series([Decimal(1), None, Decimal(3)])
