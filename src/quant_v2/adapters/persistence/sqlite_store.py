"""SQLite 存储基座：连接工厂 + 迁移执行器（T02.1）。

★ 只负责"小数据"：信号 / 审计 / 心跳 / 回执 / 告警 / 检查点 / manifest。
行情大数据走 Parquet（`parquet_bar_store.py`），绝不进 SQLite。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

__all__ = ["SqliteStore", "utc_now_iso"]


def utc_now_iso() -> str:
    """当前 UTC 时间的 ISO8601 字符串（全库统一时间口径）。"""
    return datetime.now(UTC).isoformat()


class SqliteStore:
    """SQLite 连接持有者 + 迁移执行器。

    用法::

        store = SqliteStore(Path("var/quant_v2.db"))
        store.migrate()
        with store.conn:                # 事务块
            store.conn.execute(...)
    """

    def __init__(self, path: Path) -> None:
        """打开（必要时创建）数据库并启用 WAL 与外键。

        Args:
            path: 数据库文件路径；父目录必须已存在（由调用方创建，
                  避免存储层悄悄建目录掩盖配置错误）。
        """
        if not path.parent.exists():
            raise FileNotFoundError(f"数据库父目录不存在：{path.parent}（应由调用方显式创建）")
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        # ★ WAL：验收标准之一。读写不互斥，任务写库时人肉查库不会被锁。
        self.conn.execute("PRAGMA journal_mode=WAL")
        # ★ 外键：signal_transitions -> signals 的引用完整性靠它。
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    # ----------------------------------------------------------
    # 迁移
    # ----------------------------------------------------------
    def migrate(self) -> None:
        """按版本号顺序执行 `migrations/*.sql`，已应用的跳过。

        幂等：重复调用无副作用。SQL 文件内也全部用 `IF NOT EXISTS` 双保险。
        """
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    INTEGER PRIMARY KEY,
                name       TEXT    NOT NULL,
                applied_at TEXT    NOT NULL
            )
            """
        )
        applied = {
            int(row["version"])
            for row in self.conn.execute("SELECT version FROM schema_migrations")
        }

        for sql_path in _migration_files():
            version = int(sql_path.stem.split("_", maxsplit=1)[0])
            if version in applied:
                continue
            sql = sql_path.read_text(encoding="utf-8")
            with self.conn:  # 每个迁移一个事务：要么全成功要么全回滚
                self.conn.executescript(sql)
                self.conn.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES(?, ?, ?)",
                    (version, sql_path.stem, utc_now_iso()),
                )

    def close(self) -> None:
        """关闭连接（WAL 文件由 SQLite 自动管理）。"""
        self.conn.close()

    # ----------------------------------------------------------
    # 便捷写入口
    # ----------------------------------------------------------
    def record_alert(self, *, level: str, source: str, message: str, payload: str = "{}") -> None:
        """落一条告警（D-10：降级/门禁失败禁止静默）。"""
        with self.conn:
            self.conn.execute(
                "INSERT INTO alerts(level, source, message, payload, created_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (level, source, message, payload, utc_now_iso()),
            )


def _migration_files() -> list[Path]:
    """包内 `migrations/` 下的 .sql 文件，按文件名（版本号）升序。

    ★ 通过 `importlib.resources` 定位：包被 wheel 安装后迁移文件随包分发，
    不依赖仓库布局。
    """
    base = resources.files("quant_v2.adapters.persistence") / "migrations"
    files = [entry for entry in base.iterdir() if entry.name.endswith(".sql")]
    return sorted(
        (Path(str(entry)) for entry in files),
        key=lambda p: p.name,
    )
