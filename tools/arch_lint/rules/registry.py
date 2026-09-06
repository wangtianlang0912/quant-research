"""规则注册表。

★ 规则清单**显式列举**（见文件末尾的 import），不用 pkgutil 自动发现。
门禁规则清单必须是"读这个文件就能看全"的 ——
如果规则是运行时才发现的，那么"CI 到底拦了什么"就成了一件需要查日志的事。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from tools.arch_lint.model import RuleContext, Violation

__all__ = [
    "CheckFn",
    "all_rules",
    "get_rule",
    "register",
    "rule_codes",
    "rule_description",
]

CheckFn = Callable[[RuleContext], Sequence[Violation]]

_RULES: dict[str, CheckFn] = {}
_DESCRIPTIONS: dict[str, str] = {}


def register(code: str, description: str) -> Callable[[CheckFn], CheckFn]:
    """规则注册装饰器。

    Args:
        code: 规则码，如 `'ARCH001'`。
        description: 一句话描述（用于 `--list` 与文档）。

    Raises:
        ValueError: 规则码重复注册。
    """

    def decorator(fn: CheckFn) -> CheckFn:
        normalized = code.upper()
        if normalized in _RULES:
            raise ValueError(f"规则重复注册：{normalized}")
        _RULES[normalized] = fn
        _DESCRIPTIONS[normalized] = description
        return fn

    return decorator


def all_rules() -> dict[str, CheckFn]:
    """全部已注册规则（按规则码排序）。"""
    return dict(sorted(_RULES.items()))


def rule_codes() -> tuple[str, ...]:
    """全部规则码。"""
    return tuple(sorted(_RULES))


def rule_description(code: str) -> str:
    """规则描述。"""
    return _DESCRIPTIONS.get(code.upper(), "")


def get_rule(code: str) -> CheckFn:
    """按规则码取规则函数。

    Raises:
        KeyError: 未知规则码。
    """
    normalized = code.upper()
    if normalized not in _RULES:
        raise KeyError(f"未知规则 {code}；可用规则：{rule_codes()}")
    return _RULES[normalized]


# ============================================================================
# ★ 规则清单（新增规则必须在这里登记，否则它不会生效）
# ============================================================================
from tools.arch_lint.rules import (  # noqa: E402
    arch001_market_branching,
    arch002_quantity_literal,
    arch003_price_fallback,
    arch004_absolute_path,
    arch005_null_adapter,
    arch006_fake_success,
    arch007_duplicate_block,
    arch008_duplicate_indicator,
    arch009_git_hygiene,
    arch010_import_direction,
    arch011_external_sdk,
    arch012_swallow_lookahead,
    arch013_float_discipline,
    arch014_baostock_isolation,
    arch015_forbidden_endpoints,
)

del arch001_market_branching
del arch002_quantity_literal
del arch003_price_fallback
del arch004_absolute_path
del arch005_null_adapter
del arch006_fake_success
del arch007_duplicate_block
del arch008_duplicate_indicator
del arch009_git_hygiene
del arch010_import_direction
del arch011_external_sdk
del arch012_swallow_lookahead
del arch013_float_discipline
del arch014_baostock_isolation
del arch015_forbidden_endpoints
