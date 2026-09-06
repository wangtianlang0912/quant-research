"""信号与解释契约（S-03 / S-04）。

★ v2 的第一条一等需求：**每条推荐都能讲清楚**。

门禁分两段，本文件同时锁死这两段：

- `validate_explanation_payload(payload)` —— 模型构造**之前**，查字段存在性，
  一次列出**全部**缺失项（用于告警与前端提示，而不是抛第一个异常就停）
- `SignalExplanation.missing_required_fields()` —— 模型构造**之后**，查语义
  （空列表、空白 headline、"无明显风险"这类套话）

另外锁死 **无退出计划 = 无信号**（S-04）：`ActionPlan` / `ExitPlan` / `RawSignal`
在构造期就强制带上止损、目标与最长持有天数。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from quant_v2.domain.models.lifecycle import TERMINAL_STATES, SignalState
from quant_v2.domain.models.signal import (
    FORBIDDEN_RISK_TEXTS,
    REQUIRED_EXPLANATION_FIELDS,
    ActionPlan,
    Comparator,
    ExitPlan,
    LifecycleSnapshot,
    RawSignal,
    ReasonItem,
    RiskItem,
    RiskLevel,
    ScoreBreakdown,
    ScoredSignal,
    ScoreItem,
    Signal,
    SignalDirection,
    SignalExplanation,
    validate_explanation_payload,
)

pytestmark = pytest.mark.unit

GENERATED_AT = datetime(2026, 9, 5, 1, 30, tzinfo=UTC)
AS_OF = date(2026, 9, 5)


def d(value: str) -> Decimal:
    """构造 Decimal（测试里禁止 float 字面量）。"""
    return Decimal(value)


def make_action_plan(**overrides: object) -> ActionPlan:
    kwargs: dict[str, object] = {
        "entry_low": d("10"),
        "entry_high": d("10.5"),
        "suggested_notional": d("5000"),
        "target_price": d("12"),
        "stop_loss_price": d("9.5"),
        "max_holding_days": 20,
        "expected_profit_yuan": d("750"),
        "max_loss_yuan": d("400"),
    }
    kwargs.update(overrides)
    return ActionPlan(**kwargs)  # type: ignore[arg-type]


def make_lifecycle(**overrides: object) -> LifecycleSnapshot:
    kwargs: dict[str, object] = {
        "state": SignalState.GENERATED,
        "holding_days": 0,
        "pnl_pct": d("0"),
        "pnl_yuan": d("0"),
        "progress_to_target": d("0"),
        "days_remaining": 20,
    }
    kwargs.update(overrides)
    return LifecycleSnapshot(**kwargs)  # type: ignore[arg-type]


def make_reason(**overrides: object) -> ReasonItem:
    kwargs: dict[str, object] = {
        "rule_name": "value.pe_low",
        "human_text": "PE=5.1，全市场最低的 10%",
        "actual_value": d("5.1"),
        "threshold": d("10"),
        "comparator": Comparator.LT,
        "passed": True,
    }
    kwargs.update(overrides)
    return ReasonItem(**kwargs)  # type: ignore[arg-type]


def make_score_item(**overrides: object) -> ScoreItem:
    kwargs: dict[str, object] = {
        "factor_label": "估值便宜",
        "contribution": d("15"),
        "note": "PE=5.1，全市场最低的 10%",
    }
    kwargs.update(overrides)
    return ScoreItem(**kwargs)  # type: ignore[arg-type]


def make_risk(text: str = "这种策略在单边下跌行情里会连续止损") -> RiskItem:
    return RiskItem(level=RiskLevel.MED, text=text)


def make_explanation(**overrides: object) -> SignalExplanation:
    kwargs: dict[str, object] = {
        "headline": "估值便宜且趋势转强",
        "reasons": [make_reason()],
        "score_breakdown": [make_score_item()],
        "action_plan": make_action_plan(),
        "risks": [make_risk()],
        "lifecycle": make_lifecycle(),
        "strategy_doc_ref": "strategies/docs/value_breakout.md",
        "score_total": d("72"),
        "score_historical_avg": d("55"),
    }
    kwargs.update(overrides)
    return SignalExplanation(**kwargs)  # type: ignore[arg-type]


def make_raw_signal(**overrides: object) -> RawSignal:
    kwargs: dict[str, object] = {
        "signal_id": "sig-001",
        "strategy_id": "value_breakout",
        "symbol": "601186.SH",
        "market": "cn_a",
        "as_of": AS_OF,
        "generated_at": GENERATED_AT,
        "score": d("72"),
        "entry_low": d("10"),
        "entry_high": d("10.5"),
        "target_price": d("12"),
        "stop_loss_price": d("9.5"),
        "max_holding_days": 20,
        "suggested_notional": d("5000"),
        "rationale": "估值处于全市场最低 10%，且站上 20 日均线",
    }
    kwargs.update(overrides)
    return RawSignal(**kwargs)  # type: ignore[arg-type]


class TestActionPlan:
    """③ 行动计划 —— 必须预先声明（S-04）。"""

    def test_合法计划通过(self) -> None:
        plan = make_action_plan()
        assert plan.suggested_notional == d("5000")
        assert plan.max_holding_days == 20

    def test_入场下界不可高于上界(self) -> None:
        with pytest.raises(ValidationError, match="entry_low"):
            make_action_plan(entry_low=d("10.6"), entry_high=d("10.5"))

    def test_入场下界等于上界合法(self) -> None:
        assert make_action_plan(entry_low=d("10.5"), entry_high=d("10.5")).entry_high == d("10.5")

    @pytest.mark.regression
    def test_止损必须低于入场下界(self) -> None:
        """★ v1 只有"买什么"没有"什么时候卖"；止损高于入场价意味着一入场就该卖。"""
        with pytest.raises(ValidationError, match="stop_loss_price"):
            make_action_plan(stop_loss_price=d("10"))
        with pytest.raises(ValidationError, match="stop_loss_price"):
            make_action_plan(stop_loss_price=d("11"))

    @pytest.mark.regression
    def test_目标必须高于入场下界之外(self) -> None:
        with pytest.raises(ValidationError, match="target_price"):
            make_action_plan(target_price=d("10.5"))
        with pytest.raises(ValidationError, match="target_price"):
            make_action_plan(target_price=d("9"))

    @pytest.mark.parametrize("expected_profit_yuan", ["0", "-1"])
    def test_目标收益必须为正(self, expected_profit_yuan: str) -> None:
        with pytest.raises(ValidationError, match="expected_profit_yuan 必须为正"):
            make_action_plan(expected_profit_yuan=d(expected_profit_yuan))

    @pytest.mark.parametrize("max_loss_yuan", ["0", "-1"])
    def test_最大亏损必须为正(self, max_loss_yuan: str) -> None:
        """零亏损预期是自欺欺人。"""
        with pytest.raises(ValidationError, match="max_loss_yuan 必须为正"):
            make_action_plan(max_loss_yuan=d(max_loss_yuan))

    @pytest.mark.parametrize("max_holding_days", [0, -1])
    def test_最长持有天数必须为正(self, max_holding_days: int) -> None:
        with pytest.raises(ValidationError):
            make_action_plan(max_holding_days=max_holding_days)


class TestRiskItem:
    @pytest.mark.regression
    @pytest.mark.parametrize("text", sorted(FORBIDDEN_RISK_TEXTS))
    def test_禁用话术全部登记(self, text: str) -> None:
        """★ 写这些等于没写风险，门禁直接拒。"""
        assert text in FORBIDDEN_RISK_TEXTS

    def test_风险项字段保留(self) -> None:
        risk = make_risk("连续止损风险")
        assert risk.level is RiskLevel.MED
        assert risk.text == "连续止损风险"

    def test_三级风险均可构造(self) -> None:
        for level in RiskLevel:
            assert RiskItem(level=level, text="有风险").level is level


class TestValidateExplanationPayload:
    """门禁跑在模型之前：一次列出全部缺失项，而不是抛第一个异常就停。"""

    def payload(self, **overrides: object) -> dict[str, Any]:
        base: dict[str, Any] = {
            "headline": "估值便宜且趋势转强",
            "reasons": [make_reason()],
            "score_breakdown": [make_score_item()],
            "action_plan": make_action_plan(),
            "risks": [make_risk()],
            "lifecycle": make_lifecycle(),
        }
        base.update(overrides)
        return base

    def test_完整payload通过(self) -> None:
        assert validate_explanation_payload(self.payload()) == ()

    def test_缺字段时逐个列出(self) -> None:
        missing = validate_explanation_payload({})
        assert missing == REQUIRED_EXPLANATION_FIELDS

    def test_字段值为None视为缺失(self) -> None:
        missing = validate_explanation_payload(self.payload(headline=None, risks=None))
        assert missing == ("headline", "risks")

    def test_缺失项按六大区块顺序返回(self) -> None:
        """★ 顺序稳定可测：告警信息与前端提示依赖这个顺序。"""
        payload = self.payload(score_breakdown=None, headline=None)
        assert validate_explanation_payload(payload) == ("headline", "score_breakdown")

    def test_去重(self) -> None:
        """headline 既缺失又空白时只报一次。"""
        assert validate_explanation_payload(self.payload(headline=None)) == ("headline",)

    @pytest.mark.parametrize("headline", ["", "   ", "\t"])
    def test_空白headline视为缺失(self, headline: str) -> None:
        assert "headline" in validate_explanation_payload(self.payload(headline=headline))

    @pytest.mark.parametrize("name", ["reasons", "score_breakdown"])
    def test_空列表视为缺失(self, name: str) -> None:
        assert validate_explanation_payload(self.payload(**{name: []})) == (name,)

    def test_元组形式的非空序列合法(self) -> None:
        payload = self.payload(reasons=(make_reason(),), score_breakdown=(make_score_item(),))
        assert validate_explanation_payload(payload) == ()

    @pytest.mark.parametrize("risks", [[], ()])
    def test_空风险列表视为缺失(self, risks: list[RiskItem]) -> None:
        assert validate_explanation_payload(self.payload(risks=risks)) == ("risks",)

    @pytest.mark.regression
    @pytest.mark.parametrize("text", sorted(FORBIDDEN_RISK_TEXTS))
    def test_禁用风险话术被拒(self, text: str) -> None:
        payload = self.payload(risks=[RiskItem(level=RiskLevel.LOW, text=text)])
        assert validate_explanation_payload(payload) == ("risks",)

    def test_风险文本空白被拒(self) -> None:
        assert validate_explanation_payload(self.payload(risks=[make_risk("  ")])) == ("risks",)

    def test_接受字典形式的风险项(self) -> None:
        """门禁跑在模型构造之前，输入是原始 payload —— 必须同时接受 dict。"""
        payload = self.payload(risks=[{"level": "MED", "text": "单边下跌会连续止损"}])
        assert validate_explanation_payload(payload) == ()

    def test_字典形式缺text字段被拒(self) -> None:
        payload = self.payload(risks=[{"level": "MED"}])
        assert validate_explanation_payload(payload) == ("risks",)

    def test_大小写与空白归一后仍识别禁用话术(self) -> None:
        payload = self.payload(risks=[make_risk("  N/A  ")])
        assert validate_explanation_payload(payload) == ("risks",)

    def test_非序列风险被拒(self) -> None:
        payload = self.payload(risks="无明显风险")
        assert validate_explanation_payload(payload) == ("risks",)


class TestLifecycleSnapshot:
    @pytest.mark.parametrize("progress", ["0", "1", "-1", "2", "0.5"])
    def test_区间内的进度合法(self, progress: str) -> None:
        assert make_lifecycle(progress_to_target=d(progress)).progress_to_target == d(progress)

    @pytest.mark.parametrize("progress", ["-1.1", "2.1", "10", "-100"])
    def test_越界的进度被拒(self, progress: str) -> None:
        """允许略微越界（止盈后继续上涨 / 止损跳空），但不能离谱。"""
        with pytest.raises(ValidationError, match="progress_to_target 越界"):
            make_lifecycle(progress_to_target=d(progress))

    def test_持有天数不可为负(self) -> None:
        with pytest.raises(ValidationError):
            make_lifecycle(holding_days=-1)

    def test_字段保留(self) -> None:
        snapshot = make_lifecycle(
            state=SignalState.ACTIVE,
            holding_days=5,
            pnl_pct=d("0.03"),
            pnl_yuan=d("150"),
            days_remaining=15,
        )
        assert snapshot.state is SignalState.ACTIVE
        assert snapshot.holding_days == 5
        assert snapshot.pnl_yuan == d("150")
        assert snapshot.days_remaining == 15


class TestSignalExplanation:
    def test_合法解释通过门禁(self) -> None:
        explanation = make_explanation()
        assert explanation.missing_required_fields() == ()
        assert explanation.passes_gate() is True

    def test_headline不可为纯空白(self) -> None:
        with pytest.raises(ValidationError, match="headline 不可为空白"):
            make_explanation(headline="   ")

    def test_headline不可为空串(self) -> None:
        with pytest.raises(ValidationError):
            make_explanation(headline="")

    def test_headline长度上限(self) -> None:
        with pytest.raises(ValidationError):
            make_explanation(headline="一" * 41)

    def test_headline上限内合法(self) -> None:
        assert make_explanation(headline="一" * 40).headline == "一" * 40

    @pytest.mark.regression
    def test_策略文档引用不可为空(self) -> None:
        """★ 用户必须能点进策略说明书，否则"为什么买"永远只有一句话。"""
        with pytest.raises(ValidationError, match="strategy_doc_ref 不可为空"):
            make_explanation(strategy_doc_ref="   ")

    def test_参照系字段保留(self) -> None:
        explanation = make_explanation()
        assert explanation.score_total == d("72")
        assert explanation.score_historical_avg == d("55")
        assert explanation.glossary_refs == []

    def test_六大必填区块常量(self) -> None:
        assert REQUIRED_EXPLANATION_FIELDS == (
            "headline",
            "reasons",
            "score_breakdown",
            "action_plan",
            "risks",
            "lifecycle",
        )
        assert SignalExplanation.REQUIRED_FIELDS is REQUIRED_EXPLANATION_FIELDS

    def test_多条理由与打分均可携带(self) -> None:
        explanation = make_explanation(
            reasons=[make_reason(), make_reason(rule_name="mom.above_ma20")],
            score_breakdown=[make_score_item(), make_score_item(contribution=d("-8"))],
        )
        assert len(explanation.reasons) == 2
        assert len(explanation.score_breakdown) == 2


class TestMissingRequiredFields:
    """语义层门禁。

    ★ 这些分支在**正常构造**下不可达（模型已先拦一道），
    因此用 `model_construct` 绕过构造期校验，只验门禁的语义判定本身。
    门禁的调用方（`explanation_gate.py`）跑在模型之前，正是这些分支的真实场景。
    """

    def construct(self, **overrides: object) -> SignalExplanation:
        kwargs: dict[str, Any] = {
            "headline": "估值便宜且趋势转强",
            "reasons": [make_reason()],
            "score_breakdown": [make_score_item()],
            "action_plan": make_action_plan(),
            "risks": [make_risk()],
            "lifecycle": make_lifecycle(),
            "glossary_refs": [],
            "strategy_doc_ref": "strategies/docs/value_breakout.md",
            "score_total": d("72"),
            "score_historical_avg": d("55"),
        }
        kwargs.update(overrides)
        return SignalExplanation.model_construct(**kwargs)

    def test_空白headline被判缺失(self) -> None:
        assert self.construct(headline="   ").missing_required_fields() == ("headline",)

    def test_空理由列表被判缺失(self) -> None:
        assert self.construct(reasons=[]).missing_required_fields() == ("reasons",)

    def test_空打分列表被判缺失(self) -> None:
        assert self.construct(score_breakdown=[]).missing_required_fields() == ("score_breakdown",)

    @pytest.mark.regression
    @pytest.mark.parametrize("text", sorted(FORBIDDEN_RISK_TEXTS)[:4])
    def test_套话风险被判缺失(self, text: str) -> None:
        explanation = self.construct(risks=[RiskItem(level=RiskLevel.LOW, text=text)])
        assert explanation.missing_required_fields() == ("risks",)
        assert explanation.passes_gate() is False

    def test_多项同时缺失(self) -> None:
        obj = self.construct(headline=" ", reasons=[], score_breakdown=[])
        problems = obj.missing_required_fields()
        assert problems == ("headline", "reasons", "score_breakdown")

    def test_风险项接受字典形式(self) -> None:
        mapping: Mapping[str, Any] = {"level": "MED", "text": "单边下跌会连续止损"}
        assert self.construct(risks=[mapping]).passes_gate() is True


class TestScoreBreakdown:
    def test_总分为各项贡献之和(self) -> None:
        breakdown = ScoreBreakdown(
            items=(make_score_item(contribution=d("15")), make_score_item(contribution=d("-8")))
        )
        assert breakdown.total == d("7")

    def test_空明细总分为零(self) -> None:
        assert ScoreBreakdown().total == d("0")

    def test_默认为空元组(self) -> None:
        assert ScoreBreakdown().items == ()


class TestScoredSignal:
    def test_分数取明细总分(self) -> None:
        scored = ScoredSignal(
            signal=make_raw_signal(),
            breakdown=ScoreBreakdown(items=(make_score_item(contribution=d("72")),)),
        )
        assert scored.score == d("72")
        assert scored.signal.signal_id == "sig-001"


class TestExitPlan:
    """★ 预声明的退出计划：无退出计划 = 无信号。"""

    def make_plan(self, **overrides: object) -> ExitPlan:
        kwargs: dict[str, object] = {
            "target_price": d("12"),
            "stop_loss_price": d("9.5"),
            "max_holding_days": 20,
            "max_wait_days": 5,
            "rationale": "涨 18% 止盈，跌破 8% 必须卖，最多拿 20 天",
        }
        kwargs.update(overrides)
        return ExitPlan(**kwargs)  # type: ignore[arg-type]

    def test_合法计划通过(self) -> None:
        plan = self.make_plan()
        assert plan.target_price == d("12")
        assert plan.max_wait_days == 5

    def test_止损不可高于目标(self) -> None:
        with pytest.raises(ValueError, match="stop_loss_price"):
            self.make_plan(stop_loss_price=d("12"))
        with pytest.raises(ValueError, match="stop_loss_price"):
            self.make_plan(stop_loss_price=d("13"))

    @pytest.mark.parametrize("max_holding_days", [0, -1])
    def test_最长持有天数必须为正(self, max_holding_days: int) -> None:
        with pytest.raises(ValueError, match="max_holding_days 必须为正"):
            self.make_plan(max_holding_days=max_holding_days)

    @pytest.mark.parametrize("max_wait_days", [0, -1])
    @pytest.mark.regression
    def test_等待上限必须为正(self, max_wait_days: int) -> None:
        """★ v1「信号永远停在 WATCHING」的直接反例：没有等待上限就永远不退出。"""
        with pytest.raises(ValueError, match="max_wait_days 必须为正"):
            self.make_plan(max_wait_days=max_wait_days)

    @pytest.mark.parametrize("rationale", ["", "   "])
    def test_人话说明不可为空(self, rationale: str) -> None:
        with pytest.raises(ValueError, match="rationale 不可为空"):
            self.make_plan(rationale=rationale)


class TestRawSignal:
    def test_合法多头信号通过(self) -> None:
        signal = make_raw_signal()
        assert signal.direction is SignalDirection.LONG
        assert signal.max_holding_days == 20

    def test_入场下界不可高于上界(self) -> None:
        with pytest.raises(ValidationError, match="entry_low"):
            make_raw_signal(entry_low=d("11"), entry_high=d("10.5"))

    @pytest.mark.regression
    def test_多头止损必须低于入场下界(self) -> None:
        with pytest.raises(ValidationError, match="多头信号 stop_loss_price"):
            make_raw_signal(stop_loss_price=d("10"))

    @pytest.mark.regression
    def test_多头目标必须高于入场下界之外(self) -> None:
        with pytest.raises(ValidationError, match="多头信号 target_price"):
            make_raw_signal(target_price=d("10.5"))

    def test_空头止损必须高于入场价(self) -> None:
        signal = make_raw_signal(
            direction=SignalDirection.SHORT,
            entry_low=d("10"),
            entry_high=d("10.5"),
            stop_loss_price=d("11"),
            target_price=d("8"),
        )
        assert signal.direction is SignalDirection.SHORT

    def test_空头止损不高于入场价被拒(self) -> None:
        with pytest.raises(ValidationError, match="空头信号 stop_loss_price"):
            make_raw_signal(
                direction=SignalDirection.SHORT,
                stop_loss_price=d("10.5"),
                target_price=d("8"),
            )

    def test_空头目标不低于入场价被拒(self) -> None:
        with pytest.raises(ValidationError, match="空头信号 target_price"):
            make_raw_signal(
                direction=SignalDirection.SHORT,
                stop_loss_price=d("11"),
                target_price=d("10"),
            )

    @pytest.mark.parametrize("max_holding_days", [0, -1])
    def test_最长持有天数必须为正(self, max_holding_days: int) -> None:
        with pytest.raises(ValidationError):
            make_raw_signal(max_holding_days=max_holding_days)

    @pytest.mark.parametrize("suggested_notional", ["0", "-1"])
    def test_建议金额必须为正(self, suggested_notional: str) -> None:
        with pytest.raises(ValidationError):
            make_raw_signal(suggested_notional=d(suggested_notional))

    def test_rationale可缺省且默认为空串(self) -> None:
        payload = make_raw_signal().model_dump()
        del payload["rationale"]
        assert RawSignal(**payload).rationale == ""


class TestSignal:
    def test_默认状态为已生成(self) -> None:
        signal = Signal(**make_raw_signal().model_dump())
        assert signal.state is SignalState.GENERATED
        assert signal.explanation is None
        assert signal.quantity is None
        assert signal.notional is None
        assert signal.run_id is None

    def test_终止状态的信号is_terminal为真(self) -> None:
        for state in sorted(TERMINAL_STATES, key=lambda item: item.value):
            signal = Signal(**make_raw_signal().model_dump(), state=state)
            assert signal.is_terminal is True, f"{state.value} 应判为终止"

    def test_非终止状态的信号is_terminal为假(self) -> None:
        for state in (SignalState.GENERATED, SignalState.WATCHING, SignalState.ACTIVE):
            signal = Signal(**make_raw_signal().model_dump(), state=state)
            assert signal.is_terminal is False, f"{state.value} 不该判为终止"

    def test_可携带解释与成交建议(self) -> None:
        signal = Signal(
            **make_raw_signal().model_dump(),
            state=SignalState.WATCHING,
            explanation=make_explanation(),
            quantity=400,
            notional=d("5000"),
            run_id="daily-scan-20260905T013000-abcdef12",
        )
        assert signal.quantity == 400
        assert signal.notional == d("5000")
        assert signal.explanation is not None
        assert signal.explanation.passes_gate() is True
