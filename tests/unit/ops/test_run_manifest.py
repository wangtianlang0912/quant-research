"""run_manifest 单元测试（T02.7 / O-05）。

覆盖：git 状态读取（真 git 仓库）、dirty → 不可复现、聚合指纹敏感性、落库回读。
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_v2.adapters.persistence.sqlite_store import SqliteStore
from quant_v2.ops.run_manifest import (
    GitState,
    PartitionDigest,
    build_run_manifest,
    read_git_state,
    save_manifest,
)

# 与 conftest 同口径的可复现时点
STARTED = datetime(2026, 9, 5, 7, 0, 3, tzinfo=UTC)


def _clean_git() -> GitState:
    return GitState(sha="a1b2c3d", branch="v2", dirty=False)


def _dirty_git() -> GitState:
    return GitState(sha="a1b2c3d", branch="v2", dirty=True)


def _partition(partition: str = "market=cn_a/dt=2026-09-05", sha: str = "9f2e") -> PartitionDigest:
    return PartitionDigest(partition=partition, source="baostock", sha256=sha, rows=5382)


class Test构建:
    def test_干净工作区_可复现(self):
        m = build_run_manifest(
            job_name="pre_market", git=_clean_git(), started_at=STARTED, status="COMPLETED"
        )
        assert m.reproducible is True
        payload = m.to_payload()
        assert payload["reproducible"] is True
        assert payload["git"]["dirty"] is False

    def test_脏工作区_不可复现(self):
        m = build_run_manifest(
            job_name="pre_market", git=_dirty_git(), started_at=STARTED, status="COMPLETED"
        )
        assert m.reproducible is False

    def test_run_id_时间可排序_且含随机段(self):
        m1 = build_run_manifest(
            job_name="a", git=_clean_git(), started_at=STARTED, status="RUNNING"
        )
        m2 = build_run_manifest(
            job_name="a",
            git=_clean_git(),
            started_at=STARTED,
            status="RUNNING",
            run_id=None,
        )
        assert m1.run_id.startswith("20260905T070003Z-")
        assert m1.run_id != m2.run_id  # 同秒两次构建也有随机段区分

    def test_to_payload_可JSON序列化(self):
        m = build_run_manifest(
            job_name="backtest",
            git=_clean_git(),
            started_at=STARTED,
            status="COMPLETED",
            partitions={"market=cn_a/dt=2026-09-05": _partition()},
            seed=20260905,
            artifacts=("var/reports/daily/2026-09-05.md",),
        )
        text = json.dumps(m.to_payload(), ensure_ascii=False)
        payload = json.loads(text)
        assert payload["data"]["market=cn_a/dt=2026-09-05"]["rows"] == 5382
        assert payload["seed"] == 20260905


class Test聚合指纹:
    def test_同一批分区_指纹一致(self):
        p = {"a": _partition("market=cn_a/dt=2026-09-04", sha="aa")}
        m1 = build_run_manifest(
            job_name="x", git=_clean_git(), started_at=STARTED, status="COMPLETED", partitions=p
        )
        m2 = build_run_manifest(
            job_name="x", git=_clean_git(), started_at=STARTED, status="COMPLETED", partitions=p
        )
        assert m1.data_fingerprint == m2.data_fingerprint

    def test_任一分区内容变化_聚合指纹必变(self):
        base = {"a": _partition("market=cn_a/dt=2026-09-04", sha="aa")}
        changed = {"a": _partition("market=cn_a/dt=2026-09-04", sha="bb")}
        m1 = build_run_manifest(
            job_name="x", git=_clean_git(), started_at=STARTED, status="COMPLETED", partitions=base
        )
        m2 = build_run_manifest(
            job_name="x",
            git=_clean_git(),
            started_at=STARTED,
            status="COMPLETED",
            partitions=changed,
        )
        assert m1.data_fingerprint != m2.data_fingerprint

    def test_分区集合增删_聚合指纹必变(self):
        one = {"a": _partition("market=cn_a/dt=2026-09-04", sha="aa")}
        two = {
            "a": _partition("market=cn_a/dt=2026-09-04", sha="aa"),
            "b": _partition("market=cn_a/dt=2026-09-05", sha="bb"),
        }
        m1 = build_run_manifest(
            job_name="x", git=_clean_git(), started_at=STARTED, status="COMPLETED", partitions=one
        )
        m2 = build_run_manifest(
            job_name="x", git=_clean_git(), started_at=STARTED, status="COMPLETED", partitions=two
        )
        assert m1.data_fingerprint != m2.data_fingerprint

    def test_无分区_也有确定指纹(self):
        m1 = build_run_manifest(
            job_name="x", git=_clean_git(), started_at=STARTED, status="COMPLETED"
        )
        m2 = build_run_manifest(
            job_name="x", git=_clean_git(), started_at=STARTED, status="COMPLETED"
        )
        assert m1.data_fingerprint == m2.data_fingerprint
        assert m1.data_fingerprint != ""


class Test落库:
    def test_save_manifest_写入且payload完整(self, tmp_path: Path):
        store = SqliteStore(tmp_path / "state.db")
        m = build_run_manifest(
            job_name="pre_market",
            git=_clean_git(),
            started_at=STARTED,
            finished_at=datetime(2026, 9, 5, 7, 4, 15, tzinfo=UTC),
            status="COMPLETED_WITH_WARNINGS",
            partitions={"market=cn_a/dt=2026-09-05": _partition()},
            seed=20260905,
        )
        save_manifest(store, m)
        row = store.conn.execute(
            "SELECT * FROM run_manifests WHERE run_id = ?", (m.run_id,)
        ).fetchone()
        assert row is not None
        assert row["git_sha"] == "a1b2c3d"
        assert row["dirty"] == 0
        assert row["data_fingerprint"] == m.data_fingerprint
        assert row["seed"] == 20260905
        payload = json.loads(row["payload"])
        assert payload["status"] == "COMPLETED_WITH_WARNINGS"
        store.close()

    def test_重复run_id_拒绝静默覆盖(self, tmp_path: Path):
        store = SqliteStore(tmp_path / "state.db")
        m = build_run_manifest(
            job_name="x",
            git=_clean_git(),
            started_at=STARTED,
            status="RUNNING",
            run_id="fixed-run-id",
        )
        save_manifest(store, m)
        with pytest.raises(Exception, match="UNIQUE"):
            save_manifest(store, m)
        store.close()


class TestGit状态读取:
    def _init_repo(self, repo: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)  # noqa: S607 -- 测试固定 argv，无用户输入
        subprocess.run(
            [  # noqa: S607 -- 测试固定 argv，无用户输入
                "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "--allow-empty",
                "-m",
                "init",
                "-q",
            ],
            cwd=repo,
            check=True,
        )

    def test_干净仓库(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._init_repo(repo)
        state = read_git_state(repo)
        assert len(state.sha) == 40
        assert state.dirty is False
        assert state.branch in ("master", "main")

    def test_未跟踪文件_即脏(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._init_repo(repo)
        (repo / "scratch.txt").write_text("x", encoding="utf-8")
        state = read_git_state(repo)
        assert state.dirty is True

    def test_非git目录_报错不填默认值(self, tmp_path: Path):
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(RuntimeError, match="git 命令失败"):
            read_git_state(plain)
