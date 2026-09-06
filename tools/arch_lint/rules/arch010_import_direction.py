"""ARCH010 —— 导入方向：`domain/` 不得依赖外层。

★ 这是 v1 崩溃的根因解药。

v1 的 `src/data/` 被所有层直接引用，`.gitignore` 一行就把整包抽走
→ 7 个模块 `ModuleNotFoundError`。根本问题不是那行 gitignore，
而是**领域层依赖了本该在适配层的东西**。

v2：`domain/` 只依赖标准库 + pydantic。
它不知道 `adapters/` 存在，也不知道引擎、API、CLI 存在。

## 检查

`src/quant_v2/domain/**` 中出现以下任一 import 即违规：

- 项目内的 `quant_v2.{adapters,engines,strategies,api,cli,orchestration,ops}`
- 外部依赖：`pandas` / `numpy` / `requests` / `httpx` / `akshare` / `baostock`
  / `sqlite3` / `pyarrow` / `smtplib` / `yaml` / `fastapi` / `apscheduler`
"""

from __future__ import annotations

import ast

from tools.arch_lint.model import Violation
from tools.arch_lint.rules._helpers import iter_py_files
from tools.arch_lint.rules.registry import register

CODE = "ARCH010"
DESCRIPTION = "导入方向：domain/ 不得依赖外层"

SCAN_PREFIXES: tuple[str, ...] = ("src/quant_v2/domain/",)

FORBIDDEN_PROJECT_MODULES: tuple[str, ...] = (
    "quant_v2.adapters",
    "quant_v2.engines",
    "quant_v2.strategies",
    "quant_v2.api",
    "quant_v2.cli",
    "quant_v2.orchestration",
    "quant_v2.ops",
)

FORBIDDEN_THIRD_PARTY: tuple[str, ...] = (
    "pandas",
    "numpy",
    "requests",
    "httpx",
    "akshare",
    "baostock",
    "sqlite3",
    "pyarrow",
    "smtplib",
    "yaml",
    "fastapi",
    "apscheduler",
)


def _imported(node: ast.AST) -> tuple[str, int] | None:
    """从 import 语句里取出被导入的模块名。"""
    if isinstance(node, ast.Import):
        for alias in node.names:
            return (alias.name, node.lineno)
    if isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            return None  # 相对导入的解析依赖 __package__，静态判定不可靠
        if node.module:
            return (node.module, node.lineno)
    return None


@register(CODE, DESCRIPTION)
def check(ctx) -> list[Violation]:  # type: ignore[no-untyped-def]
    """执行 ARCH010 检查。"""
    violations: list[Violation] = []
    for doc in iter_py_files(ctx, *SCAN_PREFIXES):
        tree = doc.tree
        if tree is None:
            continue

        for node in ast.walk(tree):
            imported = _imported(node)
            if imported is None:
                continue
            module, lineno = imported

            for forbidden in FORBIDDEN_PROJECT_MODULES:
                if module == forbidden or module.startswith(f"{forbidden}."):
                    violations.append(
                        Violation(
                            code=CODE,
                            path=doc.rel,
                            line=lineno,
                            message=(
                                f"domain 层不得 import {module}：{doc.line(lineno).strip()}。"
                                "领域层只依赖标准库 + pydantic；"
                                "需要外部能力请定义 Protocol（domain/ports）由适配层实现。"
                            ),
                        )
                    )

            for forbidden in FORBIDDEN_THIRD_PARTY:
                if module == forbidden or module.startswith(f"{forbidden}."):
                    violations.append(
                        Violation(
                            code=CODE,
                            path=doc.rel,
                            line=lineno,
                            message=(
                                f"domain 层不得 import 外部依赖 {module}："
                                f"{doc.line(lineno).strip()}。"
                                "领域层必须零外部依赖 —— 这是 Port/Adapter 边界的机械化保证。"
                            ),
                        )
                    )
    return violations
