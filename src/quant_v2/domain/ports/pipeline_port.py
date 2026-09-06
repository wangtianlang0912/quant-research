"""组件链端口（S-05 / S-06）—— 策略与框架的职责分界线。

```
【策略负责】UniverseProvider → FactorComputer → 规则 → Scorer
【框架负责】Ranker → Sizer → RiskManager → ExitRule → 门禁 → 持久化 → 推送
```

★ `DeclaresHistory` 是统一的最小历史长度声明协议 ——
框架据此反推预取量，从架构上消灭 v1 的"四道互相矛盾的门槛"。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from quant_v2.domain.guard.safe_series import SafeSeries
from quant_v2.domain.models.bar import InstrumentType
from quant_v2.domain.models.lifecycle import ExitDecision, TrackingState
from quant_v2.domain.models.market import MarketProfile
from quant_v2.domain.models.signal import RawSignal, ScoreBreakdown, ScoredSignal
from quant_v2.domain.ports.market_data_port import TradingCalendar

__all__ = [
    "DeclaresHistory",
    "ExitRule",
    "FactorComputer",
    "FactorContext",
    "FactorRegistry",
    "Ranker",
    "Scorer",
    "SurvivorshipRisk",
    "SymbolSnapshot",
    "UniverseProvider",
]


class SurvivorshipRisk(str, Enum):
    """幸存者偏差风险档位（附录 B 三级降级）。"""

    NONE = "NONE"  # 真实 PIT 切片，可直接用于回测
    PARTIAL = "PARTIAL"  # 池子大致正确但部分行情缺失，需标记 DATA_GAP
    HIGH = "HIGH"  # 只有【今天在市】的名单，回测结论系统性偏乐观


@dataclass(frozen=True)
class SymbolSnapshot:
    """股票池中的一个标的快照（PIT 语义）。"""

    symbol: str
    market: str
    name: str
    instrument_type: InstrumentType = InstrumentType.EQUITY
    is_st: bool = False
    industry: str = ""
    list_date: date | None = None
    delist_date: date | None = None


@runtime_checkable
class DeclaresHistory(Protocol):
    """统一的最小历史长度声明协议 —— 框架据此反推预取量。"""

    @property
    def required_history_bars(self) -> int:
        """本组件需要的最小历史 bar 数。"""
        ...


@runtime_checkable
class UniverseProvider(Protocol):
    """股票池提供者（PIT）。"""

    def symbols(self, *, as_of: date, market: str) -> Sequence[SymbolSnapshot]:
        """返回 `as_of` **当天**在市的标的。"""
        ...

    @property
    def survivorship_risk(self) -> SurvivorshipRisk:
        """幸存者偏差风险档位。"""
        ...

    @property
    def pool_build_date(self) -> date:
        """★ 池子构建日。

        回测请求 `as_of < pool_build_date` 时，引擎抛 `SurvivorshipBiasError`。
        """
        ...


@dataclass(frozen=True)
class FactorContext:
    """因子计算的上下文。"""

    as_of: date
    market_profile: MarketProfile
    calendar: TradingCalendar
    params: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class FactorComputer(DeclaresHistory, Protocol):
    """因子计算机。

    ★ `factor_id` 在注册表里唯一，**重复注册即报错**（S-06）。
    v1 有两套扫描器各写一份因子，70% 重复，改一个忘另一个。
    """

    factor_id: str
    human_label: str  # "估值便宜"
    direction: str  # "HIGH_IS_GOOD" | "LOW_IS_GOOD"

    def compute(self, bars: SafeSeries, ctx: FactorContext) -> Decimal | None:
        """计算因子值。

        Returns:
            因子值；`None` = 数据不足/不适用（**不参与打分，但计入覆盖率统计**）。

            ★ 返回 `None` 而不是 0：0 是一个真实可用的因子值，
            混在一起会让【这条因子没算出来】变成一个【中性】的打分依据。
        """
        ...


@runtime_checkable
class FactorRegistry(Protocol):
    """因子注册表 —— 单一实现 + 注册去重（S-06）。"""

    def register(self, factor: FactorComputer) -> None:
        """注册因子；`factor_id` 重复即抛错。"""
        ...

    def get(self, factor_id: str) -> FactorComputer:
        """按 ID 取因子；不存在即抛 KeyError。"""
        ...

    def all(self) -> Sequence[FactorComputer]:
        """全部已注册因子。"""
        ...

    @property
    def required_history_bars(self) -> int:
        """全部因子中最大的历史需求（框架预取用）。"""
        ...


@runtime_checkable
class Scorer(DeclaresHistory, Protocol):
    """打分器 —— 把因子值翻译成人话 + 分数贡献。"""

    def score(self, factors: Mapping[str, Decimal | None]) -> ScoreBreakdown:
        """打分。

        Returns:
            `ScoreBreakdown`，内含 `ScoreItem` 列表（人话标签 + 分数贡献 + note）。

            ★ 给【分数贡献】而不是【权重 × z-score】：
            小白看不懂 z-score，看得懂【估值便宜 +15 分】。
        """
        ...


@runtime_checkable
class Ranker(Protocol):
    """排序器（框架负责）。"""

    def rank(self, scored: Sequence[ScoredSignal], *, limit: int) -> Sequence[ScoredSignal]:
        """按分数排序并截断到 `limit` 条。"""
        ...


@runtime_checkable
class ExitRule(Protocol):
    """退出规则（框架负责）。"""

    rule_id: str

    def evaluate(self, signal: RawSignal, tracking: TrackingState) -> ExitDecision | None:
        """判定是否退出。

        Returns:
            `None` = 不触发；否则返回 `ExitDecision(target_state, reason_human, payload)`。
        """
        ...
