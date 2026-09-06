"""生命周期模型的补充覆盖（L-01 / L-04 / L-06）。

上一轮已覆盖迁移表与 `lifecycle_machine`，这里补齐模型自身：

- `is_terminal()` / `is_closed()` —— 终止节点与业务终态的判定
- `TransitionRecord.__post_init__` —— 审计字段不得"写了等于没写"
- `ExitDecision.__post_init__` —— 退出决策只能指向退出类状态
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from quant_v2.domain.models.lifecycle import (
    CLOSED_STATES,
    TERMINAL_STATES,
    Actor,
    ExitDecision,
    SignalState,
    TrackingState,
    TransitionRecord,
    is_closed,
    is_terminal,
)

pytestmark = pytest.mark.unit

FIXED_AT = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)


def d(value: str) -> Decimal:
    """构造 Decimal（测试里禁止 float 字面量）。"""
    return Decimal(value)


class TestIsTerminal:
    @pytest.mark.parametrize("state", sorted(TERMINAL_STATES, key=lambda item: item.value))
    def test_终止节点判定为真(self, state: SignalState) -> None:
        assert is_terminal(state) is True

    @pytest.mark.parametrize(
        "state", [SignalState.GENERATED, SignalState.WATCHING, SignalState.ACTIVE]
    )
    def test_非终止节点判定为假(self, state: SignalState) -> None:
        assert is_terminal(state) is False

    def test_已关闭状态不是终止节点(self) -> None:
        """业务终态还要归档，不算终止 —— 信号必须有始有终。"""
        assert is_terminal(SignalState.TAKE_PROFIT) is False


class TestIsClosed:
    @pytest.mark.parametrize("state", sorted(CLOSED_STATES, key=lambda item: item.value))
    def test_业务终态判定为真(self, state: SignalState) -> None:
        assert is_closed(state) is True

    @pytest.mark.parametrize(
        "state", [SignalState.ACTIVE, SignalState.ARCHIVED, SignalState.REVIEWED]
    )
    def test_非业务终态判定为假(self, state: SignalState) -> None:
        assert is_closed(state) is False

    def test_终止节点与已关闭状态不相交(self) -> None:
        assert not (TERMINAL_STATES & CLOSED_STATES)


class TestTransitionRecord:
    def make_record(self, **overrides: object) -> TransitionRecord:
        kwargs: dict[str, object] = {
            "signal_id": "sig-001",
            "from_state": SignalState.WATCHING,
            "to_state": SignalState.ACTIVE,
            "actor": Actor.SYSTEM,
            "reason": "触发入场价 10.50",
            "at": FIXED_AT,
        }
        kwargs.update(overrides)
        return TransitionRecord(**kwargs)  # type: ignore[arg-type]

    def test_合法审计记录通过(self) -> None:
        record = self.make_record()
        assert record.signal_id == "sig-001"
        assert record.actor is Actor.SYSTEM
        assert record.payload == {}

    @pytest.mark.regression
    def test_signal_id不可为空(self) -> None:
        """★ 空 signal_id 的审计记录等于没有审计 —— v1 正是把日志存内存里丢了个干净。"""
        with pytest.raises(ValueError, match="signal_id 不可为空"):
            self.make_record(signal_id="")

    @pytest.mark.parametrize("reason", ["", "   ", "\n"])
    def test_reason不可为空(self, reason: str) -> None:
        with pytest.raises(ValueError, match="reason 不可为空"):
            self.make_record(reason=reason)

    def test_payload可携带触发快照(self) -> None:
        record = self.make_record(payload={"price": "10.50"})
        assert record.payload == {"price": "10.50"}

    def test_四种发起者均合法(self) -> None:
        for actor in Actor:
            assert self.make_record(actor=actor).actor is actor


class TestTrackingState:
    def test_必填字段保留(self) -> None:
        tracking = TrackingState(
            signal_id="sig-001",
            as_of=date(2026, 9, 5),
            last_price=d("10.5"),
            entry_price=d("10"),
            holding_days=3,
            pnl_pct=d("0.05"),
            mfe_pct=d("0.08"),
            mae_pct=d("-0.02"),
        )
        assert tracking.signal_id == "sig-001"
        assert tracking.holding_days == 3
        assert tracking.pnl_pct == d("0.05")
        assert tracking.mfe_pct == d("0.08")
        assert tracking.mae_pct == d("-0.02")

    def test_缺省项(self) -> None:
        tracking = TrackingState(
            signal_id="sig-001",
            as_of=date(2026, 9, 5),
            last_price=d("10.5"),
            entry_price=d("10"),
            holding_days=0,
            pnl_pct=d("0"),
            mfe_pct=d("0"),
            mae_pct=d("0"),
        )
        assert tracking.is_suspended is False
        assert tracking.is_limit_up is None
        assert tracking.is_limit_down is None
        assert tracking.days_to_max_holding is None


class TestExitDecision:
    def make_decision(self, **overrides: object) -> ExitDecision:
        kwargs: dict[str, object] = {
            "target_state": SignalState.STOP_LOSS,
            "reason_human": "跌破止损价 9.50，按计划卖出",
        }
        kwargs.update(overrides)
        return ExitDecision(**kwargs)  # type: ignore[arg-type]

    @pytest.mark.parametrize("state", sorted(CLOSED_STATES, key=lambda item: item.value))
    def test_业务终态均可作为退出目标(self, state: SignalState) -> None:
        assert self.make_decision(target_state=state).target_state is state

    def test_停牌可作为退出目标(self) -> None:
        assert self.make_decision(target_state=SignalState.SUSPENDED).target_state is (
            SignalState.SUSPENDED
        )

    @pytest.mark.regression
    @pytest.mark.parametrize(
        "state", [SignalState.WATCHING, SignalState.ACTIVE, SignalState.PENDING_PUSH]
    )
    def test_中间态不可作为退出目标(self, state: SignalState) -> None:
        """★ 退出规则若能把信号丢回中间态，"何时卖"就再次散落各处。"""
        with pytest.raises(ValueError, match="必须是退出类状态之一"):
            self.make_decision(target_state=state)

    def test_归档与复盘不可作为退出目标(self) -> None:
        for state in (SignalState.ARCHIVED, SignalState.REVIEWED):
            with pytest.raises(ValueError, match="必须是退出类状态之一"):
                self.make_decision(target_state=state)

    @pytest.mark.parametrize("reason_human", ["", "   "])
    def test_人话原因不可为空(self, reason_human: str) -> None:
        """★ 用户必须知道为什么让他卖。"""
        with pytest.raises(ValueError, match="reason_human 不可为空"):
            self.make_decision(reason_human=reason_human)

    def test_报错信息列出全部可选状态(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            self.make_decision(target_state=SignalState.ACTIVE)
        message = str(excinfo.value)
        assert "STOP_LOSS" in message
        assert "SUSPENDED" in message

    def test_payload可携带触发快照(self) -> None:
        decision = self.make_decision(payload={"price": "9.49"})
        assert decision.payload == {"price": "9.49"}
