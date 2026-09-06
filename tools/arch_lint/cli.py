"""命令行入口：`python -m tools.arch_lint.cli --root .`

设计原则：**输出必须可直接跳转**。
每条违规打 `path:line:CODE: message`，编辑器/IDE 一点就过去。
门禁报错看不懂 = 门禁被绕过。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.arch_lint.rules.registry import rule_codes, rule_description
from tools.arch_lint.runner import scan

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="arch_lint",
        description="quant_v2 架构静态扫描（ARCH001~013，AST 实现）",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(),
        help="仓库根目录（默认当前目录）",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=(),
        metavar="CODE",
        help="只跑指定规则，如 --only ARCH007 ARCH008",
    )
    parser.add_argument(
        "--git-hygiene",
        action="store_true",
        help="启用 ARCH009（git 工作区干净检查）。CI 环境变量存在时自动启用",
    )
    parser.add_argument(
        "--no-baselines",
        action="store_true",
        help="忽略 tools/arch_lint/baselines.txt 中的存量豁免",
    )
    parser.add_argument("--list", action="store_true", help="列出全部规则后退出")
    parser.add_argument("--quiet", action="store_true", help="只输出违规行，不输出统计")
    return parser


def main(argv: list[str] | None = None) -> int:
    """入口。

    Returns:
        0 = 全部通过；1 = 存在违规。
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        width = max(len(code) for code in rule_codes())
        for code in rule_codes():
            print(f"  {code:<{width}}  {rule_description(code)}")
        return 0

    result = scan(
        args.root,
        only=tuple(args.only),
        git_hygiene=args.git_hygiene,
        use_baselines=not args.no_baselines,
    )

    for violation in result.violations:
        print(violation.format())

    if not args.quiet:
        print()
        if result.violations:
            counts = "  ".join(f"{code}={n}" for code, n in result.by_code().items())
            print(f"✗ {len(result.violations)} 处违规  [{counts}]")
        else:
            print(f"✓ 全部通过（{len(result.rules_run)} 条规则 / {result.files_scanned} 个文件）")
        if result.suppressed_by_noqa:
            print(f"  （{result.suppressed_by_noqa} 处被行内 noqa 豁免）")

    return 1 if result.violations else 0


if __name__ == "__main__":
    sys.exit(main())
