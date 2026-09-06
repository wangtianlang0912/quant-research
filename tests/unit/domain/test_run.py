"""运行状态与 run manifest（O-05 可复现性 / O-09 禁止假成功）。

★ v1 教训：`backtest_runner.py:78-80` 触发熔断后仍然报 `completed`，
让连续 40 天的"成功"里混着真正的失败。

这里锁死两条：

1. `dirty == True` 或状态不在成功集合 → `reproducible == False`
2. `HALTED` / `FAILED` / `SKIPPED` **永远不在** `SUCCESS_RUN_STATUSES` 里
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from quant_v2.domain.models.run import (
    SUCCESS_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    DatasetFingerprint,
    GitInfo,
    RunManifest,
    RunStatus,
    new_run_id,
)

pytestmark = pytest.mark.unit

STARTED_AT = datetime(2026, 9, 5, 1, 30, 0, tzinfo=UTC)
FINISHED_AT = datetime(2026, 9, 5, 1, 45, 0, tzinfo=UTC)


def make_git(*, dirty: bool = False) -> GitInfo:
    return GitInfo(sha="a1b2c3d4e5f6", branch="main", dirty=dirty)


def make_manifest(
    *,
    status: RunStatus = RunStatus.COMPLETED,
    dirty: bool = False,
    run_id: str = "daily-scan-20260905T013000-abcdef12",
) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        job_name="daily-scan",
        status=status,
        started_at=STARTED_AT,
        finished_at=None,
        git=make_git(dirty=dirty),
        data=(
            DatasetFingerprint(
                dataset_id="market=cn_a/dt=2026-09-05",
                source="akshare",
                sha256="f" * 64,
                rows=5200,
            ),
        ),
        config_hash="c0ffee",
        seed=20260905,
    )


class TestRunStatusSets:
    @pytest.mark.regression
    def test_熔断与失败不算成功(self) -> None:
        """★ v1 的 `backtest_runner.py:78-80` 熔断后仍报 completed。

        把 HALTED / FAILED 放进成功集合，等于允许"看起来在正常跑"。
        """
        for status in (RunStatus.HALTED, RunStatus.FAILED, RunStatus.SKIPPED, RunStatus.RUNNING):
            assert status not in SUCCESS_RUN_STATUSES, f"{status.value} 不该算成功"

    def test_成功集合只含两个完成态(self) -> None:
        assert (
            frozenset({RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_WARNINGS})
            == SUCCESS_RUN_STATUSES
        )

    def test_终止集合含全部非运行中状态(self) -> None:
        expected = frozenset(RunStatus) - {RunStatus.RUNNING}
        assert expected == TERMINAL_RUN_STATUSES

    def test_运行中不在终止集合(self) -> None:
        assert RunStatus.RUNNING not in TERMINAL_RUN_STATUSES


class TestNewRunId:
    def test_格式为作业名加时间戳加随机后缀(self) -> None:
        run_id = new_run_id("daily-scan", STARTED_AT)
        assert re.fullmatch(r"daily-scan-20260905T013000-[0-9a-f]{8}", run_id), run_id

    def test_同一秒内两次运行不冲突(self) -> None:
        """随机后缀的意义：同一秒重跑两次必须拿到不同 run_id。"""
        assert new_run_id("daily-scan", STARTED_AT) != new_run_id("daily-scan", STARTED_AT)

    def test_作业名进入run_id便于人眼定位(self) -> None:
        assert new_run_id("weekly-review", STARTED_AT).startswith("weekly-review-")


class TestReproducible:
    def test_干净工作区且完全成功即可复现(self) -> None:
        assert make_manifest().reproducible is True

    def test_带告警完成也算可复现(self) -> None:
        manifest = make_manifest(status=RunStatus.COMPLETED_WITH_WARNINGS)
        assert manifest.reproducible is True

    @pytest.mark.regression
    def test_脏工作区不可复现(self) -> None:
        """★ 代码不确定 → 结论无法验证也无法证伪。"""
        assert make_manifest(dirty=True).reproducible is False

    @pytest.mark.regression
    def test_熔断不可复现(self) -> None:
        """★ 结果不完整 → 不可复现（v1 把熔断报成 completed 的直接反例）。"""
        assert make_manifest(status=RunStatus.HALTED).reproducible is False

    def test_失败与跳过不可复现(self) -> None:
        assert make_manifest(status=RunStatus.FAILED).reproducible is False
        assert make_manifest(status=RunStatus.SKIPPED).reproducible is False

    def test_运行中不可复现(self) -> None:
        assert make_manifest(status=RunStatus.RUNNING).reproducible is False


class TestIsFinished:
    def test_运行中未结束(self) -> None:
        assert make_manifest(status=RunStatus.RUNNING).is_finished is False

    @pytest.mark.parametrize("status", sorted(TERMINAL_RUN_STATUSES, key=lambda item: item.value))
    def test_其余状态均已结束(self, status: RunStatus) -> None:
        assert make_manifest(status=status).is_finished is True


class TestFinish:
    def test_返回新的已结束manifest(self) -> None:
        finished = make_manifest(status=RunStatus.RUNNING).finish(
            RunStatus.COMPLETED,
            finished_at=FINISHED_AT,
            artifacts=("var/reports/2026-09-05.md",),
        )
        assert finished.status is RunStatus.COMPLETED
        assert finished.finished_at == FINISHED_AT
        assert finished.artifacts == ("var/reports/2026-09-05.md",)
        assert finished.error is None

    def test_原manifest不被就地改写(self) -> None:
        """frozen：跑完的作业留下的记录必须是当次运行的真实快照。"""
        original = make_manifest(status=RunStatus.RUNNING)
        original.finish(RunStatus.COMPLETED, finished_at=FINISHED_AT)
        assert original.status is RunStatus.RUNNING
        assert original.finished_at is None

    def test_失败时携带人话错误(self) -> None:
        finished = make_manifest(status=RunStatus.RUNNING).finish(
            RunStatus.FAILED, finished_at=FINISHED_AT, error="数据源 akshare 连续 3 次超时"
        )
        assert finished.status is RunStatus.FAILED
        assert finished.error == "数据源 akshare 连续 3 次超时"

    def test_熔断如实落库(self) -> None:
        """★ 状态必须如实：把 HALTED 写成 COMPLETED 由 ARCH006 拦截，这里锁死写入路径。"""
        finished = make_manifest(status=RunStatus.RUNNING).finish(
            RunStatus.HALTED, finished_at=FINISHED_AT, error="数据质量门禁未通过"
        )
        assert finished.status is RunStatus.HALTED
        assert finished.reproducible is False


class TestFingerprint:
    def test_数据指纹字段保留(self) -> None:
        manifest = make_manifest()
        (fingerprint,) = manifest.data
        assert fingerprint.dataset_id == "market=cn_a/dt=2026-09-05"
        assert fingerprint.source == "akshare"
        assert fingerprint.sha256 == "f" * 64
        assert fingerprint.rows == 5200

    def test_默认无数据集指纹(self) -> None:
        manifest = RunManifest(
            run_id="r",
            job_name="j",
            status=RunStatus.COMPLETED,
            started_at=STARTED_AT,
            git=make_git(),
            config_hash="c",
            seed=1,
        )
        assert manifest.data == ()
        assert manifest.artifacts == ()
        assert manifest.error is None
        assert manifest.market_profiles_hash == {}
