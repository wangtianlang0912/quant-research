"""运行状态与 run manifest（O-05 可复现性）。

★ v1 教训：v1 的历史报告**不可复现** —— 没有 manifest，无法回溯某次运行
用的是哪份代码（git sha / 是否脏工作区）、哪份数据（指纹）、哪份配置（哈希）、什么随机种子。
于是"7 月那次回测收益 30%"这句话既无法验证也无法证伪。

v2 的做法：每次运行产出一份 manifest，`dirty == True` 时 `reproducible = False`，
报告头部强制打 `UNREPRODUCIBLE` 水印，且该次产出的信号在推送中标记"实验性产出"。

★ `RunStatus` 禁止假成功（O-09）：`FAILED` / `HALTED` / `SKIPPED` 分支里
不允许把状态写成 `COMPLETED` —— 由 `ARCH006` 静态扫描强制。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

__all__ = [
    "SUCCESS_RUN_STATUSES",
    "TERMINAL_RUN_STATUSES",
    "DatasetFingerprint",
    "GitInfo",
    "RunManifest",
    "RunStatus",
    "new_run_id",
]


class RunStatus(str, Enum):
    """作业运行状态。

    ★ 状态必须如实：v1 的 `backtest_runner.py:78-80` 触发熔断后仍然报 `completed`，
    让连续 40 天的"成功"里混着真正的失败。
    """

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"  # 完全成功，无告警
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"  # 跑完了，但有告警
    SKIPPED = "SKIPPED"  # 主动跳过（如非交易日）
    FAILED = "FAILED"  # 失败
    HALTED = "HALTED"  # 中止（数据质量门禁/熔断）—— ★ 不是成功


# 已结束的状态（RUNNING 之外）
TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
        RunStatus.SKIPPED,
        RunStatus.FAILED,
        RunStatus.HALTED,
    }
)

# 真正算"跑成了"的状态。**HALTED 不在其中**。
SUCCESS_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
    }
)


class GitInfo(BaseModel):
    """代码版本信息 —— 可复现性的第一要素。"""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    sha: str
    branch: str
    dirty: bool


class DatasetFingerprint(BaseModel):
    """单份数据的指纹（D-04）。"""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    dataset_id: str  # 如 'market=cn_a/dt=2026-09-05'
    source: str
    sha256: str
    rows: int


def new_run_id(job_name: str, started_at: datetime) -> str:
    """生成可读的 run_id。

    格式：`{job_name}-{YYYYmmddTHHMMSS}-{8位随机}`。
    人能一眼看出是哪个作业、什么时候跑的，比纯 UUID 好用；
    随机后缀保证同一秒内多次运行不冲突。
    """
    stamp = started_at.strftime("%Y%m%dT%H%M%S")
    return f"{job_name}-{stamp}-{uuid4().hex[:8]}"


class RunManifest(BaseModel):
    """一次运行的完整可复现信息（O-05）。"""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    run_id: str
    job_name: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    git: GitInfo
    data: tuple[DatasetFingerprint, ...] = ()
    config_hash: str
    seed: int
    market_profiles_hash: Mapping[str, str] = {}
    artifacts: tuple[str, ...] = ()
    error: str | None = None

    @property
    def reproducible(self) -> bool:
        """是否可复现。

        `dirty == True` 时代码不确定 → 不可复现；
        状态不在成功集合时（如 HALTED）→ 结果不完整 → 不可复现。
        """
        return (not self.git.dirty) and self.status in SUCCESS_RUN_STATUSES

    @property
    def is_finished(self) -> bool:
        """是否已结束。"""
        return self.status in TERMINAL_RUN_STATUSES

    def finish(
        self,
        status: RunStatus,
        *,
        finished_at: datetime,
        artifacts: tuple[str, ...] = (),
        error: str | None = None,
    ) -> RunManifest:
        """返回"已结束"的新 manifest（模型 frozen，返回副本）。

        Args:
            status: 结束状态。**必须如实** —— 把 HALTED 写成 COMPLETED 由 ARCH006 拦截。
            finished_at: 结束时刻。
            artifacts: 本次产出的文件路径。
            error: 失败原因（人话）。
        """
        return self.model_copy(
            update={
                "status": status,
                "finished_at": finished_at,
                "artifacts": artifacts,
                "error": error,
            }
        )
