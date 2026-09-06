"""生命周期状态机（纯逻辑，L-01）—— 显式迁移表 + 自校验。

**为什么不用状态机库**：见 `domain/models/lifecycle.py` 的模块说明。
一句话：表可以在**导入期**自校验，把"不变量靠人记得测"变成"跑不起来"。

## 自校验规则

1. `TRANSITIONS` 覆盖 `SignalState` 的全部成员（新增状态忘了登记 → 导入即失败）
2. 每个 `CLOSED_STATES` 成员**有且仅有** `ARCHIVED` 一条出边
3. 终止节点的出边只允许是"复盘标记边"（见下）
4. 全部状态从 `GENERATED` 可达（无不可达状态）
5. 除 `GENERATED` 外无孤儿状态（每个状态都有入边）
6. 所有出边指向的状态都已登记

### ★ 与设计文档 §4.4 的一处冲突及裁决

设计稿同时要求：

- `TRANSITIONS[ARCHIVED] = frozenset({REVIEWED})`（迁移表里有这条边）
- "每个 `TERMINAL_STATES` 成员出边为空"（自校验规则）

而 `ARCHIVED ∈ TERMINAL_STATES`，两者直接矛盾。

**裁决：保留 `ARCHIVED → REVIEWED` 这条边**，把自校验规则改为：

- 终止节点的出边必须全部属于 `POST_TERMINAL_EDGES`（= `{(ARCHIVED, REVIEWED)}`）
- `POST_TERMINAL_EDGES` 的目标状态（`REVIEWED`）自身出边必须为空

理由：`ARCHIVED → REVIEWED` 是**复盘标记**，不产生任何交易动作，
业务上信号在 `ARCHIVED` 就已经"有始有终"了。
而这条规则仍然能抓住真正的错误 —— 比如有人加了 `ARCHIVED → ACTIVE`
或 `PUSH_ABANDONED → PENDING_PUSH` 之外的复活边。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Final

from quant_v2.domain.errors import IllegalTransitionError
from quant_v2.domain.models.lifecycle import (
    CLOSED_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    Actor,
    SignalState,
    TransitionRecord,
)

__all__ = [
    "POST_TERMINAL_EDGES",
    "all_edges",
    "allowed_transitions",
    "can_transition",
    "reachable_states",
    "record",
    "require_transition",
    "validate_transition_table",
]

# ★ 复盘标记边：从终止节点出发、但不产生任何交易动作的边。
#   自校验允许终止节点有且只有这类出边（见模块 docstring 的冲突裁决）。
POST_TERMINAL_EDGES: Final[frozenset[tuple[SignalState, SignalState]]] = frozenset(
    {(SignalState.ARCHIVED, SignalState.REVIEWED)}
)


def allowed_transitions(state: SignalState) -> frozenset[SignalState]:
    """该状态允许的下一跳集合。

    Raises:
        KeyError: 状态未登记在迁移表中（自校验保证不会发生，这里再兜一层防御）。
    """
    return TRANSITIONS[state]


def can_transition(from_state: SignalState, to_state: SignalState) -> bool:
    """是否允许该迁移（不抛异常，供前端判断按钮可用性等场景）。"""
    return to_state in TRANSITIONS[from_state]


def require_transition(from_state: SignalState, to_state: SignalState) -> None:
    """校验迁移合法性；非法即抛 `IllegalTransitionError`。

    ★ 禁止静默通过：v1 没有迁移表，状态靠散落各处的赋值改，
    于是"信号永远停在 WATCHING"无人知晓。
    """
    allowed = TRANSITIONS[from_state]
    if to_state not in allowed:
        readable = sorted(state.value for state in allowed)
        raise IllegalTransitionError(
            f"非法的生命周期迁移：{from_state.value} -> {to_state.value}。"
            f"{from_state.value} 只允许迁移到 {readable}"
        )


def record(
    signal_id: str,
    from_state: SignalState,
    to_state: SignalState,
    *,
    actor: Actor,
    reason: str,
    at: datetime,
    payload: Mapping[str, object] | None = None,
) -> TransitionRecord:
    """★ 校验 + 生成审计记录 —— 迁移的唯一入口（纯逻辑层）。

    持久化由 `LifecycleRepository.apply_transition()` 负责（同事务写状态 + 落审计）。
    本函数不碰 I/O，因此可以被完全单测覆盖。

    Args:
        signal_id: 信号 ID。
        from_state: 起始状态。
        to_state: 目标状态。
        actor: 发起者（审计必填）。
        reason: 人话原因（审计必填，前端时间轴直接展示）。
        at: 发生时刻。
        payload: 触发时的价格/阈值快照。

    Raises:
        IllegalTransitionError: 迁移非法。
    """
    require_transition(from_state, to_state)
    return TransitionRecord(
        signal_id=signal_id,
        from_state=from_state,
        to_state=to_state,
        actor=actor,
        reason=reason,
        at=at,
        payload=dict(payload) if payload is not None else {},
    )


def all_edges() -> tuple[tuple[SignalState, SignalState], ...]:
    """迁移表的全部合法边（供"全部边有用例"的守卫测试使用）。"""
    edges: list[tuple[SignalState, SignalState]] = []
    for from_state in SignalState:
        for to_state in sorted(TRANSITIONS[from_state], key=lambda s: s.value):
            edges.append((from_state, to_state))
    return tuple(edges)


def reachable_states(start: SignalState = SignalState.GENERATED) -> frozenset[SignalState]:
    """从 `start` 出发可达的全部状态（BFS）。"""
    seen: set[SignalState] = {start}
    queue: list[SignalState] = [start]
    while queue:
        current = queue.pop()
        for nxt in TRANSITIONS[current]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return frozenset(seen)


def _check_all_states_registered() -> list[str]:
    """不变量 1：每个状态都必须登记在迁移表里。

    漏登记的状态在 `TRANSITIONS.get()` 下会静默变成"无出边的死节点"，
    信号进去就再也出不来 —— 正是 v1 那种"跑了 40 天没人发现"的温床。
    """
    return [
        f"状态 {state.value} 未登记在 TRANSITIONS 中"
        for state in SignalState
        if state not in TRANSITIONS
    ]


def _check_closed_states_exit_to_archived() -> list[str]:
    """不变量 2：业务终态有且仅有 `ARCHIVED` 一条出边。

    业务终态（止盈/止损/超时/…）意味着这笔信号在业务上已经结束，
    唯一还能做的事是归档。给它留第二条出边，就等于开了个后门。
    """
    problems: list[str] = []
    for state in sorted(CLOSED_STATES, key=lambda s: s.value):
        out_edges = TRANSITIONS.get(state, frozenset())
        if out_edges != frozenset({SignalState.ARCHIVED}):
            problems.append(
                f"业务终态 {state.value} 的出边必须恰好是 {{ARCHIVED}}，"
                f"实际为 {sorted(s.value for s in out_edges)}"
            )
    return problems


def _check_terminal_states_only_review_edges() -> list[str]:
    """不变量 3：终止节点只能走"复盘标记边"，且标记边的终点必须是叶子。

    ★ v1 铁律：信号必须有始有终。终止节点若还能跳回 `WATCHING`，
    就等于允许一条信号无限复活，"跟踪中的信号数"会永远降不下来。
    """
    problems: list[str] = []
    for state in sorted(TERMINAL_STATES, key=lambda s: s.value):
        for to_state in sorted(TRANSITIONS.get(state, frozenset()), key=lambda s: s.value):
            if (state, to_state) not in POST_TERMINAL_EDGES:
                problems.append(f"终止节点 {state.value} 不允许有业务出边 -> {to_state.value}")

    ordered = sorted(POST_TERMINAL_EDGES, key=lambda e: (e[0].value, e[1].value))
    for from_state, to_state in ordered:
        if TRANSITIONS.get(to_state, frozenset()):
            problems.append(
                f"复盘标记边 {from_state.value} -> {to_state.value} 的终点必须是叶子节点，"
                f"但 {to_state.value} 仍有出边"
            )
    return problems


def _check_no_unreachable_states() -> list[str]:
    """不变量 4：不存在从 `GENERATED` 出发不可达的状态。

    不可达状态 = 死代码。它不会报错，只会让人以为"系统支持这个状态"。
    """
    unreachable = set(SignalState) - set(reachable_states())
    if not unreachable:
        return []
    return [f"存在不可达状态：{sorted(s.value for s in unreachable)}"]


def _check_no_orphan_states() -> list[str]:
    """不变量 5：除起点 `GENERATED` 外，每个状态都必须有入边。

    没有入边的状态永远进不去，等价于不可达 —— 但它是另一种成因
    （写迁移表时漏了来源），所以单独校验，报错信息才指得对地方。
    """
    has_in_edge: set[SignalState] = set()
    for targets in TRANSITIONS.values():
        has_in_edge.update(targets)
    orphans = {s for s in SignalState if s not in has_in_edge and s != SignalState.GENERATED}
    if not orphans:
        return []
    return [f"存在孤儿状态（无入边）：{sorted(s.value for s in orphans)}"]


def _check_edges_target_registered_states() -> list[str]:
    """不变量 6：每条出边的终点都必须是已登记状态。"""
    problems: list[str] = []
    for from_state, targets in TRANSITIONS.items():
        for to_state in targets:
            if to_state not in TRANSITIONS:
                problems.append(f"边 {from_state.value} -> {to_state.value} 指向未登记的状态")
    return problems


# 不变量清单。新增不变量时在这里登记 —— 校验项必须是"读这段代码就能看全"的。
_INVARIANT_CHECKS = (
    _check_all_states_registered,
    _check_closed_states_exit_to_archived,
    _check_terminal_states_only_review_edges,
    _check_no_unreachable_states,
    _check_no_orphan_states,
    _check_edges_target_registered_states,
)


def validate_transition_table() -> None:
    """★ 迁移表自校验（全部不变量）。

    在模块导入时执行（见文件末尾），因此任何对迁移表的破坏都会
    **在导入期就直接崩掉**，而不是等某天夜里跑出一个诡异的信号状态。

    Raises:
        IllegalTransitionError: 任一条不变量被破坏。
    """
    problems: list[str] = []
    for check in _INVARIANT_CHECKS:
        problems.extend(check())

    if problems:
        raise IllegalTransitionError("生命周期迁移表自校验失败：\n  - " + "\n  - ".join(problems))


# ★ 导入期自校验。这是选"表"而不是选"状态机库"的最大收益：
#   不变量从"靠人记得测"变成"跑不起来"。
validate_transition_table()
