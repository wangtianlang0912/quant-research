"""数据模型与文件抽象。"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

__all__ = ["FileDoc", "Rule", "RuleContext", "Violation"]


@dataclass(frozen=True)
class Violation:
    """一条违规。"""

    code: str
    path: str  # 相对仓库根的 posix 路径
    line: int
    message: str

    def format(self) -> str:
        """格式化为 `path:line:CODE: message`（可被编辑器直接跳转）。"""
        return f"{self.path}:{self.line}: {self.code}: {self.message}"


@dataclass(frozen=True)
class FileDoc:
    """一个被扫描的文件。

    `tree` 惰性解析：ARCH004 只需要逐行正则扫描，
    为几千个文件预先构造 AST 是浪费。
    """

    rel: str  # 相对仓库根的 posix 路径
    abs_path: Path
    source: str

    @property
    def lines(self) -> tuple[str, ...]:
        """按行拆分的源码。"""
        return tuple(self.source.splitlines())

    def line(self, lineno: int) -> str:
        """取指定行（1-based）；越界返回空串。"""
        lines = self.source.splitlines()
        if 1 <= lineno <= len(lines):
            return lines[lineno - 1]
        return ""

    @property
    def tree(self) -> ast.Module | None:
        """AST；非 Python 文件或语法错误时返回 `None`。"""
        if not self.rel.endswith(".py"):
            return None
        try:
            return ast.parse(self.source, filename=self.rel)
        except SyntaxError:
            return None


@dataclass(frozen=True)
class RuleContext:
    """规则执行上下文。"""

    root: Path
    files: tuple[FileDoc, ...]
    git_hygiene: bool = False

    def py_files(self, *prefixes: str) -> tuple[FileDoc, ...]:
        """按路径前缀筛选 Python 文件。

        Args:
            prefixes: 路径前缀（posix，相对仓库根）。为空时返回全部 Python 文件。
        """
        result: list[FileDoc] = []
        for doc in self.files:
            if not doc.rel.endswith(".py"):
                continue
            if not prefixes or any(doc.rel.startswith(prefix) for prefix in prefixes):
                result.append(doc)
        return tuple(result)

    def text_files(self, *prefixes: str) -> tuple[FileDoc, ...]:
        """按路径前缀筛选全部文本文件。"""
        if not prefixes:
            return self.files
        return tuple(doc for doc in self.files if doc.rel.startswith(prefixes))


class Rule(Protocol):
    """规则协议 —— 每条规则是一个模块级对象。"""

    code: str
    description: str

    def check(self, ctx: RuleContext) -> Sequence[Violation]:
        """执行检查。"""
        ...
