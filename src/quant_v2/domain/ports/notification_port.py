"""通知端口（N-01 ~ N-04）。

★ v1 最触目惊心的运维事故：`NullNotificationAdapter` 吞掉了全部发送异常，
于是**连续 40 天没有任何人收到推送，而系统每天报告"推送成功"**。

v2 的三道防线：

1. **禁止 Null / NoOp 适配器**（`ARCH005` 静态扫描 + 代码评审）
2. **`validate_credentials()` 在启动时调用**，失败即 `NotificationConfigError` →
   **进程拒绝启动**（N-04）—— 宁可起不来，也不能"看起来在正常跑"
3. **每次降级都告警**（告警矩阵 + `DispatchResult.degraded`），禁止静默降级

编排层（`NotificationDispatcher`）在 `adapters/notification/dispatcher.py`（T04），
本文件只定义渠道契约与回执数据结构，使领域层不依赖任何具体渠道。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "AlertLevel",
    "DispatchResult",
    "NotificationMessage",
    "NotificationReceipt",
    "Notifier",
]


class AlertLevel(str, Enum):
    """告警级别（附录 A 告警矩阵）。"""

    INFO = "INFO"
    WARN = "WARN"
    P1 = "P1"
    P0 = "P0"


@dataclass(frozen=True)
class NotificationMessage:
    """一条待推送的消息。"""

    title: str
    body: str
    level: AlertLevel = AlertLevel.INFO
    dedup_key: str = ""  # 幂等键：重复推送同一条时用得上
    created_at: datetime | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """消息校验。"""
        if not self.title.strip():
            raise ValueError("NotificationMessage.title 不可为空")
        if not self.body.strip():
            raise ValueError("NotificationMessage.body 不可为空")


@dataclass(frozen=True)
class NotificationReceipt:
    """推送回执 —— **每条都要落 `push_receipts` 表**（N-02）。"""

    ok: bool
    channel: str
    message_id: str | None = None
    status_code: str | None = None
    error: str | None = None
    attempt: int = 1
    latency_ms: int = 0

    def __post_init__(self) -> None:
        """回执校验。"""
        if self.attempt < 1:
            raise ValueError(f"attempt 从 1 开始计数，收到 {self.attempt}")
        if not self.ok and not self.error:
            raise ValueError("失败的回执必须记录 error：没有错误信息的失败无法排查")


@dataclass(frozen=True)
class DispatchResult:
    """一次分发的总结果（含所有尝试过的回执）。"""

    ok: bool
    channel: str  # 最终成功的通道
    receipts: tuple[NotificationReceipt, ...] = ()
    degraded: bool = False  # ★ 是否发生过降级（降级必须告警）

    @property
    def attempts(self) -> int:
        """总尝试次数。"""
        return len(self.receipts)


@runtime_checkable
class Notifier(Protocol):
    """通知渠道端口。实现类放在 `adapters/notification/`（飞书 / SMTP）。"""

    channel: str

    def validate_credentials(self) -> None:
        """★ 启动时调用。失败 raise `NotificationConfigError` → **进程拒绝启动**（N-04）。

        ★ **禁止 Null / NoOp 适配器**。
        """
        ...

    def send(self, msg: NotificationMessage) -> NotificationReceipt:
        """发送。

        ★ **不得吞异常**：网络异常原样上抛，由 `NotificationDispatcher`
        负责重试与降级。吞掉异常就是 v1 那个 40 天事故的直接成因。
        """
        ...
