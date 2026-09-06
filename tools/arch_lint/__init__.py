"""自研架构静态扫描工具。

★ **为什么用 AST 而不是 grep**：误报率决定门禁的生死。

工程师一旦觉得门禁老误报，第一反应是绕过它（加 noqa、改脚本、干脆不跑），
那这道门禁就形同虚设 —— 比没有更糟，因为它给人"有门禁"的错觉。
grep 无法区分 `market == 'cn_a'`（违规）和 `注释里写了 market == 'cn_a'`（无害），
AST 可以。

## 规则清单

| 规则码 | 检查内容 |
| --- | --- |
| ARCH001 | 禁止市场硬编码分支（`market == 'xxx'`、代码前缀 `.startswith('6')`） |
| ARCH002 | 禁止股数字面量（`quantity = 100`） |
| ARCH003 | 禁止价格兜底常量（`price or 100`） |
| ARCH004 | 禁止他人机器绝对路径（`/Users/xxx/`、`C:\\Users\\`） |
| ARCH005 | 禁止 Null 适配器与静默吞异常 |
| ARCH006 | 禁止失败伪装成功（HALTED 写成 COMPLETED） |
| ARCH007 | 跨文件重复代码块 |
| ARCH008 | 因子/指标重复实现 |
| ARCH009 | 入库纪律（`git status --porcelain` 干净） |
| ARCH010 | 导入方向：`domain/` 不得依赖外层 |
| ARCH011 | 反向导入：外部 SDK 只允许在 `adapters/` |
| ARCH012 | 禁止吞掉 `LookaheadViolationError` |
| ARCH013 | 浮点纪律：核心域禁止 float 字面量与 `float(...)` |

## 用法

```bash
python -m tools.arch_lint.cli --root .              # 全量扫描
python -m tools.arch_lint.cli --root . --only ARCH007
python -m tools.arch_lint.cli --root . --git-hygiene  # 含 ARCH009
```

## 豁免

行内豁免必须写理由：`# noqa: ARCH001 -- 这里是加载器，本来就按市场取配置`
存量豁免记在 `baselines.txt`，**每季度 review 一次**（见 `docs/operations.md`）。
"""

from __future__ import annotations

from tools.arch_lint.model import (
    FileDoc,
    Rule,
    RuleContext,
    Violation,
)
from tools.arch_lint.rules.registry import all_rules, get_rule, rule_codes
from tools.arch_lint.runner import scan

__all__ = [
    "FileDoc",
    "Rule",
    "RuleContext",
    "Violation",
    "all_rules",
    "get_rule",
    "rule_codes",
    "scan",
]
