"""ARCH004 —— 禁止他人机器绝对路径。

v1 有 4 个脚本写死了 `/Users/leihen/.qclaw/...`。
这些脚本在作者机器上能跑，换台机器立刻 `FileNotFoundError`，
而更糟的是**它们跑了 40 天都没人发现有问题**—— 因为只有作者一个人跑过。

v2：路径一律用相对路径、`Path.home()`、或环境变量。

## 检测

逐行正则（这是少数**不该**用 AST 的场景：绝对路径主要出现在
字符串常量里，但也会出现在注释、YAML、Shell 脚本里，
AST 只能覆盖 Python 源码的第一种情况）。

- `/Users/<name>/`
- `/home/<name>/`
- `C:\\Users\\` 与 `C:/Users/`
"""

from __future__ import annotations

import re

from tools.arch_lint.model import RuleContext, Violation
from tools.arch_lint.rules.registry import register

CODE = "ARCH004"
DESCRIPTION = "禁止他人机器绝对路径"

# ★ 扫描全部文本文件（含 YAML / Shell / Markdown），Python 专属路径不够用
SCAN_PREFIXES: tuple[str, ...] = ()

# ★ 自检豁免：arch_lint 自身源码与门禁自测必然包含它要检测的这几个字面量
#   （正则表、规则说明文档、合成违规样本）。若不豁免，门禁永远扫出自己的 4 条违规，
#   工程师会习惯性地过滤掉这些输出 —— 那才是真正的门禁失效。
#   豁免范围刻意收窄到 `tools/arch_lint/` 与 `tests/architecture/`。
SELF_EXEMPT_PREFIXES: tuple[str, ...] = (
    "tools/arch_lint/",
    "tests/architecture/",
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"/Users/[A-Za-z0-9._-]+/"), "/Users/<name>/"),
    (re.compile(r"/home/[A-Za-z0-9._-]+/"), "/home/<name>/"),
    (re.compile(r"C:\\Users\\"), "C:\\Users\\"),
    (re.compile(r"C:/Users/"), "C:/Users/"),
)


@register(CODE, DESCRIPTION)
def check(ctx: RuleContext) -> list[Violation]:
    """执行 ARCH004 检查。"""
    violations: list[Violation] = []
    for doc in ctx.files:
        if doc.rel.startswith(SELF_EXEMPT_PREFIXES):
            continue
        for lineno, line in enumerate(doc.lines, start=1):
            for pattern, label in _PATTERNS:
                if pattern.search(line):
                    violations.append(
                        Violation(
                            code=CODE,
                            path=doc.rel,
                            line=lineno,
                            message=(
                                f"出现他人机器绝对路径（{label}）：{line.strip()[:120]}。"
                                "请改用相对路径、Path.home() 或环境变量。"
                            ),
                        )
                    )
                    break  # 一行只报一次
    return violations
