"""ARCH008 —— 因子/指标重复实现（S-06）。

★ 诊断 #12：v1 的因子指标散落在 `factor_scanner.py`、`breakout_scorer.py`、
`scripts/phase0_*.py` 至少四处，同一指标有多个版本且**口径不同**
（MACD 用 O(n²) 前缀重算、RSI 用简单均值代替 Wilder 平滑）。
改一个忘另一个是必然的，而且没人知道该信哪个版本。

## 两层防线

1. **注册期**：`FactorRegistry.register()` 里 `factor_id` 重复即抛错（T03 实现）
2. **编译期（本规则）**：对 `factors/` 与 `indicators/` 下的顶层函数做
   **函数体 token 相似度**比对，超过阈值即报

★ 相似度用 token 5-gram 的 Jaccard 系数：
它能抓住"结构相同、改了变量名和常量"的重复，
又不会因为"两个函数都调用了 `prepare_series`"就误报。
"""

from __future__ import annotations

import ast

from tools.arch_lint.model import Violation
from tools.arch_lint.rules._helpers import iter_py_files, jaccard, statement_tokens, stmt_walk
from tools.arch_lint.rules.registry import register

CODE = "ARCH008"
DESCRIPTION = "因子/指标重复实现"

SCAN_PREFIXES: tuple[str, ...] = (
    "src/quant_v2/factors/",
    "src/quant_v2/indicators/",
)

# 相似度阈值（设计稿 0.85）
THRESHOLD: float = 0.85

# 太短的函数不做相似度判定：短函数天然"看起来像"
MIN_TOKENS: int = 30


@register(CODE, DESCRIPTION)
def check(ctx) -> list[Violation]:  # type: ignore[no-untyped-def]
    """执行 ARCH008 检查。"""
    functions: list[tuple[str, str, int, list[str]]] = []

    for doc in iter_py_files(ctx, *SCAN_PREFIXES):
        tree = doc.tree
        if tree is None:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            tokens: list[str] = []
            for stmt in stmt_walk(node):
                tokens.extend(statement_tokens(stmt))
            if len(tokens) >= MIN_TOKENS:
                functions.append((doc.rel, node.name, node.lineno, tokens))

    violations: list[Violation] = []
    for i in range(len(functions)):
        path_a, name_a, line_a, tokens_a = functions[i]
        for j in range(i + 1, len(functions)):
            path_b, name_b, line_b, tokens_b = functions[j]
            similarity = jaccard(tokens_a, tokens_b)
            if similarity < THRESHOLD:
                continue
            same_file = path_a == path_b
            violations.append(
                Violation(
                    code=CODE,
                    path=path_a,
                    line=line_a,
                    message=(
                        f"疑似重复实现：{path_a}:{line_a} {name_a}() 与 "
                        f"{path_b}:{line_b} {name_b}() 相似度 {similarity:.2f}"
                        f"（阈值 {THRESHOLD}）"
                        + ("，且在同一个文件内 —— 请合并为一个函数。" if same_file else "。")
                        + " 因子/指标必须单一实现，否则口径漂移无法察觉。"
                    ),
                )
            )
    return violations
