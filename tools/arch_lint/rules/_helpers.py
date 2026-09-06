"""共享工具。

每条规则是一个模块级函数 `check(ctx) -> list[Violation]`，
由 `tools.arch_lint.rules.registry` 的 `register()` 登记。
注册表**显式 import** 而不是靠 pkgutil 自动发现 ——
自动发现会让"哪些规则生效"变成运行时才知道的事，
而门禁规则清单必须是读代码就能看全的。
"""

from __future__ import annotations

import ast
from collections.abc import Sequence

from tools.arch_lint.model import FileDoc, RuleContext

__all__ = [
    "contains_string_constant",
    "is_numeric_literal",
    "is_string_constant",
    "iter_blocks",
    "jaccard",
    "name_hints",
    "statement_tokens",
    "stmt_walk",
]

# ============================================================================
# 共享工具
# ============================================================================


def stmt_walk(node: ast.AST) -> list[ast.stmt]:
    """按**源码顺序**收集全部语句节点（含嵌套）。"""
    result: list[ast.stmt] = []

    def recurse(current: ast.AST) -> None:
        for child in ast.iter_child_nodes(current):
            if isinstance(child, ast.stmt):
                result.append(child)
            recurse(child)

    recurse(node)
    return result


def iter_blocks(tree: ast.Module) -> list[list[ast.stmt]]:
    """收集模块里的全部语句块（module body / 函数体 / if 体 / for 体 / ...）。

    只关心"连续的语句序列"，因此按块而不是按 AST 深度遍历 ——
    重复代码检测关心的是相邻语句，不是树形结构。
    """
    blocks: list[list[ast.stmt]] = []
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            value = getattr(node, attr, None)
            if isinstance(value, list) and value and all(isinstance(s, ast.stmt) for s in value):
                blocks.append(list(value))
        handlers = getattr(node, "handlers", None)
        if isinstance(handlers, list):
            for handler in handlers:
                if isinstance(handler, ast.ExceptHandler) and handler.body:
                    blocks.append(list(handler.body))
    return blocks


def name_hints(name: str, hints: Sequence[str]) -> bool:
    """名称是否命中任一 hints（大小写不敏感，去下划线后比较）。

    去下划线是为了同时匹配 `last_price` / `lastPrice` / `lastprice`。
    """
    normalized = name.lower().replace("_", "")
    return any(hint in normalized for hint in hints)


def is_numeric_literal(node: ast.AST) -> bool:
    """是否为数字字面量（含 `Decimal(...)` / `int(...)` 包裹的字面量）。

    bool 不算数字字面量 —— `flag = True` 显然不是"写死的数字"。
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"Decimal", "int", "float"}
        and node.args
    ):
        return is_numeric_literal(node.args[0])
    return False


def is_string_constant(node: ast.AST) -> bool:
    """是否为字符串常量。"""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def contains_string_constant(node: ast.AST) -> bool:
    """子树中是否含字符串常量（递归进 Tuple/List/Set）。"""
    if is_string_constant(node):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(contains_string_constant(item) for item in node.elts)
    return False


def statement_tokens(stmt: ast.AST) -> list[str]:
    """把一条语句规范化为 token 序列（用于相似度/重复检测）。

    规范化规则：

    - 变量名统一为 `NAME` —— 复制粘贴后改名是最常见的重复形式
    - 常量只保留类型不保留值 —— 阈值改了也说不上是两份代码
    - 保留 `Attribute.attr` 与 `Call` 的函数名 —— 这两个是语义主体

    这样两条"结构相同、变量名不同"的代码会被判为重复，
    而两条只是"用的库一样"的代码不会。
    """
    tokens: list[str] = []
    for node in ast.walk(stmt):
        if isinstance(node, ast.Constant):
            tokens.append(f"C:{type(node.value).__name__}")
        elif isinstance(node, ast.Name):
            tokens.append("NAME")
        elif isinstance(node, ast.Attribute):
            tokens.append(f"A:{node.attr}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                tokens.append(f"F:{func.id}")
            elif isinstance(func, ast.Attribute):
                tokens.append(f"F:{func.attr}")
        else:
            tokens.append(type(node).__name__)
    return tokens


def jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    """两个 token 序列的 Jaccard 相似度（按多重集的 5-gram 集合比较）。"""
    if not left or not right:
        return 0.0

    def grams(tokens: Sequence[str], n: int = 5) -> set[tuple[str, ...]]:
        if len(tokens) < n:
            return {tuple(tokens)}
        return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}

    left_grams = grams(left)
    right_grams = grams(right)
    union = left_grams | right_grams
    if not union:
        return 0.0
    return len(left_grams & right_grams) / len(union)


def iter_py_files(ctx: RuleContext, *prefixes: str) -> tuple[FileDoc, ...]:
    """取指定前缀下的 Python 文件（语法错误的文件自动跳过）。"""
    return tuple(doc for doc in ctx.py_files(*prefixes) if doc.tree is not None)


def module_root(dotted: str) -> str:
    """取 dotted path 的根模块名（`quant_v2.adapters.x` → `quant_v2`）。"""
    return dotted.split(".", maxsplit=1)[0]


def is_empty_body(body: Sequence[ast.stmt]) -> bool:
    """语句体是否"什么都没做"（空 / 只有 pass / 只有 ...）。"""
    if not body:
        return True
    if len(body) != 1:
        return False
    only = body[0]
    if isinstance(only, ast.Pass):
        return True
    if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant):
        return only.value.value is Ellipsis
    return False
