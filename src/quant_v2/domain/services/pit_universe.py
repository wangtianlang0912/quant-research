"""PIT 股票池领域服务（T02.5 / D-05 / M-15 / M-19 / M-20 / M-21 / M-22）。

## 职责边界

本模块是**纯逻辑**（无 I/O、无网络、无 DB）：

- `parse_is_st`：从 `code_name` 正则解析 ST（M-20：接口无独立 ST 字段）；
- `classify_name_change`：名称突变分类（M-21：ST 相关 = INFO，其余 = P0）；
- `diff_snapshots`：相邻两日快照的名称突变检测；
- `sample_dates` / `event_fill_dates`：M-22 采样建池策略（纯日期数学）。

数据获取（`bs.query_all_stock`）在 `adapters/data_sources/`，
持久化在 `adapters/persistence/`，编排在 CLI —— 各司其职。

## 实测基准（写测试时直接引用，不许拍脑袋改）

- `as_of=2007-12-28` 池子必含 600485 / 600087 / 000033 / 600069（当时在市、今已退市）；
- `as_of=2021-06-02` 必不含 600485（已退市）；
- `as_of=1991-06-01`（周六）→ 非交易日，抛错（M-19）；
- `2005-01-04` 快照 1503 行，其中 **137 只**名称含 ST（M-20 实测基准）。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

__all__ = [
    "DAILY_SAMPLE_WINDOW_DAYS",
    "PIT_EARLIEST_DATE",
    "NameChange",
    "NameChangeKind",
    "classify_name_change",
    "diff_snapshots",
    "event_fill_dates",
    "parse_is_st",
    "sample_dates",
]

# M-15：query_all_stock(day=) 最早可用 1990-12-19（上交所开市首日），实测确认
PIT_EARLIEST_DATE = date(1990, 12, 19)

# M-22 采样策略：近 2 年逐日，更早按周
DAILY_SAMPLE_WINDOW_DAYS = 730

# M-20 实测基准：ST 只能从 code_name 解析（1503 只里 tradeStatus=0 仅 10 只，
# 与 137 只 ST 对不上 —— tradeStatus 是停牌标记，不是 ST）
_ST_NAME_RE = re.compile(r"^\*?ST|ST")

# M-21：ST 戴帽/脱帽、退市整理期涉及的名称 token。
# 名称突变若只剩这些 token 的增删 → ST 相关（INFO），否则实质性突变（P0）。
# `退市?` 兼容 "退市海润" 与 "海润退" 两种退市整理期形态。
_ST_TOKEN_RE = re.compile(r"\*?ST|退市?")


def parse_is_st(name: str) -> bool:
    """从证券名称解析 ST 状态（M-20：`is_st_source='NAME_PARSE'`）。

    匹配 `*ST` / `ST` 前缀及名称中任意位置的 `ST`（兼容 `S*ST` / `SST`
    等历史形态 —— 它们都含 "ST" 子串）。实测基准：2005-01-04 快照按此
    规则解析出 137 只。
    """
    return _ST_NAME_RE.search(name) is not None


class NameChangeKind(str, Enum):
    """名称突变的分类（M-21）。"""

    ST = "NAME_CHANGE_ST"  # 仅 ST/*ST/退 相关增删 → INFO（不告警，防噪声刷屏）
    MATERIAL = "NAME_CHANGE_MATERIAL"  # 实质性突变 → P0（疑似代码回收复用 / 重组）


@dataclass(frozen=True)
class NameChange:
    """一次标的名称突变（相邻快照 diff 的产物）。"""

    symbol: str
    as_of: date  # 新名称首次出现的快照日
    old_name: str
    new_name: str
    kind: NameChangeKind


def classify_name_change(old_name: str, new_name: str) -> NameChangeKind:
    """名称突变分类（M-21 白名单）。

    判定规则：把新旧名称中的 ST token（`*ST` / `ST` / `退`）剥掉后相等
    → `ST`（INFO）；否则 → `MATERIAL`（P0）。

    >>> classify_name_change("ST 宏盛", "宏盛")
    <NameChangeKind.ST: 'NAME_CHANGE_ST'>
    >>> classify_name_change("平安银行", "某某科技")
    <NameChangeKind.MATERIAL: 'NAME_CHANGE_MATERIAL'>
    """
    if _strip_st_tokens(old_name) == _strip_st_tokens(new_name):
        return NameChangeKind.ST
    return NameChangeKind.MATERIAL


def _strip_st_tokens(name: str) -> str:
    """剥掉名称中的 ST/退 token 与空白（M-21 白名单的判定基底）。"""
    return _ST_TOKEN_RE.sub("", name).strip()


def diff_snapshots(
    previous: Sequence[tuple[str, str]],
    current: Sequence[tuple[str, str]],
    *,
    as_of: date,
) -> list[NameChange]:
    """相邻两日快照的名称突变 diff（只看两日都在市的标的）。

    Args:
        previous / current: `(symbol, name)` 序列（repo 读取顺序无所谓）。
        as_of: current 的快照日（新名称首次出现日 ≈ 该日，采样粒度内）。

    单边缺席（上市/退市）**不算**名称突变 —— 那是池成员变化，
    由采样策略的事件日补齐处理。
    """
    prev_names = dict(previous)
    changes: list[NameChange] = []
    for symbol, new_name in current:
        old_name = prev_names.get(symbol)
        if old_name is None or old_name == new_name:
            continue
        changes.append(
            NameChange(
                symbol=symbol,
                as_of=as_of,
                old_name=old_name,
                new_name=new_name,
                kind=classify_name_change(old_name, new_name),
            )
        )
    return sorted(changes, key=lambda c: c.symbol)


# ============================================================
# M-22 采样建池（纯日期数学，输入输出都是交易日序列）
# ============================================================


def sample_dates(
    trading_days: Sequence[date],
    *,
    start: date,
    end: date,
    daily_window_days: int = DAILY_SAMPLE_WINDOW_DAYS,
) -> list[date]:
    """M-22 采样计划：近 `daily_window_days` 天逐日 + 更早按周（每 5 个交易日）。

    Args:
        trading_days: 该市场的交易日序列（升序；来源是日历适配器）。
        start / end: 建池区间（含两端；会截断到日历覆盖范围）。

    Returns:
        升序采样日列表。**未采样日的池子由"最近的前一个采样快照"下推**
        （池子在上市/退市事件日之间不变，语义正确；误差只剩 ST 状态切换，
        M-25 量化为任一时刻约 0.03% 标的）。
    """
    if start > end:
        raise ValueError(f"start({start}) 不得晚于 end({end})")
    window_start = end - timedelta(days=daily_window_days)

    days = [d for d in trading_days if start <= d <= end]
    recent = [d for d in days if d >= window_start]
    older = [d for d in days if d < window_start]
    sampled_older = older[::5]  # 每 5 个交易日取 1 个（≈ 每周）
    return sorted({*sampled_older, *recent})


def event_fill_dates(
    previous_date: date,
    current_date: date,
    trading_days: Sequence[date],
    *,
    previous_symbols: Sequence[str],
    current_symbols: Sequence[str],
) -> list[date]:
    """事件日补齐（M-22）：相邻两个采样快照的**池成员集合**有变化时，
    返回两日之间（不含两端）需要补抓的交易日。

    上市/退市是硬事件 —— 周采样最多把新成员的入池日延迟 4 个交易日；
    补齐中间天后，事件日被精确定位（相邻快照成员首次变化的那天）。
    名称变化（ST 切换）不触发补齐 —— 其误差已由 M-25 量化接受。
    """
    if current_date <= previous_date:
        return []
    if set(previous_symbols) == set(current_symbols):
        return []
    return [d for d in trading_days if previous_date < d < current_date]
