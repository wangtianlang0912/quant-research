"""SafeSeries —— 未来函数守卫。

★ 这是从 v1 继承并提升为引擎级不变量的正确资产：
v1 的 `backtest_runner.py:90` 写 `historical = bars[:i]`（T+1 对齐，无未来函数），
但**没有任何机制保护它** —— 谁在策略里写 `bars[-1]` 就悄悄拿到未来数据。

v2 的守卫必须做到：越界访问**必抛** `LookaheadViolationError`，
且该异常不得被引擎吞掉（由 `ARCH012` 静态扫描强制）。
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.conftest import make_bars

from quant_v2.domain.errors import InsufficientHistoryError, LookaheadViolationError
from quant_v2.domain.guard.safe_series import SafeSeries
from quant_v2.domain.models.bar import Bar

pytestmark = pytest.mark.unit


def build(count: int = 10) -> list[Bar]:
    return make_bars([str(100 + i) for i in range(count)])


class TestVisibility:
    def test_可见长度等于last_valid_index加一(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=4)
        assert len(series) == 5
        assert series.last_valid_index == 4

    def test_下标与底层bars一致(self) -> None:
        bars = build(10)
        series = SafeSeries(symbol="X", bars=bars, last_valid_index=9)
        assert series[3] is bars[3]

    def test_负一下标即可见最后一根(self) -> None:
        """★ v1 的正确口径：`safe[-1]` 就是 `bar[i-1]`（决策时点看到的最后一根）。"""
        bars = build(10)
        series = SafeSeries(symbol="X", bars=bars, last_valid_index=4)
        assert series[-1] is bars[4]

    def test_last属性返回可见最后一根(self) -> None:
        bars = build(10)
        series = SafeSeries(symbol="X", bars=bars, last_valid_index=6)
        assert series.last is bars[6]

    def test_as_of_date为可见最后一根的日期(self) -> None:
        bars = build(10)
        series = SafeSeries(symbol="X", bars=bars, last_valid_index=3)
        assert series.as_of_date == bars[3].date

    def test_last_valid_index越界报错(self) -> None:
        with pytest.raises(ValueError, match="越界"):
            SafeSeries(symbol="X", bars=build(5), last_valid_index=5)


class TestLookaheadGuard:
    """★ 核心：任何触及未来的访问都必须抛异常，一次都不能漏。"""

    def test_正向越界抛未来函数异常(self) -> None:
        series = SafeSeries(symbol="601186.SH", bars=build(10), last_valid_index=4)
        with pytest.raises(LookaheadViolationError) as excinfo:
            _ = series[5]
        # 报错信息必须带 symbol 与可见边界，否则线上排查时不知道是哪只票
        assert "601186.SH" in str(excinfo.value)
        assert "未来函数" in str(excinfo.value)

    def test_负向越界抛IndexError(self) -> None:
        """负向越界是"要更早的数据"，属于历史不足，不是未来函数。"""
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=4)
        with pytest.raises(IndexError):
            _ = series[-6]

    def test_切片显式请求未来区间抛异常(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=4)
        with pytest.raises(LookaheadViolationError):
            _ = series[0:8]

    def test_切片在可见范围内正常截断(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=4)
        assert len(series[0:3]) == 3

    def test_取序列超过可见长度报历史不足(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=4)
        with pytest.raises(InsufficientHistoryError):
            series.close(10)

    def test_取序列在可见长度内正常返回(self) -> None:
        bars = build(10)
        series = SafeSeries(symbol="X", bars=bars, last_valid_index=4)
        assert series.close(3) == [bars[2].close, bars[3].close, bars[4].close]

    def test_close默认返回全部可见值(self) -> None:
        bars = build(10)
        series = SafeSeries(symbol="X", bars=bars, last_valid_index=2)
        assert series.close() == [bars[0].close, bars[1].close, bars[2].close]

    def test_window请求未来终点抛异常(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=4)
        with pytest.raises(LookaheadViolationError):
            series.window(3, end_inclusive=7)

    def test_窗口长度超过可见长度报历史不足(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=2)
        with pytest.raises(InsufficientHistoryError):
            series.window(10)

    def test_window正常返回裁剪后的新视图(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=6)
        window = series.window(3)
        assert len(window) == 3
        assert window.last is series[-1]


class TestEmptySeries:
    def test_空视图长度为零(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=-1)
        assert len(series) == 0

    def test_空视图访问last报历史不足(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=-1)
        with pytest.raises(InsufficientHistoryError):
            _ = series.last

    def test_空视图访问as_of报历史不足(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=-1)
        with pytest.raises(InsufficientHistoryError):
            _ = series.as_of_date

    def test_空视图访问越界仍是未来函数(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=-1)
        with pytest.raises(LookaheadViolationError):
            _ = series[0]


class TestFieldWhitelist:
    def test_白名单外的字段名报错(self) -> None:
        """★ 允许任意 getattr 会把 SafeSeries 变成绕过守卫的后门。"""
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=9)
        with pytest.raises(ValueError, match="不允许取字段"):
            series.field("__class__")

    @pytest.mark.parametrize(
        "name", ["open", "high", "low", "close", "volume", "amount", "adj_factor"]
    )
    def test_白名单内字段均可取(self, name: str) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=9)
        assert len(series.field(name, 5)) == 5


class TestDerivedViews:
    def test_to_panel只包含可见部分(self) -> None:
        bars = build(10)
        series = SafeSeries(symbol="X", bars=bars, last_valid_index=4)
        panel = series.to_panel()
        assert len(panel) == 5
        assert panel.dates[-1] == bars[4].date

    def test_空视图无法构造panel(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=-1)
        with pytest.raises(InsufficientHistoryError):
            series.to_panel()

    def test_dates返回可见日期(self) -> None:
        bars = build(10)
        series = SafeSeries(symbol="X", bars=bars, last_valid_index=2)
        assert series.dates == [bars[0].date, bars[1].date, bars[2].date]

    def test_repr含as_of便于日志定位(self) -> None:
        series = SafeSeries(symbol="X", bars=build(10), last_valid_index=2)
        text = repr(series)
        assert "3/10" in text, f"repr 应体现可见/总量：{text}"
        assert isinstance(series.as_of_date, date)
