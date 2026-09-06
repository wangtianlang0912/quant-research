"""ARCH013 —— 浮点纪律：核心域禁止 float。

★ 这是 v1 少数**做对了**并必须继承的资产：v1 全程用 Decimal。

金额与价格计算用 float 的问题不在于精度"不够"，而在于
**误差不可预测、不可复现**：同一份数据换台机器、换个 numpy 版本，
第 8 位小数可能不一样，于是回测结果无法对账，数据指纹不稳定。

## 检测

在 `domain/` / `engines/` / `strategies/` / `factors/` / `indicators/` 内：

1. 浮点字面量（`0.1`、`1e-3`）
2. `float(...)` 调用（含 `something.float()`）

## 允许的例外

- 类型注解里的 `-> float`（如"推送成功率"这类统计展示值）
- 绘图与统计展示层（不在这五个目录里）
"""

from __future__ import annotations

import ast

from tools.arch_lint.model import Violation
from tools.arch_lint.rules._helpers import iter_py_files
from tools.arch_lint.rules.registry import register

CODE = "ARCH013"
DESCRIPTION = "浮点纪律：核心域禁止 float 字面量与 float() 调用"

SCAN_PREFIXES: tuple[str, ...] = (
    "src/quant_v2/domain/",
    "src/quant_v2/engines/",
    "src/quant_v2/strategies/",
    "src/quant_v2/factors/",
    "src/quant_v2/indicators/",
)


@register(CODE, DESCRIPTION)
def check(ctx) -> list[Violation]:  # type: ignore[no-untyped-def]
    """执行 ARCH013 检查。"""
    violations: list[Violation] = []
    for doc in iter_py_files(ctx, *SCAN_PREFIXES):
        tree = doc.tree
        if tree is None:
            continue

        for node in ast.walk(tree):
            # 1) 浮点字面量
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                violations.append(
                    Violation(
                        code=CODE,
                        path=doc.rel,
                        line=node.lineno,
                        message=(
                            f"核心域禁止浮点字面量 {node.value!r}："
                            f"{doc.line(node.lineno).strip()}。"
                            "金额/价格一律用 Decimal（如 Decimal('0.1')）。"
                            "浮点只允许出现在绘图与统计展示层。"
                        ),
                    )
                )

            # 2) float(...) 调用
            if isinstance(node, ast.Call):
                is_float_call = (isinstance(node.func, ast.Name) and node.func.id == "float") or (
                    isinstance(node.func, ast.Attribute) and node.func.attr == "float"
                )
                if is_float_call:
                    violations.append(
                        Violation(
                            code=CODE,
                            path=doc.rel,
                            line=node.lineno,
                            message=(
                                f"核心域禁止 float() 调用：{doc.line(node.lineno).strip()}。"
                                "需要浮点请用 Decimal；确需 float 的展示值"
                                "请在 engines/ 之外转换并写明理由。"
                            ),
                        )
                    )
    return violations
