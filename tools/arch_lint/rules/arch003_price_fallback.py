"""ARCH003 —— 禁止价格兜底常量。

★ 根治 v1 最危险的 P0：`basic_risk_manager.py:112-116`

    try:
        price = self._get_price(symbol)
    except Exception:
        price = Decimal("100")     # ← 幻影价

风控模块从此永远按 100 元估值：股价 3 元的票被算成 100 元，
持仓市值被放大 33 倍，所有仓位约束全部失效。
**比崩溃更危险，因为它看起来在正常跑。**

v2：取不到价格必须 `raise PriceUnavailableError`，禁止任何默认值兜底。

## 检测的四类模式

1. `price = value or 100`           —— BoolOp(Or) + 数字字面量
2. `data.get("price", 100)`         —— dict.get 默认值是数字字面量
3. `if not price: price = 100`      —— 空值检查后填字面量
4. `except: price = 100`            —— 异常兜底填字面量
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

CODE = "ARCH003"
DESCRIPTION = "禁止价格兜底常量（取价失败必须抛 PriceUnavailableError）"

# 估值路径：风控 / 生命周期 / 适配层 / 领域服务
SCAN_PREFIXES: tuple[str, ...] = (
    "src/quant_v2/engines/risk/",
    "src/quant_v2/engines/lifecycle/",
    "src/quant_v2/adapters/",
    "src/quant_v2/domain/services/",
)

_PRICE_HINTS: tuple[str, ...] = ("price", "px", "last", "mark", "close")


def _is_price_name(node: ast.AST) -> bool:
    """表达式是否是"价格类"变量。"""
    if isinstance(node, ast.Name):
        return name_hints(node.id, _PRICE_HINTS)
    if isinstance(node, ast.Attribute):
        return name_hints(node.attr, _PRICE_HINTS)
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return isinstance(node.slice.value, str) and name_hints(node.slice.value, _PRICE_HINTS)
    return False


def _assigns_literal_to_price(stmts: list[ast.stmt]) -> bool:
    """语句序列中是否存在"给价格类变量赋字面量"。"""
    for stmt in ast.walk(ast.Module(body=list(stmts), type_ignores=[])):
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        if stmt.value is None or not is_numeric_literal(stmt.value):
            continue
        targets = (
            stmt.targets
            if isinstance(stmt, ast.Assign)
            else ([stmt.target] if stmt.target is not None else [])
        )
        for target in targets:
            if _is_price_name(target):
                return True
    return False


@register(CODE, DESCRIPTION)
def check(ctx) -> list[Violation]:  # type: ignore[no-untyped-def]
    """执行 ARCH003 检查。"""
    violations: list[Violation] = []

    def report(node: ast.AST, pattern: str) -> None:
        violations.append(
            Violation(
                code=CODE,
                path=doc.rel,
                line=node.lineno,
                message=(
                    f"禁止价格兜底常量（{pattern}）：{doc.line(node.lineno).strip()}。"
                    "取不到真实价格必须 raise PriceUnavailableError。"
                    "v1 反例：用 Decimal('100') 兜底导致风控永远按 100 元估值。"
                ),
            )
        )

    for doc in iter_py_files(ctx, *SCAN_PREFIXES):
        tree = doc.tree
        if tree is None:
            continue

        for node in ast.walk(tree):
            # 1) price or 100
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                has_price = any(_is_price_name(value) for value in node.values)
                has_literal = any(is_numeric_literal(value) for value in node.values)
                if has_price and has_literal:
                    report(node, "`or` 兜底")

            # 2) data.get("price", 100)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) >= 2
                and is_numeric_literal(node.args[1])
                and _is_price_name(node.func.value)
            ):
                report(node, "dict.get 默认值")

            # 3) if not price: price = 100
            if isinstance(node, ast.If):
                test = node.test
                is_falsy_price_check = (
                    isinstance(test, ast.UnaryOp)
                    and isinstance(test.op, ast.Not)
                    and _is_price_name(test.operand)
                ) or (
                    isinstance(test, ast.Compare)
                    and len(test.ops) == 1
                    and isinstance(test.ops[0], ast.Is)
                    and isinstance(test.comparators[0], ast.Constant)
                    and test.comparators[0].value is None
                    and _is_price_name(test.left)
                )
                if is_falsy_price_check and (
                    _assigns_literal_to_price(node.body) or _assigns_literal_to_price(node.orelse)
                ):
                    report(node, "空值兜底")

            # 4) except: price = 100
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if _assigns_literal_to_price(handler.body):
                        report(handler, "异常兜底")

    return violations
