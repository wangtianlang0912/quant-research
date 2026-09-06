"""TencentAdapter 单元测试（FakeFetcher 注入，零网络）。

★ 最重要的回归：腾讯 kline 列序是 `[date, open, close, high, low, volume]`
（close 在第 2 列、high 在第 3 列），与常见 OHLC 顺序**不同** ——
列序取错不会报错，只会把 close 和 high 静默互换，是最典型的脏数据。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from quant_v2.adapters.market_data.tencent_fallback import (
    TencentAdapter,
    from_tencent_symbol,
    to_tencent_symbol,
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


def _kline_payload(
    tx_symbol: str,
    rows: list[list[str]],
    *,
    key: str = "day",
) -> dict[str, Any]:
    return {"code": 0, "data": {tx_symbol: {key: rows}}}


def _row(
    day: str = "2024-06-03",
    *,
    open_: str = "10.0",
    close: str = "10.5",
    high: str = "11.0",
    low: str = "9.5",
    volume: str = "1000",
) -> list[str]:
    return [day, open_, close, high, low, volume]


class FakeFetcher:
    """按 (symbol, start, end, max_count) 返回预设 JSON；可注入异常。"""

    def __init__(
        self,
        payloads: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._payloads = payloads or {}
        self._error = error
        self.calls: list[tuple[str, date, date, int]] = []

    def __call__(self, symbol: str, start: date, end: date, max_count: int) -> dict[str, Any]:
        self.calls.append((symbol, start, end, max_count))
        if self._error is not None:
            raise self._error
        return self._payloads[symbol]


# ============================================================
# 符号转换
# ============================================================


def test_符号转换_往返() -> None:
    assert to_tencent_symbol("600000.SH") == "sh600000"
    assert to_tencent_symbol("000001.SZ") == "sz000001"
    assert from_tencent_symbol("sh600000") == "600000.SH"


@pytest.mark.parametrize("bad", ["600000.BJ", "600000", ".SH"])
def test_to_tencent_symbol_非法格式_抛错(bad: str) -> None:
    with pytest.raises(ValueError, match=r"只支持 \.SH / \.SZ"):
        to_tencent_symbol(bad)


@pytest.mark.parametrize("bad", ["sh60000", "hk00700", "sh6000000"])
def test_from_tencent_symbol_非法格式_抛错(bad: str) -> None:
    with pytest.raises(ValueError, match=r"shXXXXXX / szXXXXXX"):
        from_tencent_symbol(bad)


# ============================================================
# fetch_bars
# ============================================================


def test_fetch_bars_列序_close在high之前() -> None:
    """★ 回归：列序 [date, open, close, high, low, volume]，取错列 = 脏数据。"""
    fetcher = FakeFetcher({"sh600000": _kline_payload("sh600000", [_row()])})
    adapter = TencentAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    (bar,) = adapter.fetch_bars(_request(["600000.SH"]))
    assert bar.close == Decimal("10.5")  # 第 2 列
    assert bar.high == Decimal("11.0")  # 第 3 列
    assert bar.open == Decimal("10.0")
    assert bar.low == Decimal("9.5")
    assert bar.volume == Decimal("1000")


def test_fetch_bars_无因子无金额_占位与legacy标记() -> None:
    fetcher = FakeFetcher({"sh600000": _kline_payload("sh600000", [_row()])})
    adapter = TencentAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    (bar,) = adapter.fetch_bars(_request(["600000.SH"]))
    assert bar.adj_factor == Decimal("1")
    assert bar.amount == Decimal("0")  # 腾讯无成交额列：0 占位（仅交叉验证用）
    assert bar.source == "tencent_legacy"


def test_fetch_bars_行不足六列_抛错() -> None:
    fetcher = FakeFetcher(
        {"sh600000": _kline_payload("sh600000", [["2024-06-03", "10.0", "10.5"]])}
    )
    adapter = TencentAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    with pytest.raises(ValueError, match="禁止猜测缺失列"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_缺data节点_抛SourceUnavailableError() -> None:
    fetcher = FakeFetcher({"sh600000": {"code": 0}})
    adapter = TencentAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    with pytest.raises(SourceUnavailableError, match="缺少 data 节点"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_缺股票节点_抛SourceUnavailableError() -> None:
    fetcher = FakeFetcher({"sh600000": {"code": 0, "data": {"sz000001": {}}}})
    adapter = TencentAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    with pytest.raises(SourceUnavailableError, match="缺少 sh600000 节点"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_缺day数组_抛SourceUnavailableError() -> None:
    fetcher = FakeFetcher({"sh600000": {"code": 0, "data": {"sh600000": {"qt": []}}}})
    adapter = TencentAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    with pytest.raises(SourceUnavailableError, match="缺少 day 行数组"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_qfqday键名变体_同样解析() -> None:
    fetcher = FakeFetcher({"sh600000": _kline_payload("sh600000", [_row()], key="qfqday")})
    adapter = TencentAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    (bar,) = adapter.fetch_bars(_request(["600000.SH"]))
    assert bar.close == Decimal("10.5")


def test_fetch_bars_网络异常_归一化为SourceUnavailableError() -> None:
    fetcher = FakeFetcher(error=TimeoutError("connect timeout"))
    adapter = TencentAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    with pytest.raises(SourceUnavailableError, match="腾讯通道查询失败"):
        adapter.fetch_bars(_request(["600000.SH"]))


def test_fetch_bars_窗口超过max_count_分段抓取() -> None:
    """max_count 根截尾是静默丢头部 —— 必须显式分段，从末日次日续抓。"""
    batch1 = [_row("2024-06-0" + str(i)) for i in (3, 4)]  # 2 行 = max_count → 还有剩余
    batch2 = [_row("2024-06-0" + str(i)) for i in (5, 6)]

    class SeqFetcher:
        """按调用序返回预设 JSON。"""

        def __init__(self) -> None:
            self.batches = [
                _kline_payload("sh600000", batch1),
                _kline_payload("sh600000", batch2),
            ]
            self.calls: list[tuple[str, date, date, int]] = []

        def __call__(self, symbol: str, start: date, end: date, max_count: int) -> dict[str, Any]:
            self.calls.append((symbol, start, end, max_count))
            return self.batches[min(len(self.calls) - 1, 1)]

    seq = SeqFetcher()
    adapter = TencentAdapter(fetcher=seq, as_of=FIXED_AS_OF, max_count=2)
    req = BarRequest(
        symbols=("600000.SH",),
        market="cn_a",
        start=DAY,
        end=date(2024, 6, 6),
        adjust=AdjustType.RAW,
    )
    bars = adapter.fetch_bars(req)
    assert [b.date.isoformat() for b in bars] == [
        "2024-06-03",
        "2024-06-04",
        "2024-06-05",
        "2024-06-06",
    ]
    # 第二段的起点 = 第一段最后一行的次日
    assert seq.calls[0][1] == DAY
    assert seq.calls[1][1] == date(2024, 6, 5)


def test_fetch_bars_非cn_a_拒绝() -> None:
    adapter = TencentAdapter(fetcher=FakeFetcher(), as_of=FIXED_AS_OF)
    req = BarRequest(
        symbols=("0700.HK",),
        market="hk",
        start=DAY,
        end=NEXT,
        adjust=AdjustType.RAW,
    )
    with pytest.raises(ValueError, match="只服务 cn_a"):
        adapter.fetch_bars(req)


# ============================================================
# healthcheck
# ============================================================


def test_healthcheck_成功() -> None:
    fetcher = FakeFetcher({"sh600000": _kline_payload("sh600000", [_row()])})
    adapter = TencentAdapter(fetcher=fetcher, as_of=FIXED_AS_OF)
    health = adapter.healthcheck()
    assert health.reachable is True
    assert health.source_id == "tencent"


def test_healthcheck_异常_不抛返回不可达() -> None:
    adapter = TencentAdapter(fetcher=FakeFetcher(error=OSError("dns")), as_of=FIXED_AS_OF)
    health = adapter.healthcheck()
    assert health.reachable is False
    assert "OSError" in health.detail


def test_healthcheck_空行_视为不可达() -> None:
    adapter = TencentAdapter(
        fetcher=FakeFetcher({"sh600000": _kline_payload("sh600000", [])}), as_of=FIXED_AS_OF
    )
    health = adapter.healthcheck()
    assert health.reachable is False
