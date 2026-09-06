"""策略端口（S-01 / S-02 / S-04 / S-09）。

★ 职责切分（关键决策）：

```
【策略负责】UniverseProvider → FactorComputer → 规则 → Scorer   ← 策略作者只写"什么值得买"
【框架负责】Ranker → Sizer → RiskManager → ExitRule → 门禁 → 持久化 → 推送
```

这样：新增策略的 diff **不可能**包含 `engines/`（S-01 验收）。

★ `StrategySpec.min_history_bars` 是**声明式契约**，不是策略内部的私有常量。
v1 的 `breakout_scorer.py` 有四道互相矛盾的最小长度门槛，根因就是
"需要多少历史"这件事散落在策略内部的各个角落，谁也说不清到底要多少。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol, runtime_checkable

from quant_v2.domain.guard.safe_series import SafeSeries
from quant_v2.domain.models.market import MarketProfile
from quant_v2.domain.models.signal import ExitPlan, RawSignal, SignalExplanation
from quant_v2.domain.ports.market_data_port import TradingCalendar
from quant_v2.domain.ports.pipeline_port import FactorRegistry, Scorer, UniverseProvider

__all__ = ["InvalidationRule", "Strategy", "StrategyContext", "StrategyDoc", "StrategySpec"]


@dataclass(frozen=True)
class StrategySpec:
    """★ 声明式元数据 —— 策略的契约。

    `min_history_bars` 是框架反推数据预取量的唯一依据。
    """

    strategy_id: str
    name: str
    tagline: str  # ≤20 字人话一句话结论（PRD §2.4 第 1 层）
    markets: frozenset[str]  # 仅用于"该策略是否适用于该市场"的容量校验，**非分支**
    min_history_bars: int  # ★ 框架据此反推数据预取量
    holding_period: tuple[int, int]  # (最短持有天数, 最长持有天数)
    default_params: Mapping[str, Any] = field(default_factory=dict)
    doc_ref: str = ""  # strategies/docs/*.md
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        """规格自洽性校验 —— 声明写错必须立刻炸，不能等到回测时才发现。"""
        if not self.strategy_id:
            raise ValueError("StrategySpec.strategy_id 不可为空")
        if self.min_history_bars <= 0:
            raise ValueError(
                f"min_history_bars 必须为正，收到 {self.min_history_bars}："
                "它是框架预取数据的唯一依据，为 0 意味着【不需要历史】，那不可能成立"
            )
        low, high = self.holding_period
        if low <= 0 or high <= 0:
            raise ValueError(f"holding_period 必须为正数对，收到 {self.holding_period}")
        if low > high:
            raise ValueError(f"holding_period 下界不能大于上界：{self.holding_period}")


@dataclass(frozen=True)
class StrategyContext:
    """注入给策略的全部依赖 —— 策略不接触 I/O。"""

    market_profile: MarketProfile
    params: Mapping[str, Any]
    universe: UniverseProvider
    factors: FactorRegistry
    scorer: Scorer
    calendar: TradingCalendar
    seed: int


@dataclass(frozen=True)
class StrategyDoc:
    """五段式人话说明书（`Strategy.describe()` 的返回值）。

    五段：① 一句话结论 ② 它认为什么值得买 ③ 什么情况下会失效
          ④ 历史战绩（★ **必须含最差的一段**）⑤ 小白怎么看这条信号

    ★ 第 ④ 段强制含最差表现：只报喜的说明书等于营销材料，
    用户拿着它去实盘，遇到回撤会以为是系统坏了。
    """

    strategy_id: str
    headline: str  # ≤20 字一句话结论
    what_it_buys: str  # 它认为什么值得买
    when_it_fails: str  # 什么情况下会失效
    track_record: str  # 历史战绩，**必须含最差的一段**
    how_to_read: str  # 小白怎么看这条信号
    doc_path: str = ""

    def __post_init__(self) -> None:
        """说明书完整性校验 —— 五段缺一段就当没写。"""
        missing = [
            name
            for name in ("headline", "what_it_buys", "when_it_fails", "track_record", "how_to_read")
            if not getattr(self, name).strip()
        ]
        if missing:
            raise ValueError(f"StrategyDoc 缺少必填段落：{missing}")


@dataclass(frozen=True)
class InvalidationRule:
    """`THESIS_INVALID` 的判定式（L-06）—— 每条规则带人话描述。"""

    rule_id: str
    human_text: str  # "跌破 20 日均线且成交量放大 2 倍以上，说明趋势可能反转"
    predicate: str  # 可求值的表达式标识（由引擎按 rule_id 分派，不用 eval）
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """规则校验。"""
        if not self.rule_id:
            raise ValueError("InvalidationRule.rule_id 不可为空")
        if not self.human_text.strip():
            raise ValueError("InvalidationRule.human_text 不可为空：用户必须知道什么情况该放弃")


@runtime_checkable
class Strategy(Protocol):
    """策略端口。

    实现类**不需要继承任何基类** —— 只要"长得像"就能用（`StrategyBase` 只是可选的便利基类）。
    """

    @property
    def spec(self) -> StrategySpec:
        """策略规格（声明式元数据）。"""
        ...

    def required_history_bars(self) -> int:
        """框架调用：返回本策略需要的最小历史长度。

        ★ 默认返回 `spec.min_history_bars`；若策略组合了 Scorer / FactorComputer，
        必须返回 `max(自身, 各组件)` ——
        `strategies/base.py::StrategyBase` 提供默认聚合实现，**禁止子类自己写死**。
        """
        ...

    def prepare(self, ctx: StrategyContext) -> None:
        """一次性准备（参数校验、warm-up）。引擎在 `generate_signals` 前调用一次。"""
        ...

    def generate_signals(
        self,
        as_of: date,
        bars: Mapping[str, SafeSeries],
    ) -> Sequence[RawSignal]:
        """生成信号。

        ★ 只能通过 `SafeSeries` 访问数据；越界访问由 SafeSeries 抛
        `LookaheadViolationError`。

        ★ **禁止在此方法内做数据长度校验**（由框架统一做）——
        v1 的四道互相矛盾的门槛就是策略自己校验长度造成的。
        """
        ...

    def explain(self, signal: RawSignal) -> SignalExplanation:
        """六区块全填充。任一必填字段缺失 → 门禁拒绝（S-03）。

        ★ 金额优先：`ActionPlan` 里给"投入约 ¥5,000，目标赚 ¥750，最多亏 ¥400"，
        而不是只给百分比 —— 小白对金额的直觉远好于对百分比的直觉。
        """
        ...

    def exit_plan(self, signal: RawSignal) -> ExitPlan:
        """★ 预声明退出计划：目标价 / 止损价 / 最长持有天数 / 未入场等待期。

        **无退出计划 = 无信号**（S-04）。没有退出计划的信号无法被跟踪，
        也就无法"有始有终"。
        """
        ...

    def invalidation_conditions(self) -> Sequence[InvalidationRule]:
        """`THESIS_INVALID` 的判定式（L-06）。"""
        ...

    def describe(self) -> StrategyDoc:
        """五段式人话说明书 + 历史战绩（★ 必须含最差的一段）。"""
        ...
