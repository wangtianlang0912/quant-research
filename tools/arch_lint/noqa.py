"""行内豁免与存量基线。

★ **豁免必须写理由**。没有理由的豁免就是"我不知道为什么这里会报错，先让它过"，
这类豁免积累到一定数量，门禁就死了。

格式：`# noqa: ARCH001 -- 这里是市场画像加载器，本来就按市场取配置`
"""

from __future__ import annotations

import re
from pathlib import Path

from tools.arch_lint.model import Violation

__all__ = ["BASELINE_PATH", "filter_baselined", "load_baselines", "suppressed_on_line"]

BASELINE_PATH: Path = Path("tools/arch_lint/baselines.txt")

# `# noqa: ARCH001 -- 理由` / `# noqa:ARCH001` / `# noqa` / `# noqa: ARCH001,ARCH002`
_NOQA_RE: re.Pattern[str] = re.compile(r"#\s*noqa(?::\s*(?P<codes>[A-Z0-9,\s]+))?", re.IGNORECASE)

# 基线文件行格式：`path:line:CODE<TAB或空格>理由`
_BASELINE_RE: re.Pattern[str] = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):(?P<code>[A-Z0-9]+)\s*(?:--\s*)?(?P<reason>.*)$"
)


def suppressed_on_line(line: str, code: str) -> bool:
    """该行的 `# noqa` 是否豁免了指定规则码。

    裸 `# noqa` 豁免全部规则（兼容写法，不鼓励）。
    """
    for match in _NOQA_RE.finditer(line):
        codes = match.group("codes")
        if codes is None:
            return True
        if code in {item.strip().upper() for item in codes.split(",")}:
            return True
    return False


def load_baselines(path: Path | None = None) -> frozenset[tuple[str, int, str]]:
    """加载存量豁免基线。

    Returns:
        `{(path, line, code), ...}`。`line == 0` 表示豁免整个文件的该规则。
    """
    target = BASELINE_PATH if path is None else path
    if not target.is_file():
        return frozenset()
    entries: set[tuple[str, int, str]] = set()
    for raw in target.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _BASELINE_RE.match(stripped)
        if match is None:
            continue
        entries.add((match.group("path"), int(match.group("line")), match.group("code").upper()))
    return frozenset(entries)


def filter_baselined(
    violations: list[Violation],
    baselines: frozenset[tuple[str, int, str]] | None = None,
) -> list[Violation]:
    """剔除已在基线中的违规。"""
    entries = load_baselines() if baselines is None else baselines
    return [
        violation
        for violation in violations
        if (violation.path, violation.line, violation.code) not in entries
        and (violation.path, 0, violation.code) not in entries
    ]
