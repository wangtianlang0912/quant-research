"""信号与解释契约（S-03 / S-04 / PRD §2.4）。

★ 这个文件承载 v2 的第一条一等需求：**每条推荐都能讲清楚**。

`SignalExplanation` 是策略与前端的契约，六个必填区块：

1. `headline`        一句话结论（≤20 汉字，纯自然语言，禁术语）
2. `reasons`         为什么买 —— 逐条规则 + 实际值 vs 阈值
3. `score_breakdown` 打分明细 —— 直接给分数贡献，不给"权重 × z-score"（小白看不懂）
4. `action_plan`     行动计划 —— 目标价/止损/最长持有天数/"目标赚 750 元"
5. `risks`           风险 —— 必填，**不得写"无明显风险"**
6. `lifecycle`       现在怎么样 —— 持有天数/盈亏/距目标进度

任一必填字段缺失 → 门禁拒绝该信号（S-03，P0 告警）。
门禁的纯逻辑在 `SignalExplanation.missing_required_fields()`，
由 T03 的 `engines/pipeline/explanation_gate.py` 调用 —— 规则留在领域层，可被单测。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_v2.domain.models.lifecycle import TERMINAL_STATES, SignalState

__all__ = [
    "FORBIDDEN_RISK_TEXTS",
    "REQUIRED_EXPLANATION_FIELDS",
    "ActionPlan",
    "Comparator",
    "ExitPlan",
    "LifecycleSnapshot",
    "RawSignal",
    "ReasonItem",
    "RiskItem",
    "RiskLevel",
    "ScoreBreakdown",
    "ScoreItem",
    "ScoredSignal",
    "Signal",
    "SignalDirection",
    "SignalExplanation",
    "validate_explanation_payload",
]


class Comparator(str, Enum):
    """阈值比较运算符 —— 用于把"实际值 vs 阈值"渲染成人话。"""

    GT = "GT"
    LT = "LT"
    GTE = "GTE"
    LTE = "LTE"
    BETWEEN = "BETWEEN"
    IN = "IN"


class RiskLevel(str, Enum):
    """风险等级。"""

    LOW = "LOW"
    MED = "MED"
    HIGH = "HIGH"


class SignalDirection(str, Enum):
    """信号方向。v1 不做做空，保留字段是为了让 Sizer/Risk 的语义完整。"""

    LONG = "LONG"
    SHORT = "SHORT"


class ReasonItem(BaseModel):
    """① 为什么买 —— 逐条规则。

    `human_text` 必须**禁止出现因子名 / z-score**。
    "PE=5.1，全市场最低的 10%" 是人话；"value_factor z=-1.8" 不是。
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    rule_name: str  # 机器可读 ID，如 'value.pe_low'
    human_text: str
    actual_value: Decimal
    threshold: Decimal
    comparator: Comparator
    passed: bool


class ScoreItem(BaseModel):
    """② 打分明细 —— 直接给分数贡献。

    ★ 不给"权重 × z-score"：把内部计算过程丢给用户，等于没解释。
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    factor_label: str  # "估值便宜"（人话标签）
    contribution: Decimal  # +15 / -8
    note: str  # "PE=5.1，全市场最低的 10%"


class ActionPlan(BaseModel):
    """③ 行动计划 —— 必须预先声明（S-04）。

    ★ v1 缺陷：信号只有"买什么"，没有"什么时候卖"。
    没有退出计划的信号 = 没有信号，因为它无法被跟踪，也就无法有始有终。

    金额优先表述："投入约 ¥5,000，目标赚 ¥750，最多亏 ¥400" —— 小白看金额比看百分比直观。
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    entry_low: Decimal
    entry_high: Decimal
    suggested_notional: Decimal  # 建议投入金额（元）
    target_price: Decimal
    stop_loss_price: Decimal
    max_holding_days: int = Field(gt=0)
    expected_profit_yuan: Decimal  # "目标赚 750 元"
    max_loss_yuan: Decimal  # "最多亏 400 元"

    @model_validator(mode="after")
    def _validate_plan(self) -> ActionPlan:
        if self.entry_low > self.entry_high:
            raise ValueError(f"entry_low({self.entry_low}) > entry_high({self.entry_high})")
        if self.stop_loss_price >= self.entry_low:
            raise ValueError(
                f"stop_loss_price({self.stop_loss_price}) 必须低于 entry_low({self.entry_low})"
            )
        if self.target_price <= self.entry_high:
            raise ValueError(
                f"target_price({self.target_price}) 必须高于 entry_high({self.entry_high})"
            )
        if self.expected_profit_yuan <= 0:
            raise ValueError("expected_profit_yuan 必须为正：目标收益为负的信号不该被推荐")
        if self.max_loss_yuan <= 0:
            raise ValueError("max_loss_yuan 必须为正：零亏损预期是自欺欺人")
        return self


class RiskItem(BaseModel):
    """④ 风险 —— 必填，且禁止写"无明显风险"。"""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    level: RiskLevel
    text: str  # "这种策略在单边下跌行情里会连续止损"


# ★ 风险栏的禁用话术。写这些等于没写风险，门禁直接拒。
FORBIDDEN_RISK_TEXTS: frozenset[str] = frozenset(
    {
        "无明显风险",
        "无风险",
        "风险较低",
        "暂无风险",
        "风险可控",
        "n/a",
        "na",
        "none",
        "-",
    }
)

# ★ 六大必填区块。门禁的唯一真源，模型与门禁共用同一份常量。
REQUIRED_EXPLANATION_FIELDS: tuple[str, ...] = (
    "headline",
    "reasons",
    "score_breakdown",
    "action_plan",
    "risks",
    "lifecycle",
)


def _risk_texts_valid(risks: Any) -> bool:
    """风险栏校验：非空，且不得是"等于没写"的套话。

    同时接受 `RiskItem` 列表与字典列表（门禁跑在模型构造之前，输入是原始 payload）。
    """
    if not isinstance(risks, (list, tuple)) or len(risks) == 0:
        return False
    for item in risks:
        text = item.get("text", "") if isinstance(item, Mapping) else getattr(item, "text", "")
        normalized = str(text).strip().lower()
        if not normalized:
            return False
        if normalized in FORBIDDEN_RISK_TEXTS:
            return False
    return True


def validate_explanation_payload(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """★ 解释门禁（S-03）：在构造 `SignalExplanation` **之前**校验原始 payload。

    门禁跑在模型之前是刻意的：模型构造失败只会抛 `ValidationError`，
    而门禁需要"列出所有缺失项"用于告警与前端提示 —— 一次说清，而不是抛第一个异常就停。

    Args:
        payload: 策略产出的解释字典。

    Returns:
        缺失或非法的必填字段名元组；空元组表示通过。
    """
    problems: list[str] = []

    for name in REQUIRED_EXPLANATION_FIELDS:
        if name not in payload or payload[name] is None:
            problems.append(name)

    headline = payload.get("headline")
    if "headline" not in problems and not str(headline).strip():
        problems.append("headline")

    for name in ("reasons", "score_breakdown"):
        if name not in problems:
            value = payload.get(name)
            if not isinstance(value, (list, tuple)) or len(value) == 0:
                problems.append(name)

    if "risks" not in problems and not _risk_texts_valid(payload.get("risks")):
        problems.append("risks")

    # 去重并保持 REQUIRED_EXPLANATION_FIELDS 的顺序，保证告警信息稳定可测
    ordered: list[str] = []
    for name in REQUIRED_EXPLANATION_FIELDS:
        if name in problems and name not in ordered:
            ordered.append(name)
    return tuple(ordered)


class LifecycleSnapshot(BaseModel):
    """⑤ 现在怎么样 —— 前端生命周期徽章与时间轴的数据源。"""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    state: SignalState
    holding_days: int = Field(ge=0)
    pnl_pct: Decimal
    pnl_yuan: Decimal
    progress_to_target: Decimal  # 0~1：相对目标/止损区间的进度
    days_remaining: int

    @model_validator(mode="after")
    def _validate_progress(self) -> LifecycleSnapshot:
        # 允许略微越界（止盈后继续上涨 / 止损跳空突破），但不能离谱
        if not (Decimal("-1") <= self.progress_to_target <= Decimal("2")):
            raise ValueError(f"progress_to_target 越界：{self.progress_to_target}")
        return self


class SignalExplanation(BaseModel):
    """策略与前端的契约。★ 任一必填字段缺失 → 门禁拒绝该信号（S-03）。"""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    headline: str = Field(min_length=1, max_length=40)  # ≤20 汉字
    reasons: list[ReasonItem] = Field(min_length=1)
    score_breakdown: list[ScoreItem] = Field(min_length=1)
    action_plan: ActionPlan
    risks: list[RiskItem] = Field(min_length=1)
    lifecycle: LifecycleSnapshot
    glossary_refs: list[str] = Field(default_factory=list)
    strategy_doc_ref: str
    score_total: Decimal
    score_historical_avg: Decimal  # 参照系："总分 72，历史均分 55"

    # 门禁：由 engines/pipeline/explanation_gate.py 调用
    REQUIRED_FIELDS: ClassVar[tuple[str, ...]] = REQUIRED_EXPLANATION_FIELDS

    @model_validator(mode="after")
    def _validate_headline(self) -> SignalExplanation:
        if not self.headline.strip():
            raise ValueError("headline 不可为空白")
        if not self.strategy_doc_ref.strip():
            raise ValueError("strategy_doc_ref 不可为空：用户必须能点进策略说明书")
        return self

    def missing_required_fields(self) -> tuple[str, ...]:
        """★ 返回语义层面缺失/非法的必填字段名（空元组 = 通过门禁）。

        与 `validate_explanation_payload()` 的分工：

        - `validate_explanation_payload(payload)` —— 模型构造**之前**，检查字段存在性
        - `SignalExplanation.missing_required_fields()` —— 模型构造**之后**，检查语义
          （空列表、空白 headline、"无明显风险"这类套话）

        规则留在领域层，使门禁可被纯单测覆盖，不依赖引擎与 I/O。
        """
        problems: list[str] = []

        if not self.headline.strip():
            problems.append("headline")
        if not self.reasons:
            problems.append("reasons")
        if not self.score_breakdown:
            problems.append("score_breakdown")
        if not self._risks_valid():
            problems.append("risks")
        return tuple(problems)

    def _risks_valid(self) -> bool:
        """风险栏语义校验：非空，且不得是"等于没写"的套话。"""
        return _risk_texts_valid(self.risks)

    def passes_gate(self) -> bool:
        """是否通过解释门禁。"""
        return not self.missing_required_fields()


@dataclass(frozen=True)
class ScoreBreakdown:
    """`Scorer.score()` 的返回值 —— 明细 + 总分。"""

    items: tuple[ScoreItem, ...] = field(default_factory=tuple)

    @property
    def total(self) -> Decimal:
        """总分 = 各因子贡献之和。"""
        return sum((item.contribution for item in self.items), Decimal("0"))


@dataclass(frozen=True)
class ScoredSignal:
    """带分的信号 —— `Ranker.rank()` 的输入/输出元素。"""

    signal: RawSignal
    breakdown: ScoreBreakdown

    @property
    def score(self) -> Decimal:
        """排序用分数（默认取 breakdown 总分）。"""
        return self.breakdown.total


@dataclass(frozen=True)
class ExitPlan:
    """★ 预声明的退出计划（S-04）：无退出计划 = 无信号。"""

    target_price: Decimal
    stop_loss_price: Decimal
    max_holding_days: int
    max_wait_days: int  # WATCHING → NOT_TRIGGERED 的等待上限
    rationale: str  # 人话："涨 18% 止盈，跌破 8% 必须卖，最多拿 20 天"

    def __post_init__(self) -> None:
        """退出计划自洽性校验。"""
        if self.stop_loss_price >= self.target_price:
            raise ValueError(
                f"stop_loss_price({self.stop_loss_price}) 必须低于 "
                f"target_price({self.target_price})"
            )
        if self.max_holding_days <= 0:
            raise ValueError("max_holding_days 必须为正：没有持有上限的信号无法超时退出")
        if self.max_wait_days <= 0:
            raise ValueError("max_wait_days 必须为正：没有等待上限的信号会永远停在 WATCHING")
        if not self.rationale.strip():
            raise ValueError("rationale 不可为空：退出计划必须用一句话向用户说清")


class RawSignal(BaseModel):
    """策略产出的原始信号（未经 Ranker / Sizer / Risk）。

    ★ 已内联 `ActionPlan` 的关键字段：v1 的缺陷是信号里只有"买什么"没有"怎么卖"，
    v2 让 `RawSignal` 构造时就必须带上止损/目标/最长持有天数。
    """

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    signal_id: str
    strategy_id: str
    symbol: str
    market: str
    as_of: date
    generated_at: datetime
    direction: SignalDirection = SignalDirection.LONG
    score: Decimal

    entry_low: Decimal
    entry_high: Decimal
    target_price: Decimal
    stop_loss_price: Decimal
    max_holding_days: int = Field(gt=0)
    suggested_notional: Decimal = Field(gt=0)

    rationale: str = ""  # 策略给的一句话人话（进 explanation.headline 的原料）

    @model_validator(mode="after")
    def _validate_prices(self) -> RawSignal:
        if self.entry_low > self.entry_high:
            raise ValueError(f"entry_low({self.entry_low}) > entry_high({self.entry_high})")
        if self.direction is SignalDirection.LONG:
            if self.stop_loss_price >= self.entry_low:
                raise ValueError(
                    f"多头信号 stop_loss_price({self.stop_loss_price}) "
                    f"必须低于 entry_low({self.entry_low})"
                )
            if self.target_price <= self.entry_high:
                raise ValueError(
                    f"多头信号 target_price({self.target_price}) "
                    f"必须高于 entry_high({self.entry_high})"
                )
        else:
            if self.stop_loss_price <= self.entry_high:
                raise ValueError(
                    f"空头信号 stop_loss_price({self.stop_loss_price}) "
                    f"必须高于 entry_high({self.entry_high})"
                )
            if self.target_price >= self.entry_low:
                raise ValueError(
                    f"空头信号 target_price({self.target_price}) "
                    f"必须低于 entry_low({self.entry_low})"
                )
        return self


class Signal(RawSignal):
    """持久化形态的信号 = RawSignal + 生命周期状态 + 解释 + 成交建议。

    `state` 只能通过 `LifecycleRepository.apply_transition()` 修改（L-04），
    禁止任何地方直接赋值 —— 由 `test_state_machine_complete.py` 与代码评审守住。
    """

    state: SignalState = SignalState.GENERATED
    explanation: SignalExplanation | None = None
    quantity: int | None = None  # 由 Sizer 计算，**禁止硬编码**（ARCH002）
    notional: Decimal | None = None
    run_id: str | None = None

    @property
    def is_terminal(self) -> bool:
        """是否处于终止节点（有始有终）。"""
        return self.state in TERMINAL_STATES
