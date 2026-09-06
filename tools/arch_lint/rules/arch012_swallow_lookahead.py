"""ARCH012 —— 禁止吞掉未来函数异常。

`LookaheadViolationError` 是 SafeSeries 抛出的"你拿到了未来数据"。
这个错误的严重之处在于：**它不会让程序崩溃，只会让回测收益虚高**。
一个用了未来函数的策略在回测里能轻松做到年化 200%，
而它上线后唯一的确定结果就是亏钱。

因此引擎**捕获它之后继续执行**是不可接受的 ——
捕获后必须停止本次运行（或至少把该信号标记为不可用并告警）。

## 检测

`src/quant_v2/engines/` 与 `src/quant_v2/orchestration/` 内：

1. `except LookaheadViolationError` 之后是 `pass` / `continue` / 空体
2. 任何 `except` 的处理体为空（宁可严格：这两个目录不该有吞异常的写法）
"""

from __future__ import annotations

import ast

from tools.arch_lint.model import Violation
from tools.arch_lint.rules._helpers import is_empty_body, iter_py_files
from tools.arch_lint.rules.registry import register

CODE = "ARCH012"
DESCRIPTION = "禁止吞掉未来函数异常（LookaheadViolationError）"

SCAN_PREFIXES: tuple[str, ...] = (
    "src/quant_v2/engines/",
    "src/quant_v2/orchestration/",
)

_LOOKAHEAD_NAMES: frozenset[str] = frozenset({"LookaheadViolationError"})


def _handler_type_names(handler: ast.ExceptHandler) -> set[str]:
    """异常处理器捕获的类型名集合。"""
    if handler.type is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(handler.type):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _swallows(body: list[ast.stmt]) -> bool:
    """处理体是否"吞掉"异常。"""
    if is_empty_body(body):
        return True
    return all(isinstance(stmt, ast.Continue) for stmt in body)


@register(CODE, DESCRIPTION)
def check(ctx) -> list[Violation]:  # type: ignore[no-untyped-def]
    """执行 ARCH012 检查。"""
    violations: list[Violation] = []
    for doc in iter_py_files(ctx, *SCAN_PREFIXES):
        tree = doc.tree
        if tree is None:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue

            caught = _handler_type_names(node)
            if caught & _LOOKAHEAD_NAMES and _swallows(node.body):
                violations.append(
                    Violation(
                        code=CODE,
                        path=doc.rel,
                        line=node.lineno,
                        message=(
                            "禁止吞掉 LookaheadViolationError："
                            f"{doc.line(node.lineno).strip()}。"
                            "捕获后继续会让回测用上未来数据 —— "
                            "收益虚高，上线必亏。必须停止本次运行并告警。"
                        ),
                    )
                )
                continue

            if _swallows(node.body):
                handled = ast.unparse(node.type) if node.type is not None else "裸 except"
                violations.append(
                    Violation(
                        code=CODE,
                        path=doc.rel,
                        line=node.lineno,
                        message=(
                            f"引擎/编排层禁止吞异常：except {handled} 的处理体为空。"
                            "异常必须转成告警 + 明确的 RunStatus（如 FAILED / HALTED）。"
                        ),
                    )
                )
    return violations
