"""ARCH015 —— 禁用端点不得出现在任何受管文件中（M-6）。

实测（§5.12）：东财 push2 系端点（含编号子域）在本网络 TCP 建连全部失败，
调用必 ProxyError。架构上把它们列为**禁用端点**，唯一声明点是
`capabilities.py` 的 `FORBIDDEN_ENDPOINTS`。

规则语义：这些域名字面量只允许出现在声明文件本身；任何其他受管文件
（src / tools / tests / scripts / configs）里出现即违规 —— 包括编号子域
（子串匹配覆盖）。
"""

from __future__ import annotations

from tools.arch_lint.model import RuleContext, Violation
from tools.arch_lint.rules.registry import register

CODE = "ARCH015"
DESCRIPTION = "禁用端点字面量（东财 push2 系）只允许出现在 capabilities.py 声明点"

# 唯一声明点（FORBIDDEN_ENDPOINTS 所在文件）
DECLARATION_FILE = "src/quant_v2/adapters/market_data/capabilities.py"


def _forbidden_endpoints() -> tuple[str, ...]:
    """取禁用端点清单（从声明点 import，单一事实来源）。"""
    from quant_v2.adapters.market_data.capabilities import FORBIDDEN_ENDPOINTS  # noqa: PLC0415

    return FORBIDDEN_ENDPOINTS


@register(CODE, DESCRIPTION)
def check(ctx: RuleContext) -> list[Violation]:
    """执行 ARCH015 检查（全文子串扫描，覆盖所有受管文本文件）。"""
    forbidden = _forbidden_endpoints()
    if not forbidden:
        return []
    violations: list[Violation] = []
    for doc in ctx.files:
        if doc.rel == DECLARATION_FILE:
            continue
        for endpoint in forbidden:
            index = doc.source.find(endpoint)
            if index < 0:
                continue
            line_no = doc.source.count("\n", 0, index) + 1
            violations.append(
                Violation(
                    code=CODE,
                    path=doc.rel,
                    line=line_no,
                    message=(
                        f"禁用端点 {endpoint} 不得出现在代码/配置中（M-6：TCP 建连失败，"
                        "调用必 ProxyError）。端点清单唯一声明点是 "
                        f"{DECLARATION_FILE}；需要判断端点是否禁用时 import "
                        "FORBIDDEN_ENDPOINTS，不要复制字符串。"
                    ),
                )
            )
    return violations
