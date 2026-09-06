"""run_manifest —— 一次运行的可复现性档案（O-05 / D-04）。

## 为什么需要它

v1 的回测结果无法回答"你用的是哪份代码 + 哪份数据 + 哪份配置"。
v2 每次运行落一条 manifest：git 提交、工作区是否干净、各分区数据指纹、
配置哈希、随机种子。**`dirty == true` 时 `reproducible = false`**，
报告头部强制打 `UNREPRODUCIBLE` 水印（渲染层的职责，本模块只提供事实）。

## 设计要点

1. **git 状态子进程读取**：`git rev-parse` / `git status --porcelain`。
   不在 git 仓库内 → 抛错而非填 "unknown"（**不可复现的 manifest 比没有
   manifest 更危险**，因为它看起来可信）。
2. **`data_fingerprint` = 各分区指纹的聚合哈希**：单列可比较，
   分区级明细进 `payload.data`。
3. **run_id 时间可排序**：`YYYYmmddTHHMMSSZ-<uuid 前 8 位>`，
   按创建顺序扫表不需要额外索引。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from quant_v2.adapters.persistence.sqlite_store import SqliteStore, utc_now_iso
from quant_v2.domain.services.fingerprint import fingerprint_mapping

__all__ = [
    "GitState",
    "PartitionDigest",
    "RunManifest",
    "build_run_manifest",
    "read_git_state",
    "save_manifest",
]


# ============================================================
# git 状态
# ============================================================
@dataclass(frozen=True)
class GitState:
    """运行时代码版本（不可复现时宁可炸，不填默认值）。"""

    sha: str
    branch: str
    dirty: bool


def read_git_state(repo: Path) -> GitState:
    """读取仓库当前 git 状态。

    Raises:
        RuntimeError: git 不可用 / 目录不是 git 仓库 / HEAD 不存在。
    """

    def _git(*args: str) -> str:
        try:
            proc = subprocess.run(  # noqa: S603 -- 固定 argv 调 git，无 shell、无用户输入
                ["git", *args],  # noqa: S607 -- PATH 上的 git，部署机由 ops probe-sources 验证
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"git 不可用，无法生成可复现 manifest：{exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"git 命令超时（{args}），无法生成 manifest") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"git 命令失败（{args}）：{(exc.stderr or '').strip()}") from exc
        return proc.stdout.strip()

    sha = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    status = _git("status", "--porcelain")
    return GitState(sha=sha, branch=branch, dirty=bool(status))


# ============================================================
# 数据指纹聚合
# ============================================================
@dataclass(frozen=True)
class PartitionDigest:
    """一个数据分区的指纹明细（进 manifest 的 `data` 字段）。"""

    partition: str  # "market=cn_a/dt=2026-09-05"
    source: str  # baostock / akshare / partition/cn_a ...
    sha256: str
    rows: int


def _aggregate_fingerprint(partitions: dict[str, PartitionDigest]) -> str:
    """聚合指纹：sha256(按分区名排序的 "partition:sha256:rows" 行)。

    分区集合变化（增/删分区）或任一分区内容变化都会改变聚合指纹。
    """
    lines = sorted(f"{p.partition}:{p.sha256}:{p.rows}" for p in partitions.values())
    body = "\n".join(lines) if lines else "<no-data-partitions>"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ============================================================
# manifest
# ============================================================
@dataclass(frozen=True)
class RunManifest:
    """一次运行的完整档案（§4.6 形态）。"""

    run_id: str
    job_name: str
    started_at: datetime
    finished_at: datetime | None
    status: str  # RUNNING | COMPLETED | COMPLETED_WITH_WARNINGS | HALTED | FAILED
    git: GitState
    data: dict[str, PartitionDigest] = field(default_factory=dict)
    data_fingerprint: str = ""
    config_hash: str = ""
    seed: int | None = None
    artifacts: tuple[str, ...] = ()

    @property
    def reproducible(self) -> bool:
        """★ 工作区脏 = 本次运行不可复现（O-05）。"""
        return not self.git.dirty

    def to_payload(self) -> dict[str, object]:
        """JSON 可序列化形态（§4.6 `run_manifest.json` 的表内版本）。"""
        return {
            "run_id": self.run_id,
            "job_name": self.job_name,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status,
            "git": {
                "sha": self.git.sha,
                "branch": self.git.branch,
                "dirty": self.git.dirty,
            },
            "data": {
                key: {
                    "source": p.source,
                    "sha256": p.sha256,
                    "rows": p.rows,
                }
                for key, p in self.data.items()
            },
            "data_fingerprint": self.data_fingerprint,
            "config_hash": self.config_hash,
            "seed": self.seed,
            "reproducible": self.reproducible,
            "artifacts": list(self.artifacts),
        }


def build_run_manifest(
    *,
    job_name: str,
    git: GitState,
    started_at: datetime,
    status: str,
    partitions: dict[str, PartitionDigest] | None = None,
    finished_at: datetime | None = None,
    config_hash: str = "",
    seed: int | None = None,
    artifacts: tuple[str, ...] = (),
    run_id: str | None = None,
) -> RunManifest:
    """组装 manifest（生成 run_id 与聚合数据指纹）。"""
    data = dict(partitions or {})
    return RunManifest(
        run_id=run_id or _new_run_id(started_at),
        job_name=job_name,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        git=git,
        data=data,
        data_fingerprint=_aggregate_fingerprint(data),
        config_hash=config_hash or fingerprint_mapping({}),
        seed=seed,
        artifacts=artifacts,
    )


def _new_run_id(started_at: datetime) -> str:
    stamp = started_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


# ============================================================
# 持久化
# ============================================================
def save_manifest(store: SqliteStore, manifest: RunManifest) -> None:
    """写入 `run_manifests` 表（run_id 冲突即炸 —— 重跑该用新 run_id）。"""
    payload = json.dumps(manifest.to_payload(), ensure_ascii=False)
    with store.conn:
        store.conn.execute(
            "INSERT INTO run_manifests"
            "(run_id, git_sha, dirty, data_fingerprint, config_hash, seed, payload, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                manifest.run_id,
                manifest.git.sha,
                1 if manifest.git.dirty else 0,
                manifest.data_fingerprint,
                manifest.config_hash,
                manifest.seed,
                payload,
                utc_now_iso(),
            ),
        )
