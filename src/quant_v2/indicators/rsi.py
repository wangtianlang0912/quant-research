"""RSI —— **Wilder 平滑口径**。

★ v1 用的是简单均值（`sum(gains)/n`），不是 Wilder 平滑。
这两者在数值上差得比想象中大，而且**收敛速度不同**：
简单均值对新信息反应过快，Wilder 平滑更接近经典 RSI 的定义（也接近行情软件）。

## 口径

- 涨跌幅度：`delta[i] = close[i] - close[i-1]`（`i >= 1`）
- 上涨幅度 `gain[i] = max(delta[i], 0)`，下跌幅度 `loss[i] = max(-delta[i], 0)`
- 用 `wilder_smooth` 分别平滑 gain 与 loss，周期 n
- `RS = avg_gain / avg_loss`，`RSI = 100 - 100 / (1 + RS)`

首个有效值出现在下标 `n`（需要 n 个 delta，delta 从下标 1 开始）。

**边界约定**：

- `avg_loss == 0 且 avg_gain > 0` → RSI = 100（只涨不跌）
- `avg_loss == 0 且 avg_gain == 0` → RSI = 50（完全无波动，中性）

  后者是自己拍的：0/0 在数学上无定义，但"横盘到一动不动"给 100 会误导用户
  以为这是极强的上涨趋势。取中性值 50 更诚实。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from quant_v2.indicators._smoothing import ZERO, prepare_series, wilder_smooth

__all__ = ["MIN_BARS", "RSI_MAX", "RSI_NEUTRAL", "rsi"]

RSI_MAX: Decimal = Decimal("100")
RSI_NEUTRAL: Decimal = Decimal("50")

# RSI 从**相邻两日之差**起算：只有一根 bar 就没有 delta，也就无从谈强弱。
MIN_BARS: int = 2


def rsi(closes: Sequence[Decimal | None], n: int = 14) -> list[Decimal | None]:
    """相对强弱指标（Wilder 口径）。

    Args:
        closes: 收盘价序列（允许前缀 `None`）。
        n: 周期，默认 14。

    Returns:
        与输入等长的 RSI 列表；下标 `0..n-1` 为 `None`。

    Raises:
        ValueError: `n` 非正、长度不足，或预热期之后出现空洞。
    """
    if n <= 0:
        raise ValueError(f"周期必须为正，收到 {n}")

    total = len(closes)
    out: list[Decimal | None] = [None] * total

    # prepare_series 统一处理"前缀 None = 预热期"并拒绝中间空洞，
    # 不在这里另写一套 —— 两套校验口径迟早会漂移（诊断 #12）。
    start, dense = prepare_series(closes)
    if len(dense) < MIN_BARS:
        return out

    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for index in range(1, len(dense)):
        delta = dense[index] - dense[index - 1]
        gains.append(delta if delta > ZERO else ZERO)
        losses.append(-delta if delta < ZERO else ZERO)

    smoothed_gain = wilder_smooth(gains, n)
    smoothed_loss = wilder_smooth(losses, n)

    for offset in range(len(gains)):
        avg_gain = smoothed_gain[offset]
        avg_loss = smoothed_loss[offset]
        if avg_gain is None or avg_loss is None:
            continue
        if avg_loss == ZERO:
            # 只涨不跌 = 100；完全无波动 = 中性 50（见模块 docstring）
            value = RSI_MAX if avg_gain > ZERO else RSI_NEUTRAL
        else:
            rs = avg_gain / avg_loss
            value = RSI_MAX - (RSI_MAX / (Decimal(1) + rs))
        out[start + 1 + offset] = value
    return out
