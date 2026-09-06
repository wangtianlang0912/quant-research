"""向量化指标库 —— 单一实现 + golden 测试（诊断 #12）。

★ v1 的指标散落在 `factor_scanner.py`、`breakout_scorer.py`、`scripts/phase0_*.py` 等
至少四处，同一指标有多个版本且口径不同（MACD 的 O(n²) 前缀重算、
RSI 用简单均值代替 Wilder 平滑）。改一个忘另一个是必然的。

## 统一约定

1. **输入输出等长、下标对齐**：输出第 i 项对应输入第 i 项。
   预热期一律用 `None`，**不截断序列** —— v1 的 `difs` 截断到 `len(closes)-26`
   是下标错位的直接原因。
2. **允许前缀 `None`**：上游（如 MACD 的 dif → dea）可以直接把带预热期的序列喂进来。
   **前缀之后不允许空洞**，出现即报错（静默跳过会掩盖数据缺失）。
3. **全程 Decimal**：ARCH013 强制，指标层不允许出现 float。
4. **单次遍历 O(n)**：禁止在循环里重算前缀。

## 目录

| 模块 | 函数 | 首个有效下标 |
| --- | --- | --- |
| `ma.py` | `sma(values, n)` | `n - 1` |
| `ema.py` | `ema(values, n)` | `n - 1` |
| `macd.py` | `macd(closes, fast, slow, signal)` | `dif: slow-1`，`dea: slow+signal-2` |
| `rsi.py` | `rsi(closes, n=14)`（Wilder） | `n` |
| `atr.py` | `true_range(...)`, `atr(..., n=14)`（Wilder） | `n - 1` |
| `donchian.py` | `donchian(...)`, `donchian_prior(...)` | `n - 1` / `n` |

`_smoothing.py` 是内部共享工具（预热期处理 + Wilder 平滑），不对外暴露为指标。
"""

from __future__ import annotations

from quant_v2.indicators.atr import atr, true_range
from quant_v2.indicators.donchian import DonchianResult, donchian, donchian_prior
from quant_v2.indicators.ema import ema
from quant_v2.indicators.ma import sma
from quant_v2.indicators.macd import MACDResult, macd
from quant_v2.indicators.rsi import rsi

__all__ = [
    "DonchianResult",
    "MACDResult",
    "atr",
    "donchian",
    "donchian_prior",
    "ema",
    "macd",
    "rsi",
    "sma",
    "true_range",
]
