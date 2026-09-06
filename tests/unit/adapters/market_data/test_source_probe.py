"""SourceProbe 单元测试（假源 + 假 TCP 连接，零网络）。"""

from __future__ import annotations

from typing import Any

import pytest

from quant_v2.adapters.market_data.capabilities import (
    AKSHARE_CAPABILITIES,
    BAOSTOCK_CAPABILITIES,
    TENCENT_CAPABILITIES,
)
from quant_v2.adapters.market_data.source_probe import (
    ProbeEndpoint,
    SourceProbe,
    assert_minimum_viable,
    probe_endpoint_tcp,
)
from quant_v2.domain.errors import SourceUnavailableError

pytestmark = pytest.mark.unit


class FakeHealth:
    """healthcheck 返回值的替身（reachable / detail 属性）。"""

    def __init__(self, reachable: bool, detail: str = "") -> None:
        self.reachable = reachable
        self.detail = detail


class FakeSource:
    """可编程探活源：healthcheck 按 fail_times 前 N 次失败。"""

    def __init__(
        self,
        source_id: str,
        capabilities: Any,
        *,
        fail_times: int = 0,
        detail: str = "connection refused",
    ) -> None:
        self.source_id = source_id
        self.capabilities = capabilities
        self._fail_times = fail_times
        self._detail = detail
        self.healthcheck_calls = 0

    def healthcheck(self) -> FakeHealth:
        self.healthcheck_calls += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            return FakeHealth(False, self._detail)
        return FakeHealth(True)


def _ok_tcp(host: str, port: int, timeout_s: float) -> None:
    """永远建连成功的假 TCP。"""


def _fail_tcp(host: str, port: int, timeout_s: float) -> None:
    """永远失败的假 TCP（模拟 M-6 不可达端点）。"""
    raise OSError("connection refused")


# ============================================================
# 端点级 TCP 探测
# ============================================================


def test_probe_endpoint_tcp_可达() -> None:
    endpoint = ProbeEndpoint(source_id="tencent", host="web.ifzq.gtimg.cn", port=443)
    ok, detail = probe_endpoint_tcp(endpoint, attempts=2, tcp_connect=_ok_tcp)
    assert ok is True
    assert detail == ""


def test_probe_endpoint_tcp_不可达_带明细() -> None:
    endpoint = ProbeEndpoint(source_id="akshare", host="finance.sina.com.cn", port=443)
    ok, detail = probe_endpoint_tcp(endpoint, attempts=2, tcp_connect=_fail_tcp)
    assert ok is False
    assert "OSError" in detail
    assert "connection refused" in detail


# ============================================================
# probe_all
# ============================================================


def test_probe_all_全部可达() -> None:
    sources = [
        FakeSource("baostock", BAOSTOCK_CAPABILITIES),
        FakeSource("akshare", AKSHARE_CAPABILITIES),
        FakeSource("tencent", TENCENT_CAPABILITIES),
    ]
    probe = SourceProbe(sources, attempts=2, tcp_connect=_ok_tcp)
    report = probe.probe_all()
    assert len(report.results) == 3
    assert all(r.reachable for r in report.results)
    assert all(r.ok_attempts == 2 for r in report.results)


def test_probe_all_语义探活重试后成功() -> None:
    """前 2 次失败第 3 次成功 → reachable=True（重试的意义）。"""
    source = FakeSource("baostock", BAOSTOCK_CAPABILITIES, fail_times=2)
    probe = SourceProbe([source], attempts=3, tcp_connect=_ok_tcp)
    report = probe.probe_all()
    (result,) = report.results
    assert result.reachable is True
    assert result.ok_attempts == 1
    assert source.healthcheck_calls == 3


def test_probe_all_全部失败_不可达带明细() -> None:
    source = FakeSource("akshare", AKSHARE_CAPABILITIES, fail_times=99)
    probe = SourceProbe([source], attempts=3, tcp_connect=_ok_tcp)
    (result,) = probe.probe_all().results
    assert result.reachable is False
    assert result.ok_attempts == 0
    assert "connection refused" in result.detail


def test_probe_all_端点详情登记() -> None:
    source = FakeSource("tencent", TENCENT_CAPABILITIES)
    endpoints = {"tencent": (ProbeEndpoint("tencent", "web.ifzq.gtimg.cn", 443),)}
    probe = SourceProbe([source], endpoints=endpoints, attempts=1, tcp_connect=_fail_tcp)
    (result,) = probe.probe_all().results
    # 语义探活成功（假源健康），但 TCP 端点失败 → 详情里可见 FAIL
    assert result.reachable is True
    assert any("web.ifzq.gtimg.cn:443=FAIL" in line for line in result.endpoints)
    assert any("connection refused" in line for line in result.endpoints)


def test_probe_all_报告按源取结果() -> None:
    sources = [
        FakeSource("baostock", BAOSTOCK_CAPABILITIES),
        FakeSource("tencent", TENCENT_CAPABILITIES),
    ]
    report = SourceProbe(sources, attempts=1, tcp_connect=_ok_tcp).probe_all()
    assert report.result_for("tencent") is not None
    assert report.result_for("tencent").source_id == "tencent"  # type: ignore[union-attr]
    assert report.result_for("nope") is None


# ============================================================
# 最低可用性断言（拒绝启动）
# ============================================================


def _report_for(sources: list[FakeSource]) -> Any:
    return SourceProbe(sources, attempts=1, tcp_connect=_ok_tcp).probe_all()


def test_最低可用_日线与因子齐备_通过() -> None:
    report = _report_for(
        [
            FakeSource("baostock", BAOSTOCK_CAPABILITIES),
            FakeSource("akshare", AKSHARE_CAPABILITIES),
        ]
    )
    assert report.viable is True
    assert_minimum_viable(report)  # 不抛


def test_最低可用_无任何源能给日线_拒绝启动() -> None:
    report = _report_for([FakeSource("tencent", TENCENT_CAPABILITIES, fail_times=99)])
    assert report.viable is False
    with pytest.raises(SourceUnavailableError, match="没有任何可达数据源能提供日线"):
        assert_minimum_viable(report)


def test_最低可用_只有无因子源_拒绝启动() -> None:
    """日线有（akshare）但因子无 —— 除权日全是假跳空，宁可停下。"""
    report = _report_for([FakeSource("akshare", AKSHARE_CAPABILITIES)])
    with pytest.raises(SourceUnavailableError, match="没有任何可达数据源能提供复权因子"):
        assert_minimum_viable(report)


def test_最低可用_主源挂了但有备源_仍可行() -> None:
    """baostock 不可达但 akshare 在 → 日线可用；但因子缺 → 不可行（如实判定）。"""
    report = _report_for(
        [
            FakeSource("baostock", BAOSTOCK_CAPABILITIES, fail_times=99),
            FakeSource("akshare", AKSHARE_CAPABILITIES),
        ]
    )
    with pytest.raises(SourceUnavailableError, match="复权因子"):
        assert_minimum_viable(report)
