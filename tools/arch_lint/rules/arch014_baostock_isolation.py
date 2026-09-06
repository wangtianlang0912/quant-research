"""ARCH014 —— baostock 隔离（M-3 / M-9）。

`import baostock` 只允许出现在两个文件：
- `src/quant_v2/adapters/market_data/subprocess_worker.py`（子进程会话）
- `src/quant_v2/adapters/market_data/baostock_cn.py`（适配器）

其余任何位置（主进程模块 / 测试 / 工具）出现即 CI 失败。

★ 为什么是 import 级检查而不是运行时检查：baostock 走**裸 TCP 不认
HTTP_PROXY**（M-9）且会在 C 扩展里挂死（M-3），一旦被主进程 import，
进程就同时背上了"挂死不可恢复"和"代理环境失效"两个不可控变量。
把检查提前到静态层，问题在 PR 阶段就被拦下，而不是在生产环境挂死时。
"""

from __future__ import annotations

import ast

from tools.arch_lint.model import RuleContext, Violation
from tools.arch_lint.rules._helpers import iter_py_files
from tools.arch_lint.rules.registry import register

CODE = "ARCH014"
DESCRIPTION = "baostock 隔离：import baostock 只允许在 subprocess_worker.py / baostock_cn.py"

# ★ 显式白名单（不是前缀匹配）：baostock 的暴露面必须逐文件可枚举
ALLOWED_FILES: frozenset[str] = frozenset(
    {
        "src/quant_v2/adapters/market_data/subprocess_worker.py",
        "src/quant_v2/adapters/market_data/baostock_cn.py",
    }
)


@register(CODE, DESCRIPTION)
def check(ctx: RuleContext) -> list[Violation]:
    """执行 ARCH014 检查（含函数体内的惰性 import —— ast.walk 全覆盖）。"""
    violations: list[Violation] = []
    for doc in iter_py_files(ctx):
        tree = doc.tree
        assert tree is not None  # iter_py_files 已过滤
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            else:
                continue
            for module in modules:
                if module.split(".")[0] != "baostock":
                    continue
                if doc.rel in ALLOWED_FILES:
                    continue
                violations.append(
                    Violation(
                        code=CODE,
                        path=doc.rel,
                        line=node.lineno,
                        message=(
                            f"import baostock 只允许在 {sorted(ALLOWED_FILES)} 内出现："
                            f"{doc.line(node.lineno).strip()}。"
                            "baostock 会挂死且不认代理（M-3/M-9），必须经子进程隔离 —— "
                            "主进程代码请改用 SubprocessWorker / BaostockCnAdapter。"
                        ),
                    )
                )
    return violations
