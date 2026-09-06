"""ResilientSource 单元测试（假源 + 告警记录器，零网络零子进程）。

★ 验收对应（T02.3）：主源人为置为不可用时，自动切备源且立刻发 P0 告警；
降级事件必须落告警（D-10 禁止静默）；跨源校验只比不复权价（M-2）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from quant_v2.adapters.market_data.capabilities import (
    AKSHARE_CAPABILITIES,
    BAOSTOCK_CAPABILITIES,
)
from quant_v2.adapters.market_data.resilient_source import ResilientSource
from quant_v2.domain.errors import SourceUnavailableError
from quant_v2.domain.models.bar import AdjustType, Bar
from quant_v2.domain.ports.market_data_port import BarRequest

pytestmark = pytest.mark.unit

DAY = date(2024, 6, 3)
FIXED_AS_OF = datetime(2024, 6, 5, 0, 0, 0, tzinfo=UTC)


def _request() -> BarRequest:
    return BarRequest(
        symbols=("600000.SH",),
        market="cn_a",
        start=DAY,
        end=DAY,
        adjust=AdjustType.RAW,
    )


def _bar(
    symbol: str = "600000.SH",
    *,
    day: date = DAY,
    close: str = "10.0",
    source: str = "test",
) -> Bar:
    close_dec = Decimal(close)
    return Bar(
        symbol=symbol,
        market="cn_a",
        date=day,
        open=close_dec,
        high=close_dec,
        low=close_dec,
        close=close_dec,
        volume=Decimal("100"),
        amount=Decimal("1000"),
        adj_factor=Decimal("1"),
        currency="CNY",
        source=source,
        as_of=FIXED_AS_OF,
    )


class FakeSource:
    """可编程源：可失败 N 次 / 永远失败 / 返回预设 bars。"""

    def __init__(
        self,
        source_id: str,
        capabilities: Any,
        *,
        fail_times: int = 0,
        bars: Sequence[Bar] | None = None,
        error_detail: str = "subprocess dead",
    ) -> None:
        self.source_id = source_id
        self.capabilities = capabilities
        self._fail_times = fail_times
        self._bars = list(bars or [])
        self._error_detail = error_detail
        self.fetch_calls = 0

    def fetch_bars(self, req: BarRequest) -> Sequence[Bar]:
        self.fetch_calls += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            raise SourceUnavailableError(f"{self.source_id}: {self._error_detail}")
        if self._bars or self.fetch_calls == 1:
            return list(self._bars)
        raise SourceUnavailableError(f"{self.source_id}: {self._error_detail}")


class AlertRecorder:
    """告警落点替身：记录 (level, source, message)。"""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, str]] = []

    def __call__(self, *, level: str, source: str, message: str, payload: str = "{}") -> None:
        self.records.append((level, source, message))

    def by_level(self, level: str) -> list[tuple[str, str, str]]:
        return [r for r in self.records if r[0] == level]


def _make(primary: FakeSource, *backups: FakeSource) -> tuple[ResilientSource, AlertRecorder]:
    alerts = AlertRecorder()
    source = ResilientSource([primary, *backups], alert_sink=alerts)
    return source, alerts


# ============================================================
# fetch_with_fallback
# ============================================================


def test_主源正常_无告警() -> None:
    primary = FakeSource("baostock", BAOSTOCK_CAPABILITIES, bars=[_bar()])
    resilient, alerts = _make(primary)
    bars = resilient.fetch_with_fallback(_request())
    assert len(bars) == 1
    assert alerts.records == []
    assert resilient.degraded is False


def test_主源失败_切备源且立刻P0告警() -> None:
    """★ T02.3 验收：自动切备源 + 立刻 P0（不是切换成功后才补日志）。"""
    primary = FakeSource("baostock", BAOSTOCK_CAPABILITIES, fail_times=1)
    backup = FakeSource("akshare", AKSHARE_CAPABILITIES, bars=[_bar(source="akshare_legacy")])
    resilient, alerts = _make(primary, backup)
    bars = resilient.fetch_with_fallback(_request())
    assert [b.source for b in bars] == ["akshare_legacy"]
    p0 = alerts.by_level("P0")
    assert len(p0) == 1
    assert p0[0][1] == "market_data.baostock"
    assert "不可用" in p0[0][2]
    assert resilient.degraded is True


def test_主源失败_无因子备源_补一条P1提醒legacy() -> None:
    primary = FakeSource("baostock", BAOSTOCK_CAPABILITIES, fail_times=1)
    backup = FakeSource("akshare", AKSHARE_CAPABILITIES, bars=[_bar()])
    resilient, alerts = _make(primary, backup)
    resilient.fetch_with_fallback(_request())
    p1 = alerts.by_level("P1")
    assert len(p1) == 1
    assert "无因子" in p1[0][2]
    assert "akshare" in p1[0][2]


def test_主源恢复_INFO留痕且退出降级() -> None:
    """D-10：恢复也要留痕；主源豁免永久拉黑（每次调用一次重试）。"""
    primary = FakeSource("baostock", BAOSTOCK_CAPABILITIES, fail_times=1, bars=[_bar()])
    backup = FakeSource("akshare", AKSHARE_CAPABILITIES, bars=[_bar(source="akshare_legacy")])
    resilient, alerts = _make(primary, backup)

    first = resilient.fetch_with_fallback(_request())  # 主源挂 → 备源
    assert [b.source for b in first] == ["akshare_legacy"]
    second = resilient.fetch_with_fallback(_request())  # 主源重试成功
    assert [b.source for b in second] == ["test"]

    infos = alerts.by_level("INFO")
    assert len(infos) == 1
    assert "主源已恢复" in infos[0][2]
    assert resilient.degraded is False
    assert "baostock" not in resilient.blacklisted


def test_P0防轰炸_同一故障只发一条() -> None:
    """主源持续挂：每次调用重试失败，但 P0 只在降级瞬间发一条。"""
    primary = FakeSource("baostock", BAOSTOCK_CAPABILITIES, fail_times=99)
    backup = FakeSource("akshare", AKSHARE_CAPABILITIES, bars=[_bar()])
    resilient, alerts = _make(primary, backup)
    for _ in range(3):
        resilient.fetch_with_fallback(_request())
    assert len(alerts.by_level("P0")) == 1


def test_主源再故障_新的一次降级_新P0() -> None:
    primary = FakeSource("baostock", BAOSTOCK_CAPABILITIES, fail_times=1, bars=[_bar()])
    backup = FakeSource("akshare", AKSHARE_CAPABILITIES, bars=[_bar()])
    resilient, alerts = _make(primary, backup)

    resilient.fetch_with_fallback(_request())  # 主源挂 → 备源（P0 #1）
    resilient.fetch_with_fallback(_request())  # 主源恢复（INFO）
    primary._fail_times = 1  # 主源再次挂
    resilient.fetch_with_fallback(_request())  # 又降级（P0 #2）

    assert len(alerts.by_level("P0")) == 2


def test_备源失败_永久拉黑不再重试() -> None:
    """备源与主源不同：失败即拉黑到底，避免级联重试浪费超时（M-14）。"""
    primary = FakeSource("baostock", BAOSTOCK_CAPABILITIES, fail_times=99)
    backup = FakeSource("akshare", AKSHARE_CAPABILITIES, fail_times=99)
    resilient, _alerts = _make(primary, backup)

    with pytest.raises(SourceUnavailableError, match="全部数据源不可用"):
        resilient.fetch_with_fallback(_request())
    assert backup.fetch_calls == 1
    assert "akshare" in resilient.blacklisted

    with pytest.raises(SourceUnavailableError):
        resilient.fetch_with_fallback(_request())
    assert backup.fetch_calls == 1  # 第二次调用：备源被跳过，不再浪费超时


def test_全部源不可用_抛SourceUnavailableError() -> None:
    primary = FakeSource("baostock", BAOSTOCK_CAPABILITIES, fail_times=99)
    resilient, alerts = _make(primary)
    with pytest.raises(SourceUnavailableError, match="全部数据源不可用"):
        resilient.fetch_with_fallback(_request())
    assert len(alerts.by_level("P0")) == 1  # 降级告警仍然发了（不是静默失败）


def test_空源列表_构造即拒绝() -> None:
    with pytest.raises(ValueError, match="至少需要一个源"):
        ResilientSource([], alert_sink=AlertRecorder())


# ============================================================
# cross_validate（M-2：只比不复权价）
# ============================================================


def test_跨源校验_价格一致_无分歧() -> None:
    resilient, alerts = _make(FakeSource("baostock", BAOSTOCK_CAPABILITIES, bars=[_bar()]))
    divergences = resilient.cross_validate(
        [_bar(close="10.0")],
        [_bar(close="10.0", source="akshare_legacy")],
    )
    assert divergences == []
    assert alerts.by_level("P1") == []


def test_跨源校验_分歧超千分之一_记P1() -> None:
    resilient, alerts = _make(FakeSource("baostock", BAOSTOCK_CAPABILITIES, bars=[_bar()]))
    divergences = resilient.cross_validate(
        [_bar(close="10.0")],
        [_bar(close="10.05", source="akshare_legacy")],  # 0.5% 分歧
    )
    assert len(divergences) == 1
    assert divergences[0].rel_diff == Decimal("0.05") / Decimal("10.0")
    p1 = alerts.by_level("P1")
    assert len(p1) == 1
    assert "cross_validate" in p1[0][1]


def test_跨源校验_容差内_不告警() -> None:
    resilient, alerts = _make(FakeSource("baostock", BAOSTOCK_CAPABILITIES, bars=[_bar()]))
    divergences = resilient.cross_validate(
        [_bar(close="10.0")],
        [_bar(close="10.005", source="akshare_legacy")],  # 0.05% < 0.1%
    )
    assert divergences == []
    assert alerts.by_level("P1") == []


def test_跨源校验_单边缺席_不算分歧() -> None:
    """覆盖差异归质量门禁管；这里只比两边都有的 (symbol, date)。"""
    resilient, alerts = _make(FakeSource("baostock", BAOSTOCK_CAPABILITIES, bars=[_bar()]))
    divergences = resilient.cross_validate(
        [_bar(day=DAY), _bar(day=date(2024, 6, 4))],
        [_bar(day=DAY)],
    )
    assert divergences == []
    assert alerts.by_level("P1") == []


def test_跨源校验_零价行跳过() -> None:
    """close=0 是脏数据（质量门禁的活），跨源校验不除零。"""
    resilient, _alerts = _make(FakeSource("baostock", BAOSTOCK_CAPABILITIES, bars=[_bar()]))
    divergences = resilient.cross_validate(
        [_bar(close="0")],
        [_bar(close="10.0", source="akshare_legacy")],
    )
    assert divergences == []


def test_跨源校验_多标的分歧_告警取最大且只发一条() -> None:
    resilient, alerts = _make(FakeSource("baostock", BAOSTOCK_CAPABILITIES, bars=[_bar()]))
    divergences = resilient.cross_validate(
        [_bar(symbol="600000.SH", close="10.0"), _bar(symbol="000001.SZ", close="20.0")],
        [
            _bar(symbol="600000.SH", close="10.5", source="x"),  # 5% 分歧
            _bar(symbol="000001.SZ", close="20.1", source="x"),  # 0.5% 分歧
        ],
    )
    assert len(divergences) == 2
    # 列表按 (symbol, date) 排序：字典序 000001.SZ 在前
    assert divergences[0].symbol == "000001.SZ"
    # 告警里的"最大"必须是真的最大（600000.SH 的 5%），不是列表第一条
    p1 = alerts.by_level("P1")
    assert len(p1) == 1  # 一条汇总告警，不逐条轰炸
    assert "600000.SH" in p1[0][2]
