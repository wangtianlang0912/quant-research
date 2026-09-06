"""多源降级编排（T02.3 / D-10 / 附录 A 告警矩阵）。

## 核心纪律：降级必须被看见

v1 的事故不是"没有备源"，而是**主源挂了 40 天无人知晓** —— 静默降级
让"系统还在产出"和"系统还在产出正确的东西"变成同一件事。
v2 的降级三要素：

1. **切换即告警**：主源异常 → 立刻 P0（不是切换成功后才补一条日志）；
2. **恢复也留痕**：降级后主源首次恢复 → 记一条 INFO（告警闭环）；
3. **拉黑防级联**：失败的源跳过后续尝试（M-14 不浪费超时时间），
   **唯独最高优先级源例外** —— 每次调用给它一次重试，否则"自动恢复"
   永远检测不到；代价是主源故障期间每个请求多等一个超时窗口，
   这是有界的、显式声明的代价。

## 跨源校验（M-2 口径修正）

**只比不复权价**：`|raw_a - raw_b| / raw_a > 0.1%` 才算分歧。
**禁止**用 hfq 价直接比 —— 实测茅台差 13.66%、平安差 17.18%，但比值
逐日恒为常数，是复权锚点差异而非数据分歧，用 hfq 比会 100% 误报。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from quant_v2.domain.errors import SourceUnavailableError
from quant_v2.domain.models.bar import Bar

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from quant_v2.domain.ports.market_data_port import BarRequest

__all__ = [
    "AlertSink",
    "CrossDivergence",
    "ResilientSource",
]

# 跨源价格分歧阈值：0.1%（M-2 实测口径）
CROSS_VALIDATE_TOLERANCE = Decimal("0.001")


class AlertSink(Protocol):
    """告警落点（与 `SqliteStore.record_alert` 签名对齐）。"""

    def __call__(self, *, level: str, source: str, message: str, payload: str = "{}") -> None: ...


class FallbackSource(Protocol):
    """降级编排所需的适配器最小面。"""

    source_id: str
    capabilities: object

    def fetch_bars(self, req: BarRequest) -> Sequence[Bar]: ...


@dataclass(frozen=True)
class CrossDivergence:
    """一处跨源价格分歧（只针对不复权 close）。"""

    symbol: str
    day: date
    close_a: Decimal
    close_b: Decimal
    rel_diff: Decimal  # |a-b|/a，恒正


class ResilientSource:
    """★ 多源编排：按优先级尝试，降级必告警（D-10）。

    `sources` 必须**按优先级升序**排列（第一个 = 主源）。
    """

    def __init__(
        self,
        sources: Sequence[FallbackSource],
        *,
        alert_sink: AlertSink,
    ) -> None:
        if not sources:
            raise ValueError("ResilientSource 至少需要一个源：空列表 = 永远失败还得装作在跑")
        self._sources = list(sources)
        self._alert_sink = alert_sink
        self._blacklisted: set[str] = set()
        self._degraded = False  # 是否处于"主源失败、正走备源"状态

    # -- 状态 ---------------------------------------------

    @property
    def blacklisted(self) -> frozenset[str]:
        """已拉黑的源（只读视图；主源可能被恢复重试移出）。"""
        return frozenset(self._blacklisted)

    @property
    def degraded(self) -> bool:
        """是否处于降级状态（主源失败、正走备源）。"""
        return self._degraded

    # -- 行情 -------------------------------------------------

    def fetch_with_fallback(self, req: BarRequest) -> Sequence[Bar]:
        """按优先级顺序尝试各源；主源失败 → P0 告警 + 切备源。

        Raises:
            SourceUnavailableError: 全部源（含备源）都不可用。
        """
        last_error: SourceUnavailableError | None = None
        for source in self._sources:
            if self._is_skipped(source):
                continue
            try:
                bars = source.fetch_bars(req)
            except SourceUnavailableError as exc:
                last_error = exc
                self._on_failure(source, exc)
                continue
            self._on_success(source)
            self._alert_if_legacy(source, bars)
            return bars
        if last_error is None:  # pragma: no cover - 空源列表已在构造时拦下，防御性兜底
            raise SourceUnavailableError("全部数据源不可用（无失败明细）")
        raise SourceUnavailableError(
            f"全部数据源不可用（拉黑: {sorted(self._blacklisted)}）: {last_error}"
        )

    # -- 跨源校验（M-2） --------------------------------------

    def cross_validate(
        self,
        primary: Sequence[Bar],
        secondary: Sequence[Bar],
    ) -> list[CrossDivergence]:
        """跨源校验：只比不复权 close，> 0.1% 记 P1。

        只比较两边**都有**的 (symbol, date) 对；单边缺席不是价格分歧
        （是覆盖差异，由数据质量门禁负责），不在这里告警。
        """
        closes_a = {(bar.symbol, bar.date): bar.close for bar in primary}
        closes_b = {(bar.symbol, bar.date): bar.close for bar in secondary}
        divergences: list[CrossDivergence] = []
        for key in sorted(set(closes_a) & set(closes_b)):
            close_a = closes_a[key]
            close_b = closes_b[key]
            if close_a == 0:
                continue  # 零价行由质量门禁抓，这里除不得
            rel_diff = abs(close_a - close_b) / close_a
            if rel_diff > CROSS_VALIDATE_TOLERANCE:
                divergences.append(
                    CrossDivergence(
                        symbol=key[0],
                        day=key[1],
                        close_a=close_a,
                        close_b=close_b,
                        rel_diff=rel_diff,
                    )
                )
        if divergences:
            worst = max(divergences, key=lambda d: d.rel_diff)
            self._alert_sink(
                level="P1",
                source="resilient_source.cross_validate",
                message=(
                    f"跨源不复权价分歧 {len(divergences)} 处"
                    f"（最大 {worst.rel_diff:.4%} @ {worst.symbol} {worst.day}）"
                    "—— 只比 raw close（M-2），复权价口径差异不在此列"
                ),
            )
        return divergences

    # -- 内部：状态迁移与告警 ----------------------------------

    def _is_skipped(self, source: FallbackSource) -> bool:
        """拉黑的源跳过；最高优先级源豁免（每次调用一次重试 = 恢复检测）。"""
        if source.source_id not in self._blacklisted:
            return False
        return source is not self._sources[0]

    def _on_failure(self, source: FallbackSource, exc: SourceUnavailableError) -> None:
        """失败：拉黑；首次降级发 P0（防告警轰炸：一次故障一条 P0）。"""
        self._blacklisted.add(source.source_id)
        if not self._degraded:
            self._degraded = True
            self._alert_sink(
                level="P0",
                source=f"market_data.{source.source_id}",
                message=f"数据源 {source.source_id} 不可用，已切换备源: {exc}",
            )

    def _on_success(self, source: FallbackSource) -> None:
        """成功：主源恢复 → INFO 闭环 + 移出拉黑。"""
        if source is not self._sources[0]:
            return
        self._blacklisted.discard(source.source_id)
        if self._degraded:
            self._alert_sink(
                level="INFO",
                source=f"market_data.{source.source_id}",
                message="主源已恢复，退出降级状态（D-10：恢复也要留痕）",
            )
            self._degraded = False

    def _alert_if_legacy(self, source: FallbackSource, bars: Sequence[Bar]) -> None:
        """源无因子能力（capabilities.adj_factor=False）→ P1 提醒 legacy 序列。"""
        capabilities = source.capabilities
        if bool(getattr(capabilities, "adj_factor", True)):
            return
        self._alert_sink(
            level="P1",
            source=f"market_data.{source.source_id}",
            message=(
                f"{source.source_id} 返回 {len(bars)} 行无因子行情（source=*_legacy）："
                "该序列跨除权日不可直接比价，因子需由 baostock 主源补齐"
            ),
        )
