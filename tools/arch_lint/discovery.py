"""文件发现。

扫描范围刻意**显式列举**而不是"扫整个仓库"：

- 避免扫到 `.venv/`、`var/`、`node_modules/` 里的第三方代码
- 避免扫到 `docs/archive/` 里的 v1 历史存档（那是历史记录，不是当前代码）
- 让"哪些文件受门禁约束"这件事一眼可见
"""

from __future__ import annotations

from pathlib import Path

from tools.arch_lint.model import FileDoc

__all__ = ["ROOT_PATTERNS", "SCAN_DIRS", "TEXT_SUFFIXES", "discover"]

# 受门禁约束的顶层目录
SCAN_DIRS: tuple[str, ...] = ("src", "tools", "tests", "scripts", "configs")

# 仓库根目录下的直接文件
ROOT_PATTERNS: tuple[str, ...] = (
    "*.py",
    "*.toml",
    "*.cfg",
    "*.ini",
    "*.md",
    "*.txt",
    "*.yaml",
    "*.yml",
    "*.sh",
    "*.sql",
)

TEXT_SUFFIXES: frozenset[str] = frozenset(
    {".py", ".toml", ".cfg", ".ini", ".md", ".txt", ".yaml", ".yml", ".sh", ".sql", ".json"}
)

# 永远跳过
_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "var",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        "dist",
        "build",
    }
)

_MAX_FILE_BYTES: int = 2 * 1024 * 1024


def _read(path: Path) -> str | None:
    """读取文本文件；二进制或超大文件返回 `None`。"""
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _iter_dir(root: Path, directory: str) -> list[FileDoc]:
    """递归收集一个顶层目录下的文本文件。"""
    base = root / directory
    if not base.is_dir():
        return []
    docs: list[FileDoc] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        source = _read(path)
        if source is None:
            continue
        docs.append(FileDoc(rel=path.relative_to(root).as_posix(), abs_path=path, source=source))
    return docs


def discover(root: Path) -> tuple[FileDoc, ...]:
    """发现全部受扫描的文件。

    Args:
        root: 仓库根。

    Returns:
        `FileDoc` 元组，按路径排序（保证输出稳定、可 diff）。
    """
    docs: list[FileDoc] = []
    for directory in SCAN_DIRS:
        docs.extend(_iter_dir(root, directory))

    for pattern in ROOT_PATTERNS:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            source = _read(path)
            if source is None:
                continue
            docs.append(FileDoc(rel=path.name, abs_path=path, source=source))

    deduped = {doc.rel: doc for doc in docs}
    return tuple(deduped[key] for key in sorted(deduped))
