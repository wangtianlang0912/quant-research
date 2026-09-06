"""ARCH014 / ARCH015 门禁自测 —— 与 test_arch_lint_selfcheck.py 同一套策略：

构造最小可复现的违规仓库，跑 `runner.scan()`，断言门禁**能抓到**违规
且**不误伤**合规形态。"门禁抓不到违规"比"没有门禁"更危险。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest
from tools.arch_lint.runner import scan

pytestmark = pytest.mark.architecture

# 夹具需要构造含禁用端点的违规仓库，而 ARCH015 对全仓做子串扫描 ——
# 拼接构造避免本文件自身命中门禁（规则抓的是"复制端点字面量"，
# 测试夹具经拼接动态生成，不在静态文本中出现字面量）
_PUSH2 = "push2" + ".eastmoney.com"
_PUSH2HIS = "push2his" + ".eastmoney.com"


def _init_git_repo(root: Path) -> None:
    """初始化一个最小 git 仓库（discovery 需要）。"""
    git = shutil.which("git") or "git"
    subprocess.run(  # noqa: S603
        [git, "init", "--quiet"], cwd=root, check=True, capture_output=True
    )


def _write(root: Path, rel: str, content: str) -> None:
    """写一个文件（posix 风格相对路径，自动建父目录）。"""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")


@pytest.fixture
def arch_root(tmp_path: Path) -> Path:
    """一份空白 git 仓库根。"""
    _init_git_repo(tmp_path)
    _write(tmp_path, "pyproject.toml", "[project]\nname = 'tmp'\nversion = '0'\n")
    return tmp_path


# ============================================================================
# ARCH014 —— baostock 隔离
# ============================================================================


def test_arch014_白名单文件内_import_放行(arch_root: Path) -> None:
    """两个白名单文件（含函数体内的惰性 import）→ 不报。"""
    _write(
        arch_root,
        "src/quant_v2/adapters/market_data/subprocess_worker.py",
        """
        def f():
            import baostock as bs  # 惰性导入也必须被识别
            return bs
        """,
    )
    _write(
        arch_root,
        "src/quant_v2/adapters/market_data/baostock_cn.py",
        """
        import baostock
        """,
    )
    result = scan(arch_root, only=("ARCH014",), use_baselines=False)
    assert [v.code for v in result.violations if v.code == "ARCH014"] == []


def test_arch014_主进程_import_必抓(arch_root: Path) -> None:
    """引擎/调度器/CLI 里 import baostock → CI 失败。"""
    _write(
        arch_root,
        "src/quant_v2/engines/backtest.py",
        """
        import baostock as bs
        """,
    )
    result = scan(arch_root, only=("ARCH014",), use_baselines=False)
    violations = [v for v in result.violations if v.code == "ARCH014"]
    assert len(violations) == 1
    assert violations[0].path == "src/quant_v2/engines/backtest.py"
    assert "子进程隔离" in violations[0].message


def test_arch014_适配器其他文件_import_也抓(arch_root: Path) -> None:
    """白名单是**逐文件**的：adapters/ 里其他文件 import 同样违规。"""
    _write(
        arch_root,
        "src/quant_v2/adapters/market_data/akshare_cn.py",
        """
        from baostock import query_history_k_data_plus
        """,
    )
    result = scan(arch_root, only=("ARCH014",), use_baselines=False)
    assert len([v for v in result.violations if v.code == "ARCH014"]) == 1


def test_arch014_测试文件_import_也抓(arch_root: Path) -> None:
    """测试不允许 import 真实 baostock（要 fake 就用 sys.modules 注入）。"""
    _write(
        arch_root,
        "tests/unit/adapters/test_x.py",
        """
        import baostock
        """,
    )
    result = scan(arch_root, only=("ARCH014",), use_baselines=False)
    assert len([v for v in result.violations if v.code == "ARCH014"]) == 1


def test_arch014_非baostock_import_不误报(arch_root: Path) -> None:
    """普通 SDK import 归 ARCH011 管，ARCH014 不能抢报。"""
    _write(
        arch_root,
        "src/quant_v2/adapters/market_data/other.py",
        """
        import requests
        """,
    )
    result = scan(arch_root, only=("ARCH014",), use_baselines=False)
    assert [v for v in result.violations if v.code == "ARCH014"] == []


# ============================================================================
# ARCH015 —— 禁用端点
# ============================================================================


def test_arch015_声明点文件_放行(arch_root: Path) -> None:
    """唯一声明点 capabilities.py 本身出现端点字面量 → 不报。"""
    _write(
        arch_root,
        "src/quant_v2/adapters/market_data/capabilities.py",
        f"""
        FORBIDDEN_ENDPOINTS = ("{_PUSH2}", "{_PUSH2HIS}")
        """,
    )
    result = scan(arch_root, only=("ARCH015",), use_baselines=False)
    assert [v for v in result.violations if v.code == "ARCH015"] == []


def test_arch015_其他源码出现端点_必抓(arch_root: Path) -> None:
    _write(
        arch_root,
        "src/quant_v2/adapters/market_data/eastmoney.py",
        f"""
        URL = "https://{_PUSH2}/api/qt/stock/get"
        """,
    )
    result = scan(arch_root, only=("ARCH015",), use_baselines=False)
    violations = [v for v in result.violations if v.code == "ARCH015"]
    assert len(violations) == 1
    assert violations[0].path == "src/quant_v2/adapters/market_data/eastmoney.py"
    assert "M-6" in violations[0].message


def test_arch015_编号子域_同样被抓(arch_root: Path) -> None:
    """给 push2his 端点加编号子域前缀（如 `33.`）→ 子串匹配同样覆盖。"""
    _write(
        arch_root,
        "src/quant_v2/adapters/market_data/spider.py",
        f"""
        URL = "https://33.{_PUSH2HIS}/api/qt/stock/get"
        """,
    )
    result = scan(arch_root, only=("ARCH015",), use_baselines=False)
    assert len([v for v in result.violations if v.code == "ARCH015"]) == 1


def test_arch015_配置文件出现端点_也抓(arch_root: Path) -> None:
    """configs/ 在扫描范围里 —— 配置文件复制端点同样违规。"""
    _write(
        arch_root,
        "configs/sources.yaml",
        f"""
        eastmoney: https://{_PUSH2}
        """,
    )
    result = scan(arch_root, only=("ARCH015",), use_baselines=False)
    assert len([v for v in result.violations if v.code == "ARCH015"]) == 1


def test_arch015_相似但不同的域名_不误报(arch_root: Path) -> None:
    """datacenter-web.eastmoney.com 实测可达（§5.12），不在禁用清单 → 不报。"""
    _write(
        arch_root,
        "src/quant_v2/adapters/market_data/fundamentals.py",
        """
        URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        """,
    )
    result = scan(arch_root, only=("ARCH015",), use_baselines=False)
    assert [v for v in result.violations if v.code == "ARCH015"] == []
