"""领域层（domain）—— 纯 Python，零外部依赖。

只允许依赖：标准库 + pydantic（数据契约）。
**不得** import `adapters/`、`engines/`、`api/`、`cli/`，
**不得** import `pandas` / `requests` / `akshare` / `sqlite3` / `pyarrow` / `smtplib`。

这条边界由 CI 的 `ARCH010`（导入方向 AST 检查）+ `mypy --strict` 机械强制，不靠自觉。

> 这是 v1 崩溃的根因解药：v1 的 `src/data/` 被所有层直接引用，
> `.gitignore` 一行就把整包抽走 → 7 个模块 `ModuleNotFoundError`。
> v2 中 `data` 这个名字从源码树里彻底消失（改为 `adapters/persistence` + `var/`）。
"""

from __future__ import annotations

__all__: list[str] = []
