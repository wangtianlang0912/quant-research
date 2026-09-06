"""ARCH005 —— 禁止 Null 适配器与静默吞异常。

★ v1 最触目惊心的运维事故：`NullNotificationAdapter` 吞掉了全部发送异常，
于是**连续 40 天没有任何人收到推送，而系统每天报告"推送成功"**。

一个 Null 适配器的问题不在于它不干活，而在于它让上游以为活干完了。
同理，`except Exception: pass` 让错误凭空消失 —— 后续任何排查都没有线索。

## 检测

1. 类名/函数名/变量名匹配 `Null*Adapter` / `NoOp*` / `Dummy*Notifier` / `*NullAdapter`
2. `except ...: pass` / `except ...: ...`（空 except 体）
"""

from __future__ import annotations

import ast
import re

from tools.arch_lint.model import Violation
from tools.arch_lint.rules._helpers import is_empty_body, iter_py_files
from tools.arch_lint.rules.registry import register

CODE = "ARCH005"
DESCRIPTION = "禁止 Null 适配器与静默吞异常"

# 生产代码全扫；tests/ 允许用哑实现做测试替身（但命名不许叫 NullAdapter）
SCAN_PREFIXES: tuple[str, ...] = ("src/", "tools/")

_NULL_ADAPTER_RE: re.Pattern[str] = re.compile(
    r"^(?:Null.*Adapter|.*NullAdapter|NoOp.*|Dummy.*Notifier|Silent.*|PassThrough.*Adapter)$",
    re.IGNORECASE,
)


def _check_names(node: ast.AST, doc, violations: list[Violation]) -> None:
    """检查类/函数/变量名是否像 Null 适配器。"""
    names: list[tuple[str, int]] = []
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        names.append((node.name, node.lineno))
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append((target.id, node.lineno))
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names.append((node.target.id, node.lineno))

    for name, lineno in names:
        if _NULL_ADAPTER_RE.match(name):
            violations.append(
                Violation(
                    code=CODE,
                    path=doc.rel,
                    line=lineno,
                    message=(
                        f"禁止 Null / NoOp 适配器：{name!r}。"
                        "v1 反例：NullNotificationAdapter 吞掉全部异常，"
                        "导致 40 天无人收到推送而系统照报成功。"
                        "宁可让进程起不来（NotificationConfigError），也不能假装干活。"
                    ),
                )
            )


@register(CODE, DESCRIPTION)
def check(ctx) -> list[Violation]:  # type: ignore[no-untyped-def]
    """执行 ARCH005 检查。"""
    violations: list[Violation] = []
    for doc in iter_py_files(ctx, *SCAN_PREFIXES):
        tree = doc.tree
        if tree is None:
            continue

        for node in ast.walk(tree):
            _check_names(node, doc, violations)

            if isinstance(node, ast.ExceptHandler) and is_empty_body(node.body):
                handled = ast.unparse(node.type) if node.type is not None else "裸 except"
                violations.append(
                    Violation(
                        code=CODE,
                        path=doc.rel,
                        line=node.lineno,
                        message=(
                            f"禁止静默吞异常：except {handled} 的处理体为空。"
                            "至少要落一条日志或告警；真正不需要处理的异常"
                            "请用 `except X: pass  # noqa: ARCH005 -- <理由>` 并写明理由。"
                        ),
                    )
                )
    return violations
