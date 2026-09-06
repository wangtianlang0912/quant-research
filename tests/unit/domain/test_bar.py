"""Bar 契约与 BarPanel 的补充覆盖。

补的是上一轮没盖到的分支：

- `Bar.tradable`（非交易日 / 停牌 / 不可交易品种）
- `_validate_ohlc` 的早退与三条异常
- `PriceView.__len__` / `close_at`
- `BarPanel` 的三条构造期校验与 `symbol` / `market` / `currency` 属性
- `to_view()` 三视图与 `as_safe_series()` 的未来函数守卫
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from tests.conftest import FIXED_AS_OF, make_bars

from quant_v2.domain.errors import LookaheadViolationError
from quant_v2.domain.models.bar import (
    AdjustType,
    Bar,
    BarPanel,
    InstrumentType,
    PriceView,
)

pytestmark = pytest.mark.unit


def d(value: str) -> Decimal:
    """构造 Decimal（测试里禁止 float 字面量）。"""
    return Decimal(value)


def raw_bar(
    *,
    open_: str = "10",
    high: str = "10.5",
    low: str = "9.5",
    close: str = "10.2",
    volume: str = "1000000",
    amount: str = "10200000",
    day: date = date(2026, 1, 5),
    adj_factor: str = "1",
    is_trading_day: bool = True,
    is_suspended: bool = False,
    instrument_type: InstrumentType = InstrumentType.EQUITY,
    symbol: str = "601186.SH",
) -> Bar:
    """构造一根 Bar（OHLC 显式给出，便于构造不自洽的非法样本）。"""
    return Bar(
        symbol=symbol,
        market="cn_a",
        date=day,
        open=d(open_),
        high=d(high),
        low=d(low),
        close=d(close),
        volume=d(volume),
        amount=d(amount),
        adj_factor=d(adj_factor),
        currency="CNY",
        source="test",
        as_of=FIXED_AS_OF,
        is_trading_day=is_trading_day,
        is_suspended=is_suspended,
        instrument_type=instrument_type,
    )


class TestTradable:
    def test_正常交易日可交易(self) -> None:
        assert raw_bar().tradable is True

    def test_非交易日不可交易(self) -> None:
        assert raw_bar(is_trading_day=False).tradable is False

    def test_停牌不可交易(self) -> None:
        """★ 停牌标记是 v2 新增字段（D-09）：v1 把停牌当正常数据继续跑。"""
        assert raw_bar(is_suspended=True).tradable is False

    @pytest.mark.parametrize("instrument_type", [InstrumentType.INDEX, InstrumentType.FUTURE])
    def test_不可交易品种不可交易(self, instrument_type: InstrumentType) -> None:
        assert raw_bar(instrument_type=instrument_type).tradable is False

    @pytest.mark.parametrize("instrument_type", [InstrumentType.EQUITY, InstrumentType.ETF])
    def test_可交易品种可交易(self, instrument_type: InstrumentType) -> None:
        assert raw_bar(instrument_type=instrument_type).tradable is True


class TestOhlcValidation:
    def test_停牌时不校验OHLC自洽(self) -> None:
        """★ 停牌/非交易日的 bar 通常是前收盘价平铺，强行校验会把正常数据判为异常。"""
        bar = raw_bar(open_="10", high="5", low="20", close="10", is_suspended=True)
        assert bar.high == d("5")

    def test_非交易日时不校验OHLC自洽(self) -> None:
        bar = raw_bar(open_="10", high="5", low="20", close="10", is_trading_day=False)
        assert bar.is_trading_day is False

    def test_high低于开盘收盘的最大值被拒(self) -> None:
        with pytest.raises(ValueError, match=r"high\(.*\) < max\(open, close\)"):
            raw_bar(open_="10", high="10.1", low="9.5", close="10.2")

    def test_low高于开盘收盘的最小值被拒(self) -> None:
        with pytest.raises(ValueError, match=r"low\(.*\) > min\(open, close\)"):
            raw_bar(open_="10", high="10.5", low="10.1", close="10.2")

    def test_自洽的OHLC通过(self) -> None:
        bar = raw_bar(open_="10", high="10.5", low="9.5", close="10.2")
        assert bar.high == d("10.5")

    @pytest.mark.parametrize("volume", ["-1", "-0.5"])
    def test_成交量不可为负(self, volume: str) -> None:
        with pytest.raises(ValueError):
            raw_bar(volume=volume)

    def test_成交额不可为负(self) -> None:
        with pytest.raises(ValueError):
            raw_bar(amount="-1")

    def test_复权因子必须为正(self) -> None:
        with pytest.raises(ValueError):
            raw_bar(adj_factor="0")


class TestPriceView:
    def build_view(self) -> PriceView:
        panel = BarPanel(make_bars(["10", "11", "12"]))
        return panel.to_view(AdjustType.RAW)

    def test_长度等于收盘价序列长度(self) -> None:
        assert len(self.build_view()) == 3

    def test_按下标取收盘价(self) -> None:
        view = self.build_view()
        assert view.close_at(0) == d("10")
        assert view.close_at(2) == d("12")

    def test_越界下标抛IndexError(self) -> None:
        """★ 不做任何兜底：静默返回 0 会让指标算出荒谬值。"""
        with pytest.raises(IndexError):
            self.build_view().close_at(3)

    def test_负下标可用(self) -> None:
        assert self.build_view().close_at(-1) == d("12")


class TestBarPanelValidation:
    @pytest.mark.regression
    def test_空序列被拒(self) -> None:
        """★ 空序列会让所有指标静默返回空，从而掩盖上游问题。"""
        with pytest.raises(ValueError, match="BarPanel 不接受空序列"):
            BarPanel([])

    def test_混合标的被拒(self) -> None:
        bars = make_bars(["10", "11"])
        mixed = [bars[0], bars[1].model_copy(update={"symbol": "000001.SZ"})]
        with pytest.raises(ValueError, match="BarPanel 只接受单一标的"):
            BarPanel(mixed)

    def test_日期重复被拒(self) -> None:
        bars = make_bars(["10", "11"], step_days=0)
        with pytest.raises(ValueError, match="Bar 日期必须严格递增且无重复"):
            BarPanel(bars)

    def test_日期倒序被拒(self) -> None:
        bars = make_bars(["10", "11", "12"])
        with pytest.raises(ValueError, match="Bar 日期必须严格递增且无重复"):
            BarPanel(list(reversed(bars)))


class TestBarPanelProperties:
    def build_panel(self) -> BarPanel:
        return BarPanel(make_bars(["10", "11", "12"]))

    def test_symbol取首根(self) -> None:
        assert self.build_panel().symbol == "601186.SH"

    def test_market取首根(self) -> None:
        assert self.build_panel().market == "cn_a"

    def test_currency取首根(self) -> None:
        assert self.build_panel().currency == "CNY"

    def test_长度与底层bars一致(self) -> None:
        panel = self.build_panel()
        assert len(panel) == 3
        assert len(panel.bars) == 3

    def test_dates序列(self) -> None:
        panel = self.build_panel()
        assert panel.dates == tuple(bar.date for bar in panel.bars)


class TestToView:
    """三视图换算的数学部分有 golden 测试，这里只验组装与口径锚定。"""

    def build_panel(self) -> BarPanel:
        """10 送 10 除权：close 20 → 10，adj_factor 1 → 2。"""
        return BarPanel(make_bars(["20", "10"], adj_factors=["1", "2"]))

    def test_RAW视图等于原始价(self) -> None:
        view = self.build_panel().to_view(AdjustType.RAW)
        assert view.close == (d("20"), d("10"))
        assert view.adjust is AdjustType.RAW

    def test_后复权消除除权跳空(self) -> None:
        view = self.build_panel().to_view(AdjustType.BACKWARD)
        assert view.close == (d("20"), d("20"))

    def test_前复权锚定最新真实价(self) -> None:
        """★ FORWARD 末日价格必须等于真实最新价，否则前端显示的现价是假的。

        k = [1/2, 2/2] → close = [10, 10]：除权跳空被抹平，且末日仍是真实价 10。
        """
        view = self.build_panel().to_view(AdjustType.FORWARD)
        assert view.close == (d("10"), d("10"))
        assert view.close[-1] == d("10")

    def test_视图携带标的与币种(self) -> None:
        view = self.build_panel().to_view(AdjustType.FORWARD)
        assert view.symbol == "601186.SH"
        assert view.market == "cn_a"
        assert view.currency == "CNY"
        assert len(view.dates) == 2

    def test_成交量与成交额同步换算(self) -> None:
        view = self.build_panel().to_view(AdjustType.BACKWARD)
        assert view.volume == (d("1000000"), d("500000"))
        assert view.amount == (d("20000000"), d("20000000"))


class TestAsSafeSeries:
    """★ 引擎唯一交给策略的数据形态（S-07 未来函数守卫）。"""

    def test_可见长度为last_valid_index加一(self) -> None:
        panel = BarPanel(make_bars(["10", "11", "12", "13"]))
        series = panel.as_safe_series(1)
        assert len(series) == 2

    def test_可见最后一根即传入下标(self) -> None:
        panel = BarPanel(make_bars(["10", "11", "12", "13"]))
        series = panel.as_safe_series(1)
        assert series.last.close == d("11")

    @pytest.mark.regression
    def test_越过可见边界即抛未来函数(self) -> None:
        """调用方应传 `i - 1`：信号用 `bar[i-1]` 收盘、成交在 `bar[i]` 收盘。"""
        panel = BarPanel(make_bars(["10", "11", "12", "13"]))
        series = panel.as_safe_series(1)
        with pytest.raises(LookaheadViolationError):
            _ = series[2]

    def test_下标零表示一根都不可见(self) -> None:
        panel = BarPanel(make_bars(["10", "11"]))
        series = panel.as_safe_series(-1)
        assert len(series) == 0
