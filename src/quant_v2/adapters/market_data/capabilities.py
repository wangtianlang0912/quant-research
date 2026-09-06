"""数据源能力声明（§4.2 / §5.2）—— 全部字段实测回填，禁止拍脑袋填 True。

## 为什么能力是一等公民

v1 的问题不是"没有数据源"，而是**没人知道当前数据源缺什么**：
- 拿"今天在市的池子"回测历史 → 幸存者偏差（不知道源没有退市股）
- 用东财 push2 → 每次调用 ProxyError（不知道该端点在本网络不可达）
- 以为有复权因子 → 实际只有复权后价格，三视图互算全错

v2 把"源能干什么 / 不能干什么"变成**显式声明 + 部署时探活回填**：
`reachable` / `forbidden_endpoints` 由 `qv2 ops probe-sources`（T02.2b）写入。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

__all__ = [
    "AKSHARE_CAPABILITIES",
    "BAOSTOCK_CAPABILITIES",
    "FORBIDDEN_ENDPOINTS",
    "TENCENT_CAPABILITIES",
    "DataCapabilities",
    "SourceHealth",
]

# ★ M-6 实测：东财 push2 系列在本网络 TCP 建连失败，调用必 ProxyError。
#   架构上禁用（ARCH015 扫描的字面量清单就从这里来 —— 本文件是唯一允许
#   出现这些域名的声明点）。
FORBIDDEN_ENDPOINTS: tuple[str, ...] = (
    "push2.eastmoney.com",
    "push2his.eastmoney.com",
)


@dataclass(frozen=True)
class DataCapabilities:
    """数据源能力声明。★ 全部字段均为实测回填，禁止拍脑袋填 True。"""

    # —— 数据可得性 ——
    daily_bars: bool = True
    adj_factor: bool = True  # 给的是"因子"还是"复权后价格"
    adj_factor_field: str | None = None  # ★ M-5：'backAdjustFactor'
    delisting_history: Literal["FULL", "PARTIAL", "NONE"] = "NONE"  # ★ OQ-8
    delisting_list: bool = False  # 能否拿到退市名单 + 退市日期
    list_date: bool = False  # 能否拿到上市日期
    trading_calendar: bool = True
    half_day_marker: bool = False  # ★ M-7：实测两个源都没有，恒 False → 只能手工表
    fundamentals: bool = False
    fundamentals_delisted_endpoint: str | None = None  # ★ M-10：退市股专用财报接口
    intraday: bool = False

    # —— 运行时特性（实测硬约束，直接影响抓取器实现）——
    rate_limit_per_min: int | None = None
    requires_subprocess_isolation: bool = False  # ★ M-3：会无限挂起，必须子进程 + 硬 kill
    protocol: Literal["HTTP", "RAW_TCP"] = "HTTP"  # ★ M-9：baostock 裸 TCP，不认 HTTP_PROXY
    honors_proxy_env: bool = True
    reachable: bool | None = None  # ★ M-6：部署前探活结果，None=未探活
    forbidden_endpoints: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceHealth:
    """一次 healthcheck 的结果（带短超时，默认 10s）。"""

    source_id: str
    reachable: bool
    checked_at: datetime
    latency_s: float | None = None
    detail: str = ""


# ============================================================
# baostock —— 主源（重活：历史全量 / 复权因子 / PIT 日快照 / 退市股）
# ============================================================
BAOSTOCK_CAPABILITIES = DataCapabilities(
    daily_bars=True,
    adj_factor=True,
    adj_factor_field="backAdjustFactor",  # ★ M-5：只用 backAdjustFactor
    delisting_history="FULL",  # 退市股历史行情完整（akshare 0/6）
    delisting_list=True,
    list_date=True,
    trading_calendar=True,
    half_day_marker=False,
    fundamentals=False,
    intraday=False,
    # ★ M-17：含子进程隔离开销的真实吞吐 43.6 req/min，按 40 排期
    rate_limit_per_min=40,
    requires_subprocess_isolation=True,  # ★ M-3/M-14：会无限挂起 + 会话劣化
    protocol="RAW_TCP",  # ★ M-9：裸 TCP，不认 HTTP_PROXY
    honors_proxy_env=False,
    reachable=None,  # 部署机探活后回填（qv2 ops probe-sources）
    forbidden_endpoints=FORBIDDEN_ENDPOINTS,
)


def utc_now() -> datetime:
    """能力模块自用的 UTC 时点（healthcheck 打时间戳）。"""
    return datetime.now(UTC)


# ============================================================
# akshare —— 备源（快活：每日增量；新浪/腾讯通道，东财 push2 通道禁用）
# ============================================================
AKSHARE_CAPABILITIES = DataCapabilities(
    daily_bars=True,
    adj_factor=False,  # ★ 新浪通道只给价格列，无复权因子（M-8 实测）
    adj_factor_field=None,
    delisting_history="PARTIAL",  # 退市股仅腾讯通道部分可达（M-1 实测 0/6）
    delisting_list=True,
    list_date=True,
    trading_calendar=True,  # tool_trade_date_hist_sina
    half_day_marker=False,
    fundamentals=True,  # 财报走 datacenter-web（实测 200，非 push2）
    intraday=False,
    # ★ M-8 实测 155 req/min，按 120 排期（5000 标的 8 并发约 4 分钟）
    rate_limit_per_min=120,
    requires_subprocess_isolation=False,  # HTTP 通道，超时可控，无需隔离
    protocol="HTTP",
    honors_proxy_env=True,
    reachable=None,  # 部署机探活后回填（qv2 ops probe-sources）
    forbidden_endpoints=FORBIDDEN_ENDPOINTS,
)


# ============================================================
# tencent —— 兜底（退市股行情交叉验证，不进回测主链路）
# ============================================================
TENCENT_CAPABILITIES = DataCapabilities(
    daily_bars=True,
    adj_factor=False,  # 腾讯 kline 只给 OHLCV，无因子
    adj_factor_field=None,
    delisting_history="PARTIAL",  # 退市股 stock_zh_a_hist_tx 实测可用（不含停牌期填充）
    delisting_list=False,
    list_date=False,
    trading_calendar=False,
    half_day_marker=False,
    fundamentals=False,
    intraday=False,
    rate_limit_per_min=120,  # 与 akshare 同级（同为腾讯 HTTP 端点）
    requires_subprocess_isolation=False,
    protocol="HTTP",
    honors_proxy_env=True,
    reachable=None,  # 部署机探活后回填（qv2 ops probe-sources）
    forbidden_endpoints=FORBIDDEN_ENDPOINTS,
)
