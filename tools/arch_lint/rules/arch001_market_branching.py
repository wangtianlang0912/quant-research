"""ARCH001 —— 禁止市场硬编码分支。

★ 这条规则是"一套框架多市场"能否成立的**唯一机械化保证**。

v1 的做法是在策略与扫描器里写 `if market == 'A'`，
结果新增港股要改 17 个文件，改到第三个人就没人敢动了。

v2 要求：市场差异全部表达为 `MarketProfile` 的**数值字段**；
`None` 优先于特例；极端特例用 `hooks` 注入类路径。
唯一允许"按市场取配置"的地方是 `adapters/clock/market_profile_loader.py`（不在此规则的扫描范围）。

## 检测什么

1. `market` / `market_code` 之类的表达式与**字符串字面量**做 `==` / `!=` / `in` / `not in`
2. 代码前缀判断：`.startswith('6')` / `.endswith('.SH')`

## 不检测什么（刻意放过，避免误报）

- `if market not in spec.markets` —— 右侧是变量不是字面量，属于容量校验，合法
- 注释与 docstring 里出现 `market == 'cn_a'` —— AST 看不到注释
"""

from __future__ import annotations

import ast

from tools.arch_lint.model import Violation
from tools.arch_lint.rules._helpers import (
    contains_string_constant,
    is_string_constant,
    iter_py_files,
    name_hints,
)
from tools.arch_lint.rules.registry import register

CODE = "ARCH001"
DESCRIPTION = "禁止市场硬编码分支（引擎代码里零市场 if）"

# 扫描范围：策略/因子/指标/引擎/领域服务。★ 不含 adapters（加载器在那里）
SCAN_PREFIXES: tuple[str, ...] = (
    "src/quant_v2/engines/",
    "src/quant_v2/strategies/",
    "src/quant_v2/factors/",
    "src/quant_v2/indicators/",
    "src/quant_v2/domain/services/",
)

_MARKET_HINTS: tuple[str, ...] = ("market", "exchange")
_COMPARE_OPS: tuple[type[ast.cmpop], ...] = (
    ast.Eq,
    ast.NotEq,
    ast.In,
    ast.NotIn,
)


def _is_market_expr(node: ast.AST) -> bool:
    """表达式是否"看起来是市场标识"。"""
    if isinstance(node, ast.Name):
        return name_hints(node.id, _MARKET_HINTS)
    if isinstance(node, ast.Attribute):
        return name_hints(node.attr, _MARKET_HINTS)
    if isinstance(node, ast.Subscript):
        return is_string_constant(node.slice) and name_hints(str(node.slice.value), _MARKET_HINTS)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
    ):
        return is_string_constant(node.args[0]) and name_hints(
            str(node.args[0].value), _MARKET_HINTS
        )
    return False


@register(CODE, DESCRIPTION)
def check(ctx) -> list[Violation]:  # type: ignore[no-untyped-def]
    """执行 ARCH001 检查。"""
    violations: list[Violation] = []
    for doc in iter_py_files(ctx, *SCAN_PREFIXES):
        tree = doc.tree
        if tree is None:
            continue

        for node in ast.walk(tree):
            # 1) market 与字符串字面量比较
            if isinstance(node, ast.Compare) and any(
                isinstance(op, _COMPARE_OPS) for op in node.ops
            ):
                operands = [node.left, *node.comparators]
                if not any(_is_market_expr(operand) for operand in operands):
                    continue
                for comparator in node.comparators:
                    if contains_string_constant(comparator):
                        line = doc.line(node.lineno).strip()
                        violations.append(
                            Violation(
                                code=CODE,
                                path=doc.rel,
                                line=node.lineno,
                                message=(
                                    f"禁止市场硬编码分支：{line}。"
                                    "市场差异请表达为 MarketProfile 的数值字段；"
                                    "无约束用 None；极端特例用 hooks 注入类路径。"
                                ),
                            )
                        )
                        break

            # 2) 代码前缀判断（.startswith('6') / .endswith('.SH')）
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"startswith", "endswith"}
                and any(is_string_constant(arg) for arg in node.args)
            ):
                violations.append(
                    Violation(
                        code=CODE,
                        path=doc.rel,
                        line=node.lineno,
                        message=(
                            f"禁止用代码前缀判断市场：{doc.line(node.lineno).strip()}。"
                            "用 MarketProfile.symbol_pattern 正则，或直接在标的上打标。"
                        ),
                    )
                )
    return violations
