"""ARCH002 —— 禁止股数字面量。

★ 根治 v1 的 `order_pipeline.py:40`：

    quantity = Decimal("100")

于是无论单笔预算多少、股价多少，每笔都买 100 股：
股价 3 元的票只买 300 元，股价 300 元的票却买 3 万元 —— **风控形同虚设**。

v2：股数只能来自 `Sizer.size()` 的返回值。任何形如
`quantity = 100` / `quantity=Decimal("100")` 的代码都会被这条规则拦下。
"""

from __future__ import annotations

import ast

from tools.arch_lint.model import Violation
from tools.arch_lint.rules._helpers import (
    is_numeric_literal,
    iter_py_files,
    name_hints,
)
from tools.arch_lint.rules.registry import register

CODE = "ARCH002"
DESCRIPTION = "禁止股数字面量（股数只能来自 Sizer）"

# 全局扫描；tests/ 与 tools/ 豁免（测试替身与扫描器本身需要构造样例数字）
SCAN_PREFIXES: tuple[str, ...] = ("src/",)

_QUANTITY_HINTS: tuple[str, ...] = ("quantity", "shares", "qty", "lots")


def _target_names(node: ast.AST) -> list[str]:
    """取出赋值目标中的全部变量名。"""
    names: list[str] = []
    if isinstance(node, ast.Name):
        names.append(node.id)
    elif isinstance(node, ast.Attribute):
        names.append(node.attr)
    elif isinstance(node, (ast.Tuple, ast.List)):
        for element in node.elts:
            names.extend(_target_names(element))
    return names


def _check_assignments(doc, violations: list[Violation]) -> None:  # type: ignore[no-untyped-def]
    """形态 1：赋值 —— `quantity = 100` / `quantity: int = 100`。"""
    for node in ast.walk(doc.tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if node.value is None or not is_numeric_literal(node.value):
            continue
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else ([node.target] if node.target is not None else [])
        )
        for target in targets:
            for name in _target_names(target):
                if name_hints(name, _QUANTITY_HINTS):
                    violations.append(
                        Violation(
                            code=CODE,
                            path=doc.rel,
                            line=node.lineno,
                            message=(
                                f"禁止股数字面量：{doc.line(node.lineno).strip()}。"
                                "股数必须来自 Sizer.size() 的返回值，"
                                "并已按 MarketProfile.round_lot() 向下取整。"
                            ),
                        )
                    )


def _check_keyword_args(doc, violations: list[Violation]) -> None:  # type: ignore[no-untyped-def]
    """形态 2：关键字实参 —— `place_order(quantity=100)`。"""
    for node in ast.walk(doc.tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg is None or not name_hints(keyword.arg, _QUANTITY_HINTS):
                continue
            if is_numeric_literal(keyword.value):
                violations.append(
                    Violation(
                        code=CODE,
                        path=doc.rel,
                        line=node.lineno,
                        message=(
                            f"禁止股数字面量：{doc.line(node.lineno).strip()}。"
                            "股数必须来自 Sizer.size()，禁止就地写死。"
                        ),
                    )
                )


# 写死股数的全部形态。新增形态时在这里登记。
_QUANTITY_SHAPES = (_check_assignments, _check_keyword_args)


@register(CODE, DESCRIPTION)
def check(ctx) -> list[Violation]:  # type: ignore[no-untyped-def]
    """执行 ARCH002 检查。"""
    violations: list[Violation] = []
    for doc in iter_py_files(ctx, *SCAN_PREFIXES):
        if doc.tree is None:
            continue
        for shape in _QUANTITY_SHAPES:
            shape(doc, violations)
    return violations
