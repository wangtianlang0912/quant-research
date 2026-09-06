"""仓库端口（持久化）。

★ `LifecycleRepository` 是**唯一允许写信号状态的地方**。
每次 `apply_transition` 必须**同事务**写 `signals.state` + 一条 `signal_transitions`。

v1 缺陷对照：状态靠散落各处的赋值修改，审计日志存在内存里，
进程退出即丢失 —— 等于没有审计，事后完全无法回答"这条信号为什么停在这里"。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from quant_v2.domain.models.bar import Bar
from quant_v2.domain.models.lifecycle import Actor, SignalState, TransitionRecord
from quant_v2.domain.models.signal import Signal
from quant_v2.domain.ports.market_data_port import BarRequest

__all__ = [
    "BarStore",
    "HeartbeatRepository",
    "LifecycleRepository",
    "PushReceiptRepository",
    "SignalRepository",
]


@runtime_checkable
class SignalRepository(Protocol):
    """信号主表读写。"""

    def save(self, signal: Signal) -> None:
        """保存（upsert）信号。"""
        ...

    def get(self, signal_id: str) -> Signal | None:
        """按 ID 取信号；不存在返回 `None`。"""
        ...

    def list_open(self, *, as_of: date) -> Sequence[Signal]:
        """列出**非终止状态**的信号（需要继续跟踪的）。"""
        ...

    def list_by_state(self, state: SignalState) -> Sequence[Signal]:
        """按状态列信号。"""
        ...


@runtime_checkable
class LifecycleRepository(Protocol):
    """★ 唯一允许写状态的地方。"""

    def apply_transition(
        self,
        signal_id: str,
        to_state: SignalState,
        *,
        actor: Actor,
        reason: str,
        payload: Mapping[str, Any] | None = None,
        expected_from: SignalState | None = None,
    ) -> TransitionRecord:
        """应用一次状态迁移（同事务写状态 + 落审计）。

        Args:
            signal_id: 信号 ID。
            to_state: 目标状态。
            actor: 发起者（审计必填）。
            reason: 人话原因（审计必填）。
            payload: 触发时的价格/阈值快照。
            expected_from: 乐观并发；实际 from 与之不符则抛 `IllegalTransitionError`。

        Returns:
            落库的 `TransitionRecord`。
        """
        ...

    def history(self, signal_id: str) -> Sequence[TransitionRecord]:
        """某信号的全部迁移历史（按时间升序）。"""
        ...

    def find_orphans(self, *, as_of: date, buffer_days: int = 5) -> Sequence[Signal]:
        """★ 孤儿巡检（L-08）：非终止状态 且 超过 `max_holding_days + buffer`。

        孤儿信号就是"推荐出去就没下文了" —— 它是 v2 第二条一等需求的直接反例，
        因此巡检是每日任务的**强制步骤**，不允许跳过。
        """
        ...


@runtime_checkable
class BarStore(Protocol):
    """行情存储（Parquet，按日分区幂等覆盖 D-11）。"""

    def save_bars(self, bars: Sequence[Bar]) -> None:
        """写入 bars；同 `dt=` 分区**覆盖写**（幂等）。"""
        ...

    def load_bars(self, req: BarRequest) -> Sequence[Bar]:
        """按请求读 bars。"""
        ...

    def fingerprint_of(self, market: str, day: date) -> str:
        """该分区的数据指纹（D-04 / D-11 幂等验收）。"""
        ...


@runtime_checkable
class PushReceiptRepository(Protocol):
    """推送回执存储（N-02 成功率统计）。"""

    def save(self, receipt: Any) -> None:
        """落一条回执。

        ★ 参数类型用 `Any`：回执实体在 T04 由适配层定义，
        领域层不引入渠道专属字段。
        """
        ...

    def success_rate(self, day: date) -> float:
        """当日推送成功率。

        ★ 返回 `float` 是**唯一允许的浮点出口**：这是统计展示值，
        不参与任何金额计算（ARCH013 只约束金额/价格路径）。
        """
        ...


@runtime_checkable
class HeartbeatRepository(Protocol):
    """心跳存储（N-03 自杀式心跳）。"""

    def expect(self, job_name: str, scheduled_date: date, *, expected_by: datetime) -> None:
        """登记"预期心跳"（任务启动即写入，不等任务结束）。

        ★ 自杀式心跳的核心：**启动即上报**。
        如果等任务成功结束才上报，那么任务一挂就什么都没有 ——
        正是 v1 那种"跑了 40 天没人发现"的状态。
        """
        ...

    def mark_finished(self, job_name: str, scheduled_date: date, *, run_id: str) -> None:
        """标记完成。"""
        ...

    def missing(self, *, as_of: date) -> Sequence[Any]:
        """列出缺失/超时的心跳（watchdog 每日检查）。"""
        ...
