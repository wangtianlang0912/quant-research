"""SqliteStore 基座测试（T02.1）。

验收点：
- WAL 开启（T02.1 验收标准原文）
- 迁移幂等（重复 migrate 无副作用）
- 外键生效（signal_transitions -> signals）
- 告警落表
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from quant_v2.adapters.persistence.sqlite_store import SqliteStore

pytestmark = pytest.mark.unit


def test_wal开启(tmp_path: Path) -> None:
    """★ T02.1 验收标准：建表 + WAL 开启。"""
    store = SqliteStore(tmp_path / "q.db")
    mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    store.close()


def test_迁移幂等(tmp_path: Path) -> None:
    """重复 migrate 不报错、不重复应用。"""
    store = SqliteStore(tmp_path / "q.db")
    store.migrate()
    store.migrate()
    rows = store.conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
    assert rows[0] == 1  # 只有 001 一个迁移，重复调用没有多插
    store.close()


def test_全表已建(tmp_path: Path) -> None:
    """初始 schema 的全部表都在。"""
    store = SqliteStore(tmp_path / "q.db")
    names = {
        r["name"] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    expected = {
        "schema_migrations",
        "signals",
        "signal_transitions",
        "push_receipts",
        "heartbeats",
        "alerts",
        "sync_runs",
        "sync_checkpoints",
        "run_manifests",
        "data_quality_reports",
        "partition_fingerprints",
        "pit_universe",
    }
    assert expected <= names, f"缺表：{expected - names}"
    store.close()


def test_外键生效(tmp_path: Path) -> None:
    """对不存在的信号插审计行必须被外键拦下。"""
    store = SqliteStore(tmp_path / "q.db")
    with pytest.raises(sqlite3.IntegrityError), store.conn:
        store.conn.execute(
            "INSERT INTO signal_transitions(signal_id, from_state, to_state, "
            "actor, reason, at) VALUES('ghost', 'A', 'B', 'SYSTEM', 'x', '2026-01-01')"
        )
    store.close()


def test_父目录不存在时拒绝(tmp_path: Path) -> None:
    """★ 不悄悄建目录：把库建到错误位置比报错贵得多。"""
    with pytest.raises(FileNotFoundError, match="父目录不存在"):
        SqliteStore(tmp_path / "no_such_dir" / "q.db")


def test_告警落表(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "q.db")
    store.record_alert(level="P0", source="test", message="主源不可用已降级")
    row = store.conn.execute("SELECT level, source, message FROM alerts").fetchone()
    assert row["level"] == "P0"
    assert row["message"] == "主源不可用已降级"
    store.close()
