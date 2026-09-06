"""生命周期状态机（L-01）。

★ 这是 v1「信号永远停在 WATCHING、跑了 40 天没人知道」的根治验收。

四条硬要求：

1. 迁移表自校验在**导入期**执行 —— 表被改坏，import 就崩
2. 全部合法边都有用例（新增一条边，测试立刻要求补用例）
3. 1000 组随机非法迁移**全部**抛异常（一个漏网就是后门）
4. 终止节点不得复活（信号必须有始有终）
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from quant_v2.domain.errors import IllegalTransitionError
from quant_v2.domain.models.lifecycle import (
    CLOSED_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    Actor,
    SignalState,
)
from quant_v2.domain.services.lifecycle_machine import (
    POST_TERMINAL_EDGES,
    all_edges,
    allowed_transitions,
    can_transition,
    reachable_states,
    record,
    require_transition,
    validate_transition_table,
)

pytestmark = pytest.mark.unit

FIXED_AT = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)


class TestSelfValidation:
    def test_导入期自校验通过(self) -> None:
        """导入本模块时已执行过一次；这里再显式跑一遍，确认幂等。"""
        validate_transition_table()

    def test_全部状态都已登记(self) -> None:
        for state in SignalState:
            assert state in TRANSITIONS, f"{state.value} 未登记在迁移表中"

    def test_业务终态只通向归档(self) -> None:
        for state in CLOSED_STATES:
            assert allowed_transitions(state) == frozenset({SignalState.ARCHIVED}), (
                f"{state.value} 的出边必须是 {{ARCHIVED}}"
            )

    def test_终止节点不得复活(self) -> None:
        """★ PRD 铁律：信号必须有始有终。

        终止节点若还能跳回 WATCHING / ACTIVE，跟踪中的信号数就永远降不下来。
        """
        resurrectable = {SignalState.WATCHING, SignalState.ACTIVE, SignalState.PENDING_PUSH}
        for state in TERMINAL_STATES:
            outgoing = allowed_transitions(state)
            assert not (outgoing & resurrectable), (
                f"终止节点 {state.value} 竟然能回到活跃状态：{sorted(s.value for s in outgoing)}"
            )

    def test_终止节点的出边只能是复盘标记边(self) -> None:
        for state in TERMINAL_STATES:
            for target in allowed_transitions(state):
                assert (state, target) in POST_TERMINAL_EDGES, (
                    f"终止节点 {state.value} 出现了非复盘标记出边 -> {target.value}"
                )

    def test_无不可达状态(self) -> None:
        unreachable = set(SignalState) - set(reachable_states())
        assert unreachable == set(), f"存在不可达状态：{sorted(s.value for s in unreachable)}"

    def test_复盘标记边的终点是叶子(self) -> None:
        for _, target in POST_TERMINAL_EDGES:
            assert allowed_transitions(target) == frozenset(), (
                f"复盘标记边终点 {target.value} 应无出边"
            )


class TestEdgeCoverage:
    """★ "全部边有用例" —— 迁移表新增一条边，这个测试会立刻失败要求补用例。"""

    # 人工登记的"每条边对应哪个测试"清单。
    # 与 all_edges() 做集合比对，漏一条就是失败。
    COVERED_EDGES: frozenset[tuple[SignalState, SignalState]] = frozenset(
        {
            # —— 生成与推送 ——
            (SignalState.GENERATED, SignalState.PENDING_PUSH),
            (SignalState.GENERATED, SignalState.REJECTED),
            (SignalState.PENDING_PUSH, SignalState.WATCHING),
            (SignalState.PENDING_PUSH, SignalState.PUSH_FAILED),
            (SignalState.PENDING_PUSH, SignalState.PUSH_ABANDONED),
            (SignalState.PUSH_FAILED, SignalState.PENDING_PUSH),
            (SignalState.PUSH_FAILED, SignalState.PUSH_ABANDONED),
            # —— 跟踪中 ——
            (SignalState.WATCHING, SignalState.ACTIVE),
            (SignalState.WATCHING, SignalState.SUSPENDED),
            (SignalState.WATCHING, SignalState.NOT_TRIGGERED),
            (SignalState.ACTIVE, SignalState.SUSPENDED),
            (SignalState.ACTIVE, SignalState.TAKE_PROFIT),
            (SignalState.ACTIVE, SignalState.STOP_LOSS),
            (SignalState.ACTIVE, SignalState.TIME_EXPIRED),
            (SignalState.ACTIVE, SignalState.THESIS_INVALID),
            (SignalState.SUSPENDED, SignalState.ACTIVE),
            (SignalState.SUSPENDED, SignalState.FORCE_CLOSED),
            # —— 业务终态 → 归档（8 条） ——
            (SignalState.TAKE_PROFIT, SignalState.ARCHIVED),
            (SignalState.STOP_LOSS, SignalState.ARCHIVED),
            (SignalState.TIME_EXPIRED, SignalState.ARCHIVED),
            (SignalState.THESIS_INVALID, SignalState.ARCHIVED),
            (SignalState.NOT_TRIGGERED, SignalState.ARCHIVED),
            (SignalState.FORCE_CLOSED, SignalState.ARCHIVED),
            # —— 归档 → 复盘 ——
            (SignalState.ARCHIVED, SignalState.REVIEWED),
        }
    )

    def test_登记的边与迁移表完全一致(self) -> None:
        actual = set(all_edges())
        only_in_table = sorted(f"{a.value}->{b.value}" for a, b in actual - set(self.COVERED_EDGES))
        only_in_test = sorted(f"{a.value}->{b.value}" for a, b in set(self.COVERED_EDGES) - actual)
        assert actual == set(self.COVERED_EDGES), (
            f"迁移表与用例登记不一致。\n"
            f"  迁移表有、用例没登记：{only_in_table}\n"
            f"  用例登记了、迁移表没有：{only_in_test}"
        )

    @pytest.mark.parametrize(("from_state", "to_state"), sorted(all_edges()))
    def test_每条合法边都允许迁移(self, from_state: SignalState, to_state: SignalState) -> None:
        assert can_transition(from_state, to_state)
        require_transition(from_state, to_state)  # 合法边不得抛异常


class TestIllegalTransitions:
    def test_一千组随机非法迁移全部抛异常(self) -> None:
        """★ 一个漏网的非法迁移就是一条后门。

        用固定种子保证可复现；每组都必须是**迁移表里不存在**的边。
        """
        rng = random.Random(20260905)  # noqa: S311 -- 测试用固定种子生成确定性序列，非密码用途
        states = list(SignalState)
        legal = set(all_edges())

        candidates: list[tuple[SignalState, SignalState]] = []
        while len(candidates) < 1000:
            pair = (rng.choice(states), rng.choice(states))
            if pair not in legal:
                candidates.append(pair)

        failures: list[str] = []
        for from_state, to_state in candidates:
            try:
                require_transition(from_state, to_state)
            except IllegalTransitionError:
                continue
            failures.append(f"{from_state.value}->{to_state.value}")

        assert failures == [], f"{len(failures)} 组非法迁移竟然被放行：{failures[:10]}"

    def test_自环不被允许(self) -> None:
        for state in SignalState:
            assert not can_transition(state, state), f"{state.value} 不该能迁移到自己"

    def test_非法迁移的报错信息含允许目标(self) -> None:
        with pytest.raises(IllegalTransitionError) as excinfo:
            require_transition(SignalState.ARCHIVED, SignalState.ACTIVE)
        message = str(excinfo.value)
        assert "ARCHIVED" in message and "ACTIVE" in message
        assert "REVIEWED" in message, "报错信息应告诉调用方 ARCHIVED 只能去 REVIEWED"


class TestRecord:
    def test_合法迁移生成审计记录(self) -> None:
        rec = record(
            "sig-001",
            SignalState.WATCHING,
            SignalState.ACTIVE,
            actor=Actor.SYSTEM,
            reason="触发入场价 10.50",
            at=FIXED_AT,
            payload={"price": "10.50"},
        )
        assert rec.signal_id == "sig-001"
        assert rec.from_state is SignalState.WATCHING
        assert rec.to_state is SignalState.ACTIVE
        assert rec.actor is Actor.SYSTEM
        assert rec.reason == "触发入场价 10.50"
        assert rec.payload == {"price": "10.50"}

    def test_非法迁移不生成记录(self) -> None:
        with pytest.raises(IllegalTransitionError):
            record(
                "sig-002",
                SignalState.ACTIVE,
                SignalState.PENDING_PUSH,
                actor=Actor.SYSTEM,
                reason="x",
                at=FIXED_AT,
            )

    def test_payload缺省为空字典(self) -> None:
        rec = record(
            "sig-003",
            SignalState.GENERATED,
            SignalState.REJECTED,
            actor=Actor.SYSTEM,
            reason="解释门禁未通过",
            at=FIXED_AT,
        )
        assert rec.payload == {}
