"""部署前数据源探活（§5.12 / M-6 硬约束 / T02.2b）。

## 为什么探活是一等操作

M-6 实测：本网络到东财 push2 系端点 TCP 建连全部失败 —— 这不是 akshare 的
缺陷，但**把不可达端点当默认通道**是架构缺陷。对策是部署清单第一步就探活：

1. `qv2 ops probe-sources`：对每个源的端点做 TCP 建连 + 一次最小语义请求
   （各 3 次、单次超时 5s），结果回填 `capabilities.reachable`；
2. `assert_minimum_viable()`：**至少 1 个源能拿日线 + 至少 1 个源能给复权
   因子，否则拒绝启动** —— 与 N-04 同源思想：能力不足就快速失败，
   不做降级假象（宁可任务 FAILED，不产出"看起来在跑"的空转）；
3. `FORBIDDEN_ENDPOINTS` 只登记不探测：禁用端点不浪费超时时间去试
   （ResilientSource 见到清单里的端点直接跳过）。
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from quant_v2.adapters.market_data.capabilities import DataCapabilities, utc_now
from quant_v2.domain.errors import SourceUnavailableError

__all__ = [
    "ProbeEndpoint",
    "ProbeReport",
    "ProbeResult",
    "SourceProbe",
    "assert_minimum_viable",
]

# TCP 建连函数：(host, port, timeout_s) -> None；建连失败抛 OSError。
# 抽出来是为了单测注入（真实网络行为不该进单测）。
TcpConnect = Callable[[str, int, float], None]


def _default_tcp_connect(host: str, port: int, timeout_s: float) -> None:
    """真实 TCP 建连（socket.create_connection，失败抛 OSError）。"""
    socket.create_connection((host, port), timeout=timeout_s).close()


class ProbeableSource(Protocol):
    """探活所需的适配器最小面（MarketDataAdapter 的子集）。"""

    source_id: str
    capabilities: DataCapabilities

    def healthcheck(self) -> object:
        """最小语义请求（各适配器自带短超时）。"""
        ...


@dataclass(frozen=True)
class ProbeEndpoint:
    """一个待探活的 TCP 端点。"""

    source_id: str
    host: str
    port: int


@dataclass(frozen=True)
class ProbeResult:
    """单源探活结果。"""

    source_id: str
    reachable: bool
    attempts: int
    ok_attempts: int
    detail: str
    endpoints: tuple[str, ...] = field(default=())
    capabilities: DataCapabilities | None = None


@dataclass(frozen=True)
class ProbeReport:
    """一次 probe_all 的完整结果。"""

    checked_at: datetime
    results: tuple[ProbeResult, ...]

    @property
    def viable(self) -> bool:
        """是否满足最低可用条件（能拿日线 + 能给因子，详见 assert_minimum_viable）。"""
        try:
            assert_minimum_viable(self)
        except SourceUnavailableError:
            return False
        return True

    def result_for(self, source_id: str) -> ProbeResult | None:
        """按 source_id 取结果。"""
        for result in self.results:
            if result.source_id == source_id:
                return result
        return None


def probe_endpoint_tcp(
    endpoint: ProbeEndpoint,
    *,
    attempts: int = 3,
    timeout_s: float = 5.0,
    tcp_connect: TcpConnect = _default_tcp_connect,
) -> tuple[bool, str]:
    """单端点 TCP 建连探测（重试 attempts 次）。

    Returns:
        (是否可达, 失败明细)。可达时明细为空串。
    """
    errors: list[str] = []
    for _ in range(attempts):
        try:
            tcp_connect(endpoint.host, endpoint.port, timeout_s)
        except OSError as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    if errors:
        return False, " | ".join(errors)
    return True, ""


class SourceProbe:
    """★ 部署前与每日启动时执行；结果回填 capabilities.reachable。"""

    def __init__(
        self,
        sources: Sequence[ProbeableSource],
        *,
        endpoints: Mapping[str, Sequence[ProbeEndpoint]] | None = None,
        attempts: int = 3,
        timeout_s: float = 5.0,
        tcp_connect: TcpConnect = _default_tcp_connect,
    ) -> None:
        self._sources = list(sources)
        self._endpoints = dict(endpoints or {})
        self._attempts = attempts
        self._timeout_s = timeout_s
        self._tcp_connect = tcp_connect

    def probe_all(self) -> ProbeReport:
        """对每个源：TCP 端点探测 + 最小语义请求（healthcheck），各重试。"""
        results: list[ProbeResult] = []
        for source in self._sources:
            results.append(self._probe_one(source))
        return ProbeReport(checked_at=utc_now(), results=tuple(results))

    def _probe_one(self, source: ProbeableSource) -> ProbeResult:
        """单源探测：端点详情收集 + 语义请求重试。"""
        endpoint_details: list[str] = []
        for endpoint in self._endpoints.get(source.source_id, ()):
            ok, detail = probe_endpoint_tcp(
                endpoint,
                attempts=self._attempts,
                timeout_s=self._timeout_s,
                tcp_connect=self._tcp_connect,
            )
            endpoint_details.append(f"{endpoint.host}:{endpoint.port}={'OK' if ok else 'FAIL'}")
            if detail:
                endpoint_details.append(f"  ↳ {detail}")

        ok_attempts = 0
        last_error = ""
        for _ in range(self._attempts):
            health = source.healthcheck()
            reachable = bool(getattr(health, "reachable", False))
            if reachable:
                ok_attempts += 1
            elif not last_error:
                last_error = str(getattr(health, "detail", "unknown"))
        reachable = ok_attempts > 0
        return ProbeResult(
            source_id=source.source_id,
            reachable=reachable,
            attempts=self._attempts,
            ok_attempts=ok_attempts,
            detail=last_error,
            endpoints=tuple(endpoint_details),
            capabilities=source.capabilities,
        )


def assert_minimum_viable(report: ProbeReport) -> None:
    """★ 最低可用性断言：不满足就拒绝启动（快速失败，不做降级假象）。

    Raises:
        SourceUnavailableError: 无任何可达源能给日线，或无任何可达源能给复权因子。
    """
    reachable = [r for r in report.results if r.reachable and r.capabilities is not None]
    if not any(r.capabilities.daily_bars for r in reachable):  # type: ignore[union-attr]
        raise SourceUnavailableError(
            "探活失败：没有任何可达数据源能提供日线行情 —— 拒绝启动"
            "（§5.12：能力不足就快速失败，不做降级假象）"
        )
    if not any(r.capabilities.adj_factor for r in reachable):  # type: ignore[union-attr]
        raise SourceUnavailableError(
            "探活失败：没有任何可达数据源能提供复权因子 —— 拒绝启动"
            "（复权因子缺失意味着除权日全是假跳空，宁可停下也不产出脏回测）"
        )
