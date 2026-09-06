"""扫描执行器。"""

from __future__ import annotations

from pathlib import Path

from tools.arch_lint.discovery import discover
from tools.arch_lint.model import FileDoc, RuleContext, Violation
from tools.arch_lint.noqa import filter_baselined, suppressed_on_line
from tools.arch_lint.rules import registry  # noqa: F401 -- 触发规则注册
from tools.arch_lint.rules.registry import all_rules, rule_codes

__all__ = ["ScanResult", "scan"]


class ScanResult:
    """一次扫描的结果。"""

    __slots__ = ("files_scanned", "rules_run", "suppressed_by_noqa", "violations")

    def __init__(
        self,
        *,
        violations: list[Violation],
        files_scanned: int,
        rules_run: tuple[str, ...],
        suppressed_by_noqa: int,
    ) -> None:
        """构造扫描结果。"""
        self.violations: list[Violation] = violations
        self.files_scanned: int = files_scanned
        self.rules_run: tuple[str, ...] = rules_run
        self.suppressed_by_noqa: int = suppressed_by_noqa

    @property
    def ok(self) -> bool:
        """是否全部通过。"""
        return not self.violations

    def by_code(self) -> dict[str, int]:
        """按规则码统计违规数。"""
        counts: dict[str, int] = {}
        for violation in self.violations:
            counts[violation.code] = counts.get(violation.code, 0) + 1
        return dict(sorted(counts.items()))


def scan(
    root: Path,
    *,
    only: tuple[str, ...] = (),
    git_hygiene: bool = False,
    use_baselines: bool = True,
) -> ScanResult:
    """执行一次架构扫描。

    Args:
        root: 仓库根。
        only: 只跑指定规则码；为空则跑全部。
        git_hygiene: 是否启用 ARCH009（默认关闭，见该规则说明）。
        use_baselines: 是否应用 `baselines.txt` 的存量豁免。

    Returns:
        `ScanResult`。

    Raises:
        KeyError: `only` 里含未知规则码。
    """
    root = Path(root).resolve()
    files: tuple[FileDoc, ...] = discover(root)

    wanted = tuple(code.upper() for code in only)
    unknown = sorted(set(wanted) - set(rule_codes()))
    if unknown:
        raise KeyError(f"未知规则：{unknown}；可用规则：{rule_codes()}")

    rules = all_rules()
    selected = {code: fn for code, fn in rules.items() if not wanted or code in wanted}

    ctx = RuleContext(root=root, files=files, git_hygiene=git_hygiene)

    by_path: dict[str, FileDoc] = {doc.rel: doc for doc in files}
    raw: list[Violation] = []
    for code, fn in sorted(selected.items()):
        try:
            raw.extend(fn(ctx))
        except Exception as exc:
            raw.append(
                Violation(
                    code=code,
                    path="<rule-error>",
                    line=0,
                    message=f"规则 {code} 执行时抛异常：{type(exc).__name__}: {exc}",
                )
            )

    # 行内豁免：`# noqa: ARCH001 -- 理由`
    kept: list[Violation] = []
    suppressed = 0
    for violation in raw:
        doc = by_path.get(violation.path)
        # 行内豁免：源码该行写了行内豁免注释（见 noqa.py 的语法）
        if (
            doc is not None
            and violation.line > 0
            and suppressed_on_line(doc.line(violation.line), violation.code)
        ):
            suppressed += 1
            continue
        kept.append(violation)

    if use_baselines:
        kept = filter_baselined(kept)

    kept.sort(key=lambda v: (v.path, v.line, v.code))
    return ScanResult(
        violations=kept,
        files_scanned=len(files),
        rules_run=tuple(sorted(selected)),
        suppressed_by_noqa=suppressed,
    )
