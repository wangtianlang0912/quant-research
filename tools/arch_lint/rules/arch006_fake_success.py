"""ARCH006 —— 禁止失败伪装成功（O-09）。

v1 的 `backtest_runner.py:78-80` 触发熔断后仍然 `return RunStatus.COMPLETED`，
于是连续 40 天的"每日成功"里混着真正的失败，
任何人看那张运行状态表都会得出"系统很稳"的错误结论。

**一个会说谎的状态字段，比没有状态字段更糟。**

## 检测

1. `except` 块内出现 `COMPLETED`（属性或字符串）
2. `if <涉及 HALTED/FAILED/SKIPPED/降级>` 的分支内出现 `COMPLETED`
"""

from __future__ import annotations

import ast

from tools.arch_lint.model import Violation
from tools.arch_lint.rules._helpers import iter_py_files, stmt_walk
from tools.arch_lint.rules.registry import register

CODE = "ARCH006"
DESCRIPTION = "禁止失败伪装成功（HALTED/FAILED 不得写成 COMPLETED）"

# 编排层与运维层
SCAN_PREFIXES: tuple[str, ...] = (
    "src/quant_v2/orchestration/",
    "src/quant_v2/ops/",
)

_FAILURE_TOKENS: tuple[str, ...] = ("HALTED", "FAILED", "SKIPPED", "DEGRADED", "降级", "降级通道")
_SUCCESS_TOKENS: tuple[str, ...] = ("COMPLETED", "COMPLETED_WITH_WARNINGS")


def _mentions(node: ast.AST, tokens: tuple[str, ...]) -> bool:
    """子树中是否提到某个 token（属性名或字符串常量）。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr in tokens:
            return True
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and any(token in child.value for token in tokens)
        ):
            return True
        if isinstance(child, ast.Name) and child.id in tokens:
            return True
    return False


@register(CODE, DESCRIPTION)
def check(ctx) -> list[Violation]:  # type: ignore[no-untyped-def]
    """执行 ARCH006 检查。"""
    violations: list[Violation] = []
    for doc in iter_py_files(ctx, *SCAN_PREFIXES):
        tree = doc.tree
        if tree is None:
            continue

        for statement in stmt_walk(tree):
            # 1) except 块内报成功
            if isinstance(statement, ast.Try):
                for handler in statement.handlers:
                    if _mentions(handler, _SUCCESS_TOKENS):
                        violations.append(
                            Violation(
                                code=CODE,
                                path=doc.rel,
                                line=handler.lineno,
                                message=(
                                    "禁止在 except 分支里报 COMPLETED："
                                    f"{doc.line(handler.lineno).strip()}。"
                                    "失败就是 FAILED，中止就是 HALTED。"
                                    "v1 反例：熔断后仍报 completed，掩盖了 40 天的真实故障。"
                                ),
                            )
                        )

            # 2) 失败分支里报成功
            if isinstance(statement, ast.If) and _mentions(statement.test, _FAILURE_TOKENS):
                branch = statement.body + statement.orelse
                if _mentions(ast.Module(body=list(branch), type_ignores=[]), _SUCCESS_TOKENS):
                    violations.append(
                        Violation(
                            code=CODE,
                            path=doc.rel,
                            line=statement.lineno,
                            message=(
                                "禁止在失败/降级分支里报 COMPLETED："
                                f"{doc.line(statement.lineno).strip()}。"
                                "状态必须如实反映结果，否则运维看板会骗人。"
                            ),
                        )
                    )
    return violations
