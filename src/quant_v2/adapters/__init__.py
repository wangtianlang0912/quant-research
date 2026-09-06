"""适配层 —— **唯一允许碰外部世界的地方**。

只有 `adapters/` 可以出现 `import akshare / requests / smtplib / sqlite3 / pyarrow / yaml`
这类 I/O 依赖（由 `ARCH011` 静态扫描机械强制）。

领域层与引擎层只依赖 `domain/ports` 里的 Protocol，
因此换掉一个数据源、换掉一个通知渠道，都不需要动引擎与策略。
"""

from __future__ import annotations

__all__: list[str] = []
