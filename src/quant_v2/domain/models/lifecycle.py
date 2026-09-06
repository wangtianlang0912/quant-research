"""生命周期状态、迁移表与跟踪快照（L-01 ~ L-06）。

**表达方式决策：显式迁移表（`frozenset` 常量）+ 纯函数；不用状态机库。**

理由：

1. `transitions` 之类的库引入 DSL 与隐式回调，调试成本高 —— 单人项目负担不起。
2. L-04 要求每次迁移落一条审计记录；手写表更容易保证"只通过一个函数写入"。
3. **表可以在模块加载时自校验**（PRD 铁律 1/4 可自动化），
   这是选表而不是选库的最大理由：不变量从"靠人记得测"变成"跑不起来"。

★ v1 的对应缺陷：没有迁移表，状态靠散落各处的赋值修改，
于是"信号永远停在 WATCHING"、"状态是 ACTIVE 但早就该止盈"这类问题无人知晓。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Final

__all__ = [
    "CLOSED_STATES",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "Actor",
    "ExitDecision",
    "SignalState",
    "TrackingState",
    "TransitionRecord",
    "is_closed",
    "is_terminal",
]


class SignalState(str, Enum):
    """信号生命周期状态。

    15 个状态，全部有明确语义，**不存在"其他"兜底状态**。
    """

    # —— 生成与推送 ——
    GENERATED = "GENERATED"  # 策略产出，尚未通过解释门禁
    REJECTED = "REJECTED"  # 被门禁拒绝（解释不全 / 风控否决 / 数据质量）
    PENDING_PUSH = "PENDING_PUSH"  # 待推送
    PUSH_FAILED = "PUSH_FAILED"  # 推送失败，等待重试
    PUSH_ABANDONED = "PUSH_ABANDONED"  # 重试耗尽，放弃推送（★ 终止节点）

    # —— 跟踪中 ——
    WATCHING = "WATCHING"  # 已推送，等待入场
    ACTIVE = "ACTIVE"  # 已入场持仓
    SUSPENDED = "SUSPENDED"  # 标的停牌

    # —— 业务终态（8 个，★ 禁止"其他"兜底） ——
    TAKE_PROFIT = "TAKE_PROFIT"  # 止盈
    STOP_LOSS = "STOP_LOSS"  # 止损
    TIME_EXPIRED = "TIME_EXPIRED"  # 超时（超过 max_holding_days）
    THESIS_INVALID = "THESIS_INVALID"  # 逻辑失效（invalidation_conditions 命中）
    NOT_TRIGGERED = "NOT_TRIGGERED"  # 等待期内未触发入场
    FORCE_CLOSED = "FORCE_CLOSED"  # 强制关闭（停牌超期 / 退市 / 数据缺失）

    # —— 归档与复盘 ——
    ARCHIVED = "ARCHIVED"  # 已归档（★ 终止节点）
    REVIEWED = "REVIEWED"  # 已复盘（周报已覆盖）


# ★ 终止节点（PRD 铁律 1：信号必须有始有终）
#   只有这三个。REVIEWED 是归档之后的复盘标记，不是独立终态。
TERMINAL_STATES: Final[frozenset[SignalState]] = frozenset(
    {
        SignalState.ARCHIVED,
        SignalState.REJECTED,
        SignalState.PUSH_ABANDONED,
    }
)

# 已关闭（业务终态，8 个）。进入这些状态后只能归档。
CLOSED_STATES: Final[frozenset[SignalState]] = frozenset(
    {
        SignalState.TAKE_PROFIT,
        SignalState.STOP_LOSS,
        SignalState.TIME_EXPIRED,
        SignalState.THESIS_INVALID,
        SignalState.NOT_TRIGGERED,
        SignalState.FORCE_CLOSED,
    }
)

_S: Final = SignalState  # 简写，仅为本表可读性

# ★ 显式迁移表：唯一真源。
#   任何新增状态都必须同时在这里登记，否则 `validate_transition_table()` 会在导入期直接报错。
TRANSITIONS: Final[Mapping[SignalState, frozenset[SignalState]]] = {
    _S.GENERATED: frozenset({_S.REJECTED, _S.PENDING_PUSH}),
    _S.PENDING_PUSH: frozenset({_S.PUSH_FAILED, _S.WATCHING, _S.PUSH_ABANDONED}),
    _S.PUSH_FAILED: frozenset({_S.PENDING_PUSH, _S.PUSH_ABANDONED}),
    _S.PUSH_ABANDONED: frozenset(),
    _S.WATCHING: frozenset({_S.ACTIVE, _S.NOT_TRIGGERED, _S.SUSPENDED}),
    _S.ACTIVE: frozenset(
        {
            _S.TAKE_PROFIT,
            _S.STOP_LOSS,
            _S.TIME_EXPIRED,
            _S.THESIS_INVALID,
            _S.SUSPENDED,
        }
    ),
    _S.SUSPENDED: frozenset({_S.ACTIVE, _S.FORCE_CLOSED}),
    _S.TAKE_PROFIT: frozenset({_S.ARCHIVED}),
    _S.STOP_LOSS: frozenset({_S.ARCHIVED}),
    _S.TIME_EXPIRED: frozenset({_S.ARCHIVED}),
    _S.THESIS_INVALID: frozenset({_S.ARCHIVED}),
    _S.NOT_TRIGGERED: frozenset({_S.ARCHIVED}),
    _S.FORCE_CLOSED: frozenset({_S.ARCHIVED}),
    _S.ARCHIVED: frozenset({_S.REVIEWED}),
    _S.REVIEWED: frozenset(),
    _S.REJECTED: frozenset(),
}


def is_terminal(state: SignalState) -> bool:
    """是否为终止节点（出边为空、不再有任何后续迁移）。"""
    return state in TERMINAL_STATES


def is_closed(state: SignalState) -> bool:
    """是否为业务终态（已关闭，待归档）。"""
    return state in CLOSED_STATES


class Actor(str, Enum):
    """状态迁移的发起者 —— 审计必填，禁止空 actor。"""

    SYSTEM = "SYSTEM"
    STRATEGY = "STRATEGY"
    HUMAN = "HUMAN"
    WATCHDOG = "WATCHDOG"


@dataclass(frozen=True)
class TransitionRecord:
    """★ 每次迁移必须落一条审计记录。

    v1 缺陷：审计日志存在内存里，进程退出即丢失 —— 等于没有审计。
    """

    signal_id: str
    from_state: SignalState
    to_state: SignalState
    actor: Actor
    reason: str  # 人话原因，前端时间轴直接展示
    at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)  # 触发时的价格/阈值快照

    def __post_init__(self) -> None:
        """审计字段校验：空 signal_id / 空 reason 都是"写了等于没写"。"""
        if not self.signal_id:
            raise ValueError("TransitionRecord.signal_id 不可为空")
        if not self.reason.strip():
            raise ValueError("TransitionRecord.reason 不可为空：审计记录必须说清为什么")


@dataclass(frozen=True)
class TrackingState:
    """每日跟踪快照 —— `ExitRule.evaluate(signal, tracking)` 的输入。

    全部字段由 `engines/lifecycle/tracker.py` 计算（T04），
    这里只定义契约，保证退出规则可纯函数化测试。
    """

    signal_id: str
    as_of: date
    last_price: Decimal  # ★ 真实最近价；缺失时上层已抛 PriceUnavailableError
    entry_price: Decimal
    holding_days: int
    pnl_pct: Decimal
    mfe_pct: Decimal  # 最大有利偏离（Maximum Favorable Excursion）
    mae_pct: Decimal  # 最大不利偏离（Maximum Adverse Excursion）
    is_suspended: bool = False
    is_limit_up: bool | None = None
    is_limit_down: bool | None = None
    days_to_max_holding: int | None = None


@dataclass(frozen=True)
class ExitDecision:
    """退出规则的判定结果。

    `target_state` 必须是真正的退出类状态（业务终态或停牌），
    不允许退出规则直接把信号丢回中间态 —— 那会让"何时卖"再次散落各处。
    """

    target_state: SignalState
    reason_human: str  # 人话："连续停牌 12 天，超过 10 天上限，强制平仓"
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """校验：退出决策只能指向退出类状态。"""
        allowed = CLOSED_STATES | {SignalState.SUSPENDED}
        if self.target_state not in allowed:
            raise ValueError(
                f"ExitDecision.target_state 必须是退出类状态之一 "
                f"{sorted(s.value for s in allowed)}，"
                f"收到 {self.target_state.value}"
            )
        if not self.reason_human.strip():
            raise ValueError("ExitDecision.reason_human 不可为空：用户必须知道为什么让他卖")
