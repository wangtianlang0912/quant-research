"""ARCH007 —— 跨文件重复代码块。

★ v1 的 `scripts/hk_daily_scan.py` 与 `hk_daily_scan_enhanced.py`（合计 2559 行）
有 30/31 个同名函数、约 70% 重复。修 bug 要改两处，改一处忘一处是全靠运气的游戏。

## 实现

不用 pylint R0801（会引入 pylint 依赖，且它的报告粒度不好控），
改成自己实现：

1. 把每个文件切成"语句块"（module body / 函数体 / if 体 / for 体 / ...）
2. 块内取**连续 `WINDOW` 条语句**的滑动窗口
3. 每个窗口规范化成 token 序列并取哈希
4. 同一个哈希出现在 **≥2 个不同文件** → 判定重复

★ 只查**跨文件**：同一个文件内两个相似函数是"该抽象成一个函数"的问题，
属于代码味道而不是"两处实现会漂移"的风险；跨文件重复才是真正会漂移的那个。
（同文件内的重复由 ARCH008 在 factors/indicators 目录下把关。）

**为什么用 token 规范化而不是逐行文本比对**：
逐行比对会被缩进、空行、注释干扰，误报率高；
token 规范化能抓住"复制粘贴后改了变量名"这种最常见的重复形式。
"""

from __future__ import annotations

import ast
from collections import defaultdict

from tools.arch_lint.model import Violation
from tools.arch_lint.rules._helpers import iter_blocks, iter_py_files, statement_tokens
from tools.arch_lint.rules.registry import register

CODE = "ARCH007"
DESCRIPTION = "跨文件重复代码块"

SCAN_PREFIXES: tuple[str, ...] = ("src/", "tools/")

# 连续 WINDOW 条语句构成一个"块"。10 条语句 ≈ 25~35 行，对应设计稿的"30 行"阈值。
WINDOW: int = 10


def _is_boilerplate(block: list[ast.stmt]) -> bool:
    """是否为样板代码（import 段、docstring 段）—— 这类重复是正常的。"""
    counts = defaultdict(int)
    for stmt in block:
        counts[type(stmt)] += 1
    boilerplate = counts[ast.Import] + counts[ast.ImportFrom]
    return boilerplate * 2 >= len(block)


def _is_declarative(block: list[ast.stmt]) -> bool:
    """是否为声明式常量块（Enum 成员 / 模块级常量表）。

    ★ 这是**误报抑制**，不是放宽门禁：
    两个 `class X(str, Enum)` 的成员声明在 token 化后完全一致
    （`NAME = C:str` 连着重复 N 次），会被判成"重复代码块"。
    但枚举是**声明式数据**——它没有逻辑，不会"两处实现漂移"，
    强行抽成共享基类反而破坏可读性。

    门禁的存亡取决于误报率：误报一多，工程师的第一反应是绕过门禁，
    那门禁就形同虚设。所以这里必须显式排除。
    """
    if not block:
        return False
    for stmt in block:
        if not isinstance(stmt, ast.Assign):
            return False
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            return False
        if not isinstance(stmt.value, ast.Constant):
            return False
    return True


@register(CODE, DESCRIPTION)
def check(ctx) -> list[Violation]:  # type: ignore[no-untyped-def]
    """执行 ARCH007 检查。"""
    # 窗口哈希 → [(path, line)]
    windows: dict[str, list[tuple[str, int]]] = defaultdict(list)

    for doc in iter_py_files(ctx, *SCAN_PREFIXES):
        tree = doc.tree
        if tree is None:
            continue
        for block in iter_blocks(tree):
            if len(block) < WINDOW:
                continue
            for start in range(0, len(block) - WINDOW + 1):
                chunk = block[start : start + WINDOW]
                if _is_boilerplate(chunk) or _is_declarative(chunk):
                    continue
                tokens: list[str] = []
                for stmt in chunk:
                    tokens.extend(statement_tokens(stmt))
                if len(tokens) < 40:  # 太少 token 的窗口没有判定价值
                    continue
                windows["|".join(tokens)].append((doc.rel, chunk[0].lineno))

    violations: list[Violation] = []
    for token_key, locations in sorted(windows.items()):
        files = {path for path, _ in locations}
        if len(files) < 2:
            continue
        locations_sorted = sorted(locations)
        first_path, first_line = locations_sorted[0]
        others = ", ".join(
            f"{path}:{line}" for path, line in locations_sorted[1:] if path != first_path
        )
        violations.append(
            Violation(
                code=CODE,
                path=first_path,
                line=first_line,
                message=(
                    f"跨文件重复代码块（{len(locations_sorted)} 处，{WINDOW} 条连续语句）："
                    f"{first_path}:{first_line} 与 {others}。"
                    "请抽成共享函数；两处实现迟早会漂移。"
                ),
            )
        )
        del token_key
    return violations
