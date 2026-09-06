"""ARCH009 —— 入库纪律。

★ 根治"生产脚本跑了 40 天从未提交"。

v1 的 `scripts/hk_daily_scan.py` 是真正驱动每日推送的生产代码，
但它**从未进入版本控制**。后果是：

- 没有任何人对它做过评审
- 它改了什么、什么时候改的、为什么改，全无线索
- 机器一坏就永久丢失

## 检查

1. `git ls-files --others --exclude-standard` 为空（无未跟踪文件）
2. `git status --porcelain` 为空（工作区干净）

★ 默认**关闭**，需要显式 `--git-hygiene` 或环境变量 `CI` 才跑 ——
本地开发时工作区本来就是脏的，天天报会让这条规则被当成噪音关掉。
"""

from __future__ import annotations

import os
import shutil
import subprocess

from tools.arch_lint.model import RuleContext, Violation
from tools.arch_lint.rules.registry import register

CODE = "ARCH009"
DESCRIPTION = "入库纪律（git 工作区必须干净）"

# 固定可执行文件路径（S607）：命令与参数全部由本模块硬编码，
# 不接受任何外部输入，因此不存在命令注入面。
GIT_EXE = shutil.which("git") or "git"


def _git(root: str, *args: str) -> tuple[int, str]:
    """执行 git 命令。"""
    try:
        completed = subprocess.run(  # noqa: S603
            [GIT_EXE, *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return (127, "git 不可用")
    return (completed.returncode, completed.stdout.strip())


@register(CODE, DESCRIPTION)
def check(ctx: RuleContext) -> list[Violation]:
    """执行 ARCH009 检查（默认关闭）。"""
    if not ctx.git_hygiene and os.environ.get("CI", "").lower() not in {"1", "true", "yes"}:
        return []

    root = str(ctx.root)
    violations: list[Violation] = []

    code, untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    if code == 0 and untracked:
        for line in untracked.splitlines():
            if line.strip():
                violations.append(
                    Violation(
                        code=CODE,
                        path=line.strip(),
                        line=0,
                        message=(
                            "存在未纳入版本控制的文件。"
                            "v1 反例：2559 行的生产脚本跑了 40 天从未提交，"
                            "无人评审、无人知情、机器一坏就永久丢失。"
                        ),
                    )
                )

    code, dirty = _git(root, "status", "--porcelain")
    if code == 0 and dirty:
        for line in dirty.splitlines():
            if line.strip():
                violations.append(
                    Violation(
                        code=CODE,
                        path=line[3:].strip() if len(line) > 3 else line.strip(),
                        line=0,
                        message=f"工作区不干净（{line.strip()}）：提交或清理后再跑门禁。",
                    )
                )

    return violations
