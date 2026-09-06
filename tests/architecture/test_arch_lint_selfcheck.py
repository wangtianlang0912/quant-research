"""架构门禁自测 —— "门禁抓不到违规"比"没有门禁"更危险。

★ 设计原则：每条 ARCH 规则都对应一份合成违规样本，断言门禁**能抓到**它。
  若某条规则的检测逻辑退化（重命名常量、漏判分支、改错条件），
  这个测试套件立刻红盘 —— 把"门禁失效"这种灾难从"上线 40 天后才发现"压缩到 PR 阶段。

## 测试策略

不在这里模拟 `FileDoc` / `RuleContext`，那样等于用门禁自己的代码测试门禁。
真正的自测要做的是：**构造最小可复现的违规仓库**，跑 `runner.scan()`，
断言每条规则的违规出现在结果里。

具体做法：用 `tmp_path`（pytest fixture）建一个临时仓库目录，写入：
- 受门禁扫描的代码（`src/quant_v2/...` 等最小子集）
- 故意植入每条规则对应形态的代码
- 一个空的 `pyproject.toml` / `.git` 让 `discover()` 正常工作
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest
from tools.arch_lint.runner import scan

# 这些 marker 已注册，跑测试需先 import conftest 触发
pytestmark = pytest.mark.architecture


def _init_git_repo(root: Path) -> None:
    """初始化一个最小 git 仓库（ARCH009 需要真实 git 元数据）。"""
    git = shutil.which("git") or "git"
    subprocess.run(  # noqa: S603
        [git, "init", "--quiet"], cwd=root, check=True, capture_output=True
    )
    subprocess.run(  # noqa: S603
        [git, "config", "user.email", "test@example.com"], cwd=root, check=True, capture_output=True
    )
    subprocess.run(  # noqa: S603
        [git, "config", "user.name", "Test"], cwd=root, check=True, capture_output=True
    )


def _write(root: Path, rel: str, content: str) -> None:
    """写一个文件（posix 风格相对路径，自动建父目录）。"""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")


def _codes(result) -> set[str]:
    """提取一次扫描结果里的全部规则码。"""
    return {v.code for v in result.violations}


def _violations_for(result, code: str) -> list:
    """某条规则的所有违规。"""
    return [v for v in result.violations if v.code == code]


@pytest.fixture
def arch_root(tmp_path: Path) -> Path:
    """一份空白 git 仓库根，门禁要扫描 src/tools/tests/configs/scripts。"""
    _init_git_repo(tmp_path)
    # ★ 写一个最简 baseline 配置文件，避免 discovery 的 `pyproject.toml` 解析出错
    _write(tmp_path, "pyproject.toml", "[project]\nname = 'tmp'\nversion = '0'\n")
    return tmp_path


# ============================================================================
# ARCH001 —— 禁止市场硬编码分支
# ============================================================================


def test_arch001_catches_market_string_compare(arch_root: Path) -> None:
    """市场字符串与字面量做 `==` 比较 → 必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/engines/strategy.py",
        """
        def pick(market: str, code: str) -> bool:
            return market == 'cn_a'   # ARCH001
        """,
    )
    result = scan(arch_root, only=("ARCH001",), use_baselines=False)
    assert "ARCH001" in _codes(result)


def test_arch001_catches_startswith(arch_root: Path) -> None:
    """`code.startswith('6')` 这种代码前缀判断也要被抓。"""
    _write(
        arch_root,
        "src/quant_v2/engines/strategy.py",
        """
        def is_sh(code: str) -> bool:
            return code.startswith('6')   # ARCH001
        """,
    )
    result = scan(arch_root, only=("ARCH001",), use_baselines=False)
    assert "ARCH001" in _codes(result)


def test_arch001_ignores_variable_right_side(arch_root: Path) -> None:
    """`if market not in spec.markets` —— 右侧是变量，不该误报。"""
    _write(
        arch_root,
        "src/quant_v2/engines/strategy.py",
        """
        def pick(market: str, spec) -> bool:
            return market not in spec.markets    # 合法
        """,
    )
    result = scan(arch_root, only=("ARCH001",), use_baselines=False)
    assert _violations_for(result, "ARCH001") == []


# ============================================================================
# ARCH002 —— 禁止股数字面量
# ============================================================================


def test_arch002_catches_quantity_assignment(arch_root: Path) -> None:
    """`quantity = 100` —— 必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/strategies/buy.py",
        """
        def allocate() -> int:
            quantity = 100   # ARCH002
            return quantity
        """,
    )
    result = scan(arch_root, only=("ARCH002",), use_baselines=False)
    assert "ARCH002" in _codes(result)


def test_arch002_catches_decimal_wrapped_literal(arch_root: Path) -> None:
    """`quantity = Decimal(100)` —— 必须被抓（与 v1 的真实 bug 同形）。

    门禁只识别 `Decimal(<数字>)`，不识别 `Decimal('<数字>')`（后者不是数字字面量，
    而是字符串字面量，需要运行时求值 —— 它不会被这条规则判违规，但
    Ruff/类型检查能抓到）。
    """
    _write(
        arch_root,
        "src/quant_v2/strategies/buy.py",
        """
        from decimal import Decimal
        def allocate() -> Decimal:
            quantity = Decimal(100)   # ARCH002
            return quantity
        """,
    )
    result = scan(arch_root, only=("ARCH002",), use_baselines=False)
    assert "ARCH002" in _codes(result)


def test_arch002_catches_keyword_arg(arch_root: Path) -> None:
    """`place_order(qty=200)` —— 必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/strategies/buy.py",
        """
        def go(place_order) -> None:
            place_order(qty=200)   # ARCH002
        """,
    )
    result = scan(arch_root, only=("ARCH002",), use_baselines=False)
    assert "ARCH002" in _codes(result)


# ============================================================================
# ARCH003 —— 禁止价格兜底常量
# ============================================================================


def test_arch003_catches_or_fallback(arch_root: Path) -> None:
    """`price = value or 100` —— 幻影价（v1 反例复现）。

    名字必须是 ARCH003 的 PRICE_HINTS（price/px/last/mark/close）才会被规则匹配。
    """
    _write(
        arch_root,
        "src/quant_v2/adapters/pricing.py",
        """
        def get(price):
            px = price or 100   # ARCH003
            return px
        """,
    )
    result = scan(arch_root, only=("ARCH003",), use_baselines=False)
    assert "ARCH003" in _codes(result)


def test_arch003_catches_dict_get_default(arch_root: Path) -> None:
    """`price_data.get('close', 100)` —— 必须被抓。

    门禁的判定对象是 `.get` 的**接收者**：必须是"价格类"变量名（price/px/last/...）。
    `data.get('price', 100)` 这种调用方名字不带 price hint 的不会被抓（这是规则
    的明确取舍 —— 接收方是 dict 时没有普适启发式，把所有 dict.get 都判违规
    误报太多）。
    """
    _write(
        arch_root,
        "src/quant_v2/adapters/pricing.py",
        """
        def get(price_data):
            close = price_data.get('close', 100)   # ARCH003
            return close
        """,
    )
    result = scan(arch_root, only=("ARCH003",), use_baselines=False)
    assert "ARCH003" in _codes(result)


def test_arch003_catches_if_not_price(arch_root: Path) -> None:
    """`if not price: price = 100` —— 也必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/adapters/pricing.py",
        """
        def get(price):
            if not price:
                price = 100   # ARCH003
            return price
        """,
    )
    result = scan(arch_root, only=("ARCH003",), use_baselines=False)
    assert "ARCH003" in _codes(result)


def test_arch003_catches_except_fallback(arch_root: Path) -> None:
    """`except: price = 100` —— v1 最危险的 P0，必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/adapters/pricing.py",
        """
        def get():
            try:
                price = fetch()
            except Exception:
                price = 100   # ARCH003
            return price
        """,
    )
    result = scan(arch_root, only=("ARCH003",), use_baselines=False)
    assert "ARCH003" in _codes(result)


# ============================================================================
# ARCH004 —— 禁止他人机器绝对路径
# ============================================================================


def test_arch004_catches_user_path(arch_root: Path) -> None:
    """`/Users/<name>/` —— 必须在 Python 源码里被抓。"""
    _write(
        arch_root,
        "scripts/load.py",
        """
        DATA = '/Users/heihen/data/'
        """,
    )
    result = scan(arch_root, only=("ARCH004",), use_baselines=False)
    assert "ARCH004" in _codes(result)


def test_arch004_catches_yaml_and_md(arch_root: Path) -> None:
    """绝对路径也常出现在 YAML/Markdown 里 —— 门禁必须扫到。"""
    _write(arch_root, "configs/path.yaml", "root: /Users/bob/qclaw/\n")
    _write(arch_root, "docs/runbook.md", "把数据放在 `/home/alice/data/`。\n")
    result = scan(arch_root, only=("ARCH004",), use_baselines=False)
    assert "ARCH004" in _codes(result)


def test_arch004_self_exempt(arch_root: Path) -> None:
    """`tests/architecture/` 与 `tools/arch_lint/` 自检豁免。

    这两个目录里写"绝对路径字面量"是合法的（门禁自测必然包含字面量样本、
    arch_lint 自身规则定义也要列示例）。豁免范围**只能**是这两处；其余代码
    一律要被抓。
    """
    # 自检目录里写违规字面量 → 必须不被抓（豁免生效）
    arch_self_dir = arch_root / "tests" / "architecture"
    arch_self_dir.mkdir(parents=True, exist_ok=True)
    (arch_self_dir / "fixture.py").write_text("X = '/Users/heihen/data/'\n", encoding="utf-8")
    # 仓库其他位置写违规字面量 → 必须被抓
    _write(
        arch_root,
        "src/quant_v2/strategies/x.py",
        "P = '/Users/leon/qclaw/'\n",
    )
    result = scan(arch_root, only=("ARCH004",), use_baselines=False)
    violations = _violations_for(result, "ARCH004")
    paths = {v.path for v in violations}
    assert any("strategies" in p for p in paths), violations
    assert not any("tests/architecture" in p for p in paths), violations


# ============================================================================
# ARCH005 —— 禁止 Null 适配器与静默吞异常
# ============================================================================


def test_arch005_catches_null_adapter_class_name(arch_root: Path) -> None:
    """`class NullNotificationAdapter` —— v1 反例复现。"""
    _write(
        arch_root,
        "src/quant_v2/adapters/notifier.py",
        """
        class NullNotificationAdapter:   # ARCH005
            pass
        """,
    )
    result = scan(arch_root, only=("ARCH005",), use_baselines=False)
    assert "ARCH005" in _codes(result)


def test_arch005_catches_empty_except(arch_root: Path) -> None:
    """`except Exception: pass` —— 必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/strategies/run.py",
        """
        def run():
            try:
                do()
            except Exception:
                pass    # ARCH005
        """,
    )
    result = scan(arch_root, only=("ARCH005",), use_baselines=False)
    assert "ARCH005" in _codes(result)


def test_arch005_allows_logged_except(arch_root: Path) -> None:
    """`except Exception: log.error(...)` —— 不该被报。"""
    _write(
        arch_root,
        "src/quant_v2/strategies/run.py",
        """
        def run():
            try:
                do()
            except Exception:
                log.error('boom')    # 合法
        """,
    )
    result = scan(arch_root, only=("ARCH005",), use_baselines=False)
    assert _violations_for(result, "ARCH005") == []


# ============================================================================
# ARCH006 —— 禁止失败伪装成功
# ============================================================================


def test_arch006_catches_completed_in_except(arch_root: Path) -> None:
    """except 块内报 COMPLETED —— v1 反例。"""
    _write(
        arch_root,
        "src/quant_v2/orchestration/run.py",
        """
        def go():
            try:
                do()
            except Exception:
                return RunStatus.COMPLETED   # ARCH006
        """,
    )
    result = scan(arch_root, only=("ARCH006",), use_baselines=False)
    assert "ARCH006" in _codes(result)


def test_arch006_catches_completed_after_halted_check(arch_root: Path) -> None:
    """`if HALTED: ... COMPLETED` 也算伪装成功。"""
    _write(
        arch_root,
        "src/quant_v2/orchestration/run.py",
        """
        def go(status):
            if status == RunStatus.HALTED:
                return RunStatus.COMPLETED   # ARCH006
        """,
    )
    result = scan(arch_root, only=("ARCH006",), use_baselines=False)
    assert "ARCH006" in _codes(result)


# ============================================================================
# ARCH007 —— 跨文件重复代码块（10 条连续语句 token 哈希相同）
# ============================================================================


def _ten_stmt_block(label: str) -> str:
    """生成 10 条会被 ARCH007 抓的 token 规范化后相同的语句。
    改名 a/b 后 token 序列也一致（变量名被规整为 NAME）。"""
    return "\n".join(
        [
            f"def func_{label}():",
            f"    a = {label}_x",
            "    b = a + 1",
            "    c = b * 2",
            "    d = c - 3",
            "    e = d / 4",
            "    f = e + 5",
            "    g = f - 6",
            "    h = g * 7",
            "    i = h + 8",
            "    j = i - 9",
            "    return j",
        ]
    )


def test_arch007_catches_cross_file_duplication(arch_root: Path) -> None:
    """两个不同文件里出现 token 相同的 10 条连续语句 → 必须被抓。"""
    _write(arch_root, "src/quant_v2/strategies/a.py", _ten_stmt_block("alpha"))
    _write(arch_root, "src/quant_v2/strategies/b.py", _ten_stmt_block("beta"))
    result = scan(arch_root, only=("ARCH007",), use_baselines=False)
    assert "ARCH007" in _codes(result)


def test_arch007_allows_declarative_block(arch_root: Path) -> None:
    """声明式常量块（类成员声明）即使完全相同也不该误报。"""
    declarative = "\n".join(f"NAME_{i} = '{i}'" for i in range(12))
    _write(arch_root, "src/quant_v2/strategies/a.py", declarative)
    _write(arch_root, "src/quant_v2/strategies/b.py", declarative)
    result = scan(arch_root, only=("ARCH007",), use_baselines=False)
    assert _violations_for(result, "ARCH007") == []


# ============================================================================
# ARCH008 —— 因子/指标重复实现（函数体 token Jaccard ≥ 0.85）
# ============================================================================


def _long_function(label: str) -> str:
    """足够长的函数体，使 token 序列超过 MIN_TOKENS=30 且与 _long_function 的另一版本高度相似。"""
    return "\n".join(
        [
            f"def compute_{label}(series, window):",
            "    acc = 0",
            "    out = []",
            "    for k, v in enumerate(series):",
            "        acc = acc + v",
            "        if k >= window:",
            "            acc = acc - series[k - window]",
            "        if k >= window - 1:",
            "            out.append(acc / window)",
            "        else:",
            "            out.append(None)",
            "    final = out[-1]",
            "    if final is None:",
            "        final = 0",
            "    return final",
        ]
    )


def test_arch008_catches_function_body_clone(arch_root: Path) -> None:
    """两个结构相同的函数（变量名改了）→ 必须被抓。"""
    _write(arch_root, "src/quant_v2/indicators/sma_one.py", _long_function("alpha"))
    _write(arch_root, "src/quant_v2/indicators/sma_two.py", _long_function("beta"))
    result = scan(arch_root, only=("ARCH008",), use_baselines=False)
    assert "ARCH008" in _codes(result)


# ============================================================================
# ARCH009 —— 入库纪律（默认关闭，显式开启后才生效）
# ============================================================================


def test_arch009_off_by_default(arch_root: Path) -> None:
    """默认（git_hygiene=False）ARCH009 不报。"""
    _write(arch_root, "scripts/dirty.py", "x = 1\n")
    # 不 commit，让它保持未跟踪状态
    result = scan(arch_root, only=("ARCH009",), use_baselines=False)
    assert _violations_for(result, "ARCH009") == []


def test_arch009_catches_untracked_when_enabled(arch_root: Path) -> None:
    """开启 git_hygiene 后，未跟踪文件必须被抓。"""
    _write(arch_root, "scripts/dirty.py", "x = 1\n")
    result = scan(arch_root, only=("ARCH009",), use_baselines=False, git_hygiene=True)
    assert "ARCH009" in _codes(result)


def test_arch009_clean_when_committed(arch_root: Path) -> None:
    """全部文件已 commit 且工作区干净 → 即使开启 git_hygiene 也不报。"""
    _write(arch_root, "scripts/clean.py", "x = 1\n")
    git = shutil.which("git") or "git"
    subprocess.run(  # noqa: S603
        [git, "add", "-A"], cwd=arch_root, check=True, capture_output=True
    )
    subprocess.run(  # noqa: S603
        [git, "commit", "--quiet", "-m", "init"], cwd=arch_root, check=True, capture_output=True
    )
    result = scan(arch_root, only=("ARCH009",), use_baselines=False, git_hygiene=True)
    assert _violations_for(result, "ARCH009") == []


# ============================================================================
# ARCH010 —— domain/ 不得依赖外层（量化 v2 入口防线）
# ============================================================================


def test_arch010_catches_forbidden_third_party(arch_root: Path) -> None:
    """domain/ 内 import pandas → 必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/domain/services/x.py",
        """
        import pandas as pd    # ARCH010
        """,
    )
    result = scan(arch_root, only=("ARCH010",), use_baselines=False)
    assert "ARCH010" in _codes(result)


def test_arch010_catches_forbidden_project_module(arch_root: Path) -> None:
    """domain/ 内 import quant_v2.adapters → 必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/domain/services/x.py",
        """
        from quant_v2.adapters.pricing import get_price    # ARCH010
        """,
    )
    result = scan(arch_root, only=("ARCH010",), use_baselines=False)
    assert "ARCH010" in _codes(result)


def test_arch010_allows_pydantic(arch_root: Path) -> None:
    """domain/ 内 import pydantic —— 合法，不该被报。"""
    _write(
        arch_root,
        "src/quant_v2/domain/models/x.py",
        """
        from pydantic import BaseModel    # 合法
        """,
    )
    result = scan(arch_root, only=("ARCH010",), use_baselines=False)
    assert _violations_for(result, "ARCH010") == []


# ============================================================================
# ARCH011 —— 反向导入方向：外部 SDK 只允许在 adapters/
# ============================================================================


def test_arch011_catches_akshare_outside_adapters(arch_root: Path) -> None:
    """engines/ 里 import akshare → 必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/engines/scan.py",
        """
        import akshare as ak    # ARCH011
        """,
    )
    result = scan(arch_root, only=("ARCH011",), use_baselines=False)
    assert "ARCH011" in _codes(result)


def test_arch011_allows_akshare_in_adapters(arch_root: Path) -> None:
    """adapters/ 里 import akshare —— 合法。"""
    _write(
        arch_root,
        "src/quant_v2/adapters/source.py",
        """
        import akshare as ak    # 合法
        """,
    )
    result = scan(arch_root, only=("ARCH011",), use_baselines=False)
    assert _violations_for(result, "ARCH011") == []


# ============================================================================
# ARCH012 —— 引擎/编排层禁止吞异常
# ============================================================================


def test_arch012_catches_empty_except_in_engines(arch_root: Path) -> None:
    """engines/ 里空 except → 必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/engines/run.py",
        """
        def go():
            try:
                do()
            except Exception:
                pass    # ARCH012
        """,
    )
    result = scan(arch_root, only=("ARCH012",), use_baselines=False)
    assert "ARCH012" in _codes(result)


def test_arch012_catches_swalLOWED_lookahead(arch_root: Path) -> None:
    """`except LookaheadViolationError: pass` —— v1 真实场景，必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/engines/backtest.py",
        """
        from quant_v2.domain.guard.safe_series import LookaheadViolationError
        def go():
            try:
                run()
            except LookaheadViolationError:
                pass    # ARCH012
        """,
    )
    result = scan(arch_root, only=("ARCH012",), use_baselines=False)
    assert "ARCH012" in _codes(result)


def test_arch012_allows_logged_except_in_engines(arch_root: Path) -> None:
    """`except Exception: log.error(...)` —— 合法。"""
    _write(
        arch_root,
        "src/quant_v2/engines/run.py",
        """
        def go():
            try:
                do()
            except Exception:
                log.error('boom')    # 合法
        """,
    )
    result = scan(arch_root, only=("ARCH012",), use_baselines=False)
    assert _violations_for(result, "ARCH012") == []


# ============================================================================
# ARCH013 —— 核心域禁止 float
# ============================================================================


def test_arch013_catches_float_literal(arch_root: Path) -> None:
    """domain/ 内写 `0.1` → 必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/domain/services/x.py",
        """
        RATE = 0.1    # ARCH013
        """,
    )
    result = scan(arch_root, only=("ARCH013",), use_baselines=False)
    assert "ARCH013" in _codes(result)


def test_arch013_catches_float_call(arch_root: Path) -> None:
    """`float(x)` —— 也必须被抓。"""
    _write(
        arch_root,
        "src/quant_v2/indicators/x.py",
        """
        def f(x):
            return float(x)    # ARCH013
        """,
    )
    result = scan(arch_root, only=("ARCH013",), use_baselines=False)
    assert "ARCH013" in _codes(result)


def test_arch013_allows_decimal_literal(arch_root: Path) -> None:
    """`Decimal('0.1')` —— 合法（字符串不是浮点）。"""
    _write(
        arch_root,
        "src/quant_v2/indicators/x.py",
        """
        from decimal import Decimal
        RATE = Decimal('0.1')    # 合法
        """,
    )
    result = scan(arch_root, only=("ARCH013",), use_baselines=False)
    assert _violations_for(result, "ARCH013") == []


# ============================================================================
# runner.scan —— 顶层编排
# ============================================================================


def test_scan_returns_sortable_codes(arch_root: Path) -> None:
    """`only=` 参数按规则码顺序跑，结果按 path/line/code 排序。"""
    _write(
        arch_root,
        "src/quant_v2/strategies/a.py",
        "quantity = 100\n",
    )
    _write(
        arch_root,
        "src/quant_v2/strategies/b.py",
        "quantity = 200\n",
    )
    result = scan(arch_root, only=("ARCH002",), use_baselines=False)
    paths = [v.path for v in result.violations]
    assert paths == sorted(paths)


def test_scan_unknown_code_raises(arch_root: Path) -> None:
    """`only=` 包含未知规则码 → 必须抛 KeyError（防止"静默没跑"）。"""
    with pytest.raises(KeyError, match="未知规则"):
        scan(arch_root, only=("ARCH999",), use_baselines=False)


def test_scan_baselines_suppress_known_violations(arch_root: Path, monkeypatch) -> None:
    """基线豁免：写入 baselines.txt 的 (path, line, code) 应被剔除。

    `noqa.load_baselines` 用相对 cwd 的 `tools/arch_lint/baselines.txt`，
    因此临时仓库目录会被 chdir 进去。
    """
    _write(
        arch_root,
        "src/quant_v2/strategies/a.py",
        "quantity = 100\n",
    )
    baseline = arch_root / "tools" / "arch_lint" / "baselines.txt"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text(
        "src/quant_v2/strategies/a.py:1:ARCH002 -- 已知遗留，下版清\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(arch_root)
    result = scan(arch_root, only=("ARCH002",), use_baselines=True)
    assert _violations_for(result, "ARCH002") == []
