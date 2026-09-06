"""AkshareCnAdapter 单元测试（FakeFetcher 注入，零网络）。

★ 测试策略：适配器职责是**符号归一化、Bar 组装、legacy 标记、错误放大**，
全是纯逻辑 —— 用 FakeFetcher 覆盖；新浪通道真实行为由部署探活
（`qv2 ops probe-sources`）验证，不进单测。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from quant_v2.adapters.market_data.akshare_cn import (
    AkshareCnAdapter,
    from_sina_symbol,
    to_sina_symbol,
)
from quant_v2.domain.errors import SourceUnavailableError
from quant_v2.domain.models.bar import AdjustType
from quant_v2.domain.ports.market_data_port import BarRequest

pytestmark = pytest.mark.unit

DAY = date(2024, 6, 3)
NEXT = date(2024, 6, 4)
FIXED_AS_OF = datetime(2024, 6, 5, 0, 0, 0, tzinfo=UTC)


def _request(symbols: Sequence[str]) -> BarRequest:
    return BarRequest(
        symbols=tuple(symbols),
        market="cn_a",
        start=DAY,
        end=NEXT,
        adjust=AdjustType.RAW,
    )


def _row(
    day: str = "2024-06-03",
    *,
    open_: Any = "10.0",
    high: Any = "11.0",
    low: Any = "9.5",
    close: Any = "10.5",
    volume: Any = "1000",
    amount: Any = "10500",
) -> dict[str, Any]:
    return {
        "date": day,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
    }


class FakeFetcher:
    """按新浪代码返回预设行；可注入异常。"""

    def __init__(
        self,
        rows_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._rows = rows_by_symbol or {}
        self._error = error
        self.calls: list[tuple[str, date, date]] = []
        self.call_times: list[float] = []

    def __call__(self, symbol: str, start: date, end: date) -> Sequence[dict[str, Any]]:
        self.call_times.append(time.monotonic())
        self.calls.append((symbol, start, end))
        if self._error is not None:
            raise self._error
        return list(self._rows.get(symbol, []))


# ============================================================
# 符号转换
# ============================================================


def test_符号转换_往返() -> None:
    assert to_sina_symbol("600000.SH") == "sh600000"
    assert to_sina_symbol("000001.SZ") == "sz000001"
    assert from_sina_symbol("sh600000") == "600000.SH"
    assert from_sina_symbol("sz000001") == "000001.SZ"


@pytest.mark.parametrize("bad", ["600000.BJ", "600000", ".SH", "830001.BJ"])
def test_符号转换_不支持的市场_抛错(bad: str) -> None:
    with pytest.raises(ValueError, match=r"只支持 \.SH / \.SZ"):
        to_sina_symbol(bad)


# ============================================================
# fetch_bars
# ============================================================


def test_fetch_bars_组装Bar_原始价与legacy标记() -> None:
    """★ 端口契约：缺因子的源必须用 source=*_legacy 自我暴露。"""
    fetcher = FakeFetcher({"sh600000": [_row()]})
    adapter = AkshareCnAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    (bar,) = adapter.fetch_bars(_request(["600000.SH"]))
    assert bar.symbol == "600000.SH"
    assert bar.close == Decimal("10.5")
    assert bar.open == Decimal("10.0")
    assert bar.adj_factor == Decimal("1")  # 占位（新浪通道无因子）
    assert bar.source == "akshare_legacy"
    assert bar.currency == "CNY"
    assert bar.is_suspended is False
    assert bar.is_trading_day is True
    assert bar.as_of == FIXED_AS_OF


def test_fetch_bars_数值可以是float() -> None:
    """pandas to_dict 给 float；适配器必须容忍（经 str 转 Decimal）。"""
    fetcher = FakeFetcher({"sh600000": [_row(open_=10.1, close=10.55)]})
    adapter = AkshareCnAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    (bar,) = adapter.fetch_bars(_request(["600000.SH"]))
    assert bar.open == Decimal("10.1")
    assert bar.close == Decimal("10.55")


def test_fetch_bars_空volume和amount_按零处理() -> None:
    fetcher = FakeFetcher({"sh600000": [_row(volume=None, amount="")]})
    adapter = AkshareCnAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    (bar,) = adapter.fetch_bars(_request(["600000.SH"]))
    assert bar.volume == Decimal("0")
    assert bar.amount == Decimal("0")


def test_fetch_bars_价格缺失_抛错禁止兜底() -> None:
    fetcher = FakeFetcher({"sh600000": [_row(close=None)]})
    adapter = AkshareCnAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    with pytest.raises(ValueError, match=r"close@.* 为 None"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_非法价格_抛错() -> None:
    fetcher = FakeFetcher({"sh600000": [_row(close="abc")]})
    adapter = AkshareCnAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    with pytest.raises(ValueError, match=r"不是合法数值"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_网络异常_归一化为SourceUnavailableError() -> None:
    fetcher = FakeFetcher(error=RuntimeError("connection reset"))
    adapter = AkshareCnAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    with pytest.raises(SourceUnavailableError, match="新浪通道查询失败"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_非cn_a_拒绝() -> None:
    adapter = AkshareCnAdapter(fetcher=FakeFetcher(), as_of=FIXED_AS_OF)
    req = BarRequest(
        symbols=("0700.HK",),
        market="hk",
        start=DAY,
        end=NEXT,
        adjust=AdjustType.RAW,
    )
    with pytest.raises(ValueError, match="只服务 cn_a"):
        adapter.fetch_bars(req)


def test_fetch_bars_多标的_逐个查询并带限流间隔() -> None:
    """pacing = 60/120 = 0.5s：第二个标的前必须等一个限流间隔（M-17）。"""
    fetcher = FakeFetcher({"sh600000": [_row()], "sz000001": [_row("2024-06-03")]})
    adapter = AkshareCnAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    bars = adapter.fetch_bars(_request(["600000.SH", "000001.SZ"]))
    assert len(bars) == 2
    assert [c[0] for c in fetcher.calls] == ["sh600000", "sz000001"]
    gap = fetcher.call_times[1] - fetcher.call_times[0]
    assert gap >= 0.4  # 限流间隔真实生效（0.5s - 容差）


def test_fetch_bars_限流间隔常量派生() -> None:
    adapter = AkshareCnAdapter(fetcher=FakeFetcher(), as_of=FIXED_AS_OF)
    assert adapter._pacing_s() == pytest.approx(0.5)  # 60 / 120


# ============================================================
# 日期解析
# ============================================================


def test_fetch_bars_日期兼容datetime对象() -> None:
    fetcher = FakeFetcher({"sh600000": [_row(day=datetime(2024, 6, 3, 0, 0, 0).isoformat())]})
    adapter = AkshareCnAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    (bar,) = adapter.fetch_bars(_request(["600000.SH"]))
    assert bar.date == DAY


def test_fetch_bars_缺date列_抛错() -> None:
    row = _row()
    del row["date"]
    fetcher = FakeFetcher({"sh600000": [row]})
    adapter = AkshareCnAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    with pytest.raises(ValueError, match="缺少 date 列"):
        adapter.fetch_bars(_request(["600000.SH"]))


# ============================================================
# healthcheck
# ============================================================


def test_healthcheck_成功() -> None:
    fetcher = FakeFetcher({"sh600000": [_row()]})
    adapter = AkshareCnAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    health = adapter.healthcheck()
    assert health.reachable is True
    assert health.source_id == "akshare"


def test_healthcheck_网络异常_不抛返回不可达() -> None:
    adapter = AkshareCnAdapter(fetcher=FakeFetcher(error=TimeoutError("boom")), as_of=FIXED_AS_OF)
    health = adapter.healthcheck()
    assert health.reachable is False
    assert "TimeoutError" in health.detail


def test_healthcheck_空行_视为不可达() -> None:
    """0 行 = 通道响应异常（浦发银行不可能一周无行情），不是"健康"。"""
    adapter = AkshareCnAdapter(fetcher=FakeFetcher(), as_of=FIXED_AS_OF)
    health = adapter.healthcheck()
    assert health.reachable is False
    assert "0 行" in health.detail
