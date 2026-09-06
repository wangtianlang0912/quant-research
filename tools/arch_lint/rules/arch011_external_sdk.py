"""ARCH011 —— 反向导入方向：外部 SDK 只允许在 `adapters/`。

ARCH010 保证 domain 干净，ARCH011 保证**其余层也干净** ——
`engines/`、`strategies/`、`factors/`、`indicators/`、`orchestration/`、`ops/`、
`api/`、`cli/` 里都不许直接 import 数据源 SDK / HTTP 客户端 / 数据库驱动。

★ 这条规则的反面价值更大：它把"哪里可以碰外部世界"变成了一个
**可机械验证的事实**，而不是一句写在文档里的约定。
新人写 `import akshare` 时，CI 会立刻告诉他该去 adapters/。
"""

from __future__ import annotations

import ast

from tools.arch_lint.model import RuleContext, Violation
from tools.arch_lint.rules._helpers import iter_py_files
from tools.arch_lint.rules.registry import register

CODE = "ARCH011"
DESCRIPTION = "反向导入方向：外部 SDK 只允许在 adapters/"

# 模块根名 → 允许出现的路径前缀
ALLOWED_SCOPES: dict[str, tuple[str, ...]] = {
    "akshare": ("src/quant_v2/adapters/",),
    "baostock": ("src/quant_v2/adapters/",),
    "tushare": ("src/quant_v2/adapters/",),
    "requests": ("src/quant_v2/adapters/",),
    "httpx": ("src/quant_v2/adapters/",),
    "smtplib": ("src/quant_v2/adapters/",),
    "pyarrow": ("src/quant_v2/adapters/",),
    "sqlite3": ("src/quant_v2/adapters/",),
    "pandas": ("src/quant_v2/adapters/",),
    "numpy": ("src/quant_v2/adapters/",),
    "fastapi": ("src/quant_v2/api/", "src/quant_v2/adapters/"),
    "uvicorn": ("src/quant_v2/api/",),
    "apscheduler": ("src/quant_v2/orchestration/", "src/quant_v2/adapters/"),
    "typer": ("src/quant_v2/cli/",),
    # YAML 用于配置加载：适配层 + 测试脚手架 + 扫描工具
    "yaml": ("src/quant_v2/adapters/", "tests/", "tools/"),
}


@register(CODE, DESCRIPTION)
def check(ctx: RuleContext) -> list[Violation]:
    """执行 ARCH011 检查。"""
    violations: list[Violation] = []
    for doc in iter_py_files(ctx):
        tree = doc.tree
        if tree is None:
            continue

        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            else:
                continue

            for module in modules:
                root_module = module.split(".")[0]
                allowed = ALLOWED_SCOPES.get(root_module)
                if allowed is None:
                    continue
                if any(doc.rel.startswith(prefix) for prefix in allowed):
                    continue
                violations.append(
                    Violation(
                        code=CODE,
                        path=doc.rel,
                        line=node.lineno,
                        message=(
                            f"外部依赖 {root_module} 只允许在 "
                            f"{' / '.join(allowed)} 内 import：{doc.line(node.lineno).strip()}。"
                            "碰外部世界的代码请放进 adapters/，"
                            "其余层只能通过 domain/ports 的 Protocol 使用它。"
                        ),
                    )
                )
    return violations
