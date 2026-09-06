"""akshare A 股备源适配器（§4.2 主备分工 / M-6 / M-8）。

## 职责边界

- **快活专用**：每日增量更新（155 req/min 实测，按 120 排期）。
  历史全量回补、复权因子、PIT 快照、退市股行情仍走 baostock 主源。
- **通道纪律（M-6）**：只用新浪通道 `stock_zh_a_daily`；
  东财 push2 系通道（akshare 里的 `*_em` 家族）在本网络 TCP 建连失败，
  由 `capabilities.FORBIDDEN_ENDPOINTS` + ARCH015 双重禁用，本文件不出现其端点字面量。
- **无因子声明（M-8）**：新浪通道只给价格列，没有复权因子。
  `Bar.adj_factor` 只能置 `1`（占位），`Bar.source` 标记为
  `akshare_legacy` 提醒下游"该序列跨除权日不可直接比价"；
  告警由编排层（ResilientSource）统一发，本类不越权。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from quant_v2.adapters.market_data.capabilities import (
    AKSHARE_CAPABILITIES,
    SourceHealth,
    utc_now,
)
from quant_v2.domain.errors import SourceUnavailableError
from quant_v2.domain.models.bar import Bar

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from quant_v2.domain.ports.market_data_port import BarRequest

__all__ = [
    "AkshareCnAdapter",
    "from_sina_symbol",
    "to_sina_symbol",
]

# 新浪通道单标的日线抓取函数： (sina_symbol, start, end) -> 原始行列表
SinaDailyFetcher = Callable[[str, date, date], Sequence[Mapping[str, Any]]]

_SUFFIX_TO_PREFIX = {"SH": "sh", "SZ": "sz"}

# 新浪代码形如 sh600000：2 位交易所前缀 + 6 位证券代码
_SINA_SYMBOL_LEN = 8


def to_sina_symbol(symbol: str) -> str:
    """归一化代码 → 新浪代码：`600000.SH` → `sh600000`。"""
    code, _, suffix = symbol.partition(".")
    prefix = _SUFFIX_TO_PREFIX.get(suffix.upper())
    if prefix is None or not code:
        raise ValueError(f"无法把 {symbol!r} 转成新浪代码：只支持 .SH / .SZ")
    return f"{prefix}{code}"


def from_sina_symbol(sina: str) -> str:
    """新浪代码 → 归一化代码：`sh600000` → `600000.SH`。"""
    if len(sina) != _SINA_SYMBOL_LEN or sina[:2] not in ("sh", "sz"):
        raise ValueError(f"无法把 {sina!r} 解析为新浪代码：期望 shXXXXXX / szXXXXXX")
    return f"{sina[2:]}.{sina[:2].upper()}"


def _default_fetcher(symbol: str, start: date, end: date) -> Sequence[Mapping[str, Any]]:
    """默认抓取器：惰性 import akshare，走新浪通道（adjust="" = 未复权原始价）。

    ★ 惰性 import 而非模块级：akshare 导入开销大（含 pandas 全家桶），
      只在真正发起查询时才加载；ARCH011 允许 adapters/ 内引用外部 SDK。
    """
    import akshare as ak  # noqa: PLC0415 -- ARCH011：adapters/ 内允许；惰性导入避免冷启动开销

    frame = ak.stock_zh_a_daily(
        symbol=symbol,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="",  # ★ 原始价：因子本来就没有，绝不用 qfq/hfq 价冒充 raw（M-2 教训）
    )
    return frame.to_dict("records")


def _to_decimal(value: Any, *, context: str) -> Decimal:
    """任意标量（str/float/None）→ Decimal；空/非法值抛错而非兜底。"""
    if value is None:
        raise ValueError(f"{context} 为 None：新浪通道返回了不完整行，禁止用默认价兜底")
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none"):
        raise ValueError(f"{context} 为空值（{value!r}），禁止用默认价兜底")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{context} = {value!r} 不是合法数值") from exc


class AkshareCnAdapter:
    """akshare A 股备源（行情子集：healthcheck / fetch_bars）。

    与 `BaostockCnAdapter` 一样，不冒充完整 `MarketDataAdapter`：
    `list_instruments`（PIT 池）在 T02.5 落地，日历由 `adapters/clock/` 承担。
    """

    source_id = "akshare"
    supported_markets = frozenset({"cn_a"})
    capabilities = AKSHARE_CAPABILITIES

    def __init__(
        self,
        *,
        fetcher: SinaDailyFetcher | None = None,
        as_of: datetime | None = None,
        request_timeout_s: float = 15.0,
    ) -> None:
        self._fetcher = fetcher if fetcher is not None else _default_fetcher
        self._as_of = as_of
        self._request_timeout_s = request_timeout_s

    # -- 健康检查 ---------------------------------------------

    def healthcheck(self) -> SourceHealth:
        """一次最小语义请求（浦发银行近 5 个自然日）探活。

        ★ 失败不抛 —— 返回 `reachable=False`，降级与告警决策留给编排层（D-10）。
        """
        started = utc_now()
        try:
            rows = self._fetch_one(
                to_sina_symbol("600000.SH"),
                date(2020, 1, 2),
                date(2020, 1, 10),
            )
        except Exception as exc:
            return SourceHealth(
                source_id=self.source_id,
                reachable=False,
                checked_at=started,
                detail=f"{type(exc).__name__}: {exc}",
            )
        if not rows:
            return SourceHealth(
                source_id=self.source_id,
                reachable=False,
                checked_at=started,
                detail="最小语义请求返回 0 行：新浪通道响应异常",
            )
        return SourceHealth(source_id=self.source_id, reachable=True, checked_at=started)

    # -- 行情 -------------------------------------------------

    def fetch_bars(self, req: BarRequest) -> Sequence[Bar]:
        """拉日线（新浪通道原始价；adj_factor 恒 1 占位，source=akshare_legacy）。"""
        if req.market != "cn_a":
            raise ValueError(f"akshare 适配器只服务 cn_a，收到 {req.market!r}")
        as_of = self._as_of if self._as_of is not None else datetime.now(UTC)

        bars: list[Bar] = []
        for index, symbol in enumerate(req.symbols):
            if index > 0:
                time.sleep(self._pacing_s())
            rows = self._fetch_one(to_sina_symbol(symbol), req.start, req.end)
            bars.extend(_to_bars(rows, symbol=symbol, market=req.market, as_of=as_of))
        return bars

    def _fetch_one(self, sina_symbol: str, start: date, end: date) -> Sequence[Mapping[str, Any]]:
        """单标的抓取；异常统一包成 SourceUnavailableError（编排层只认这一种）。"""
        try:
            return self._fetcher(sina_symbol, start, end)
        except SourceUnavailableError:
            raise
        except Exception as exc:
            raise SourceUnavailableError(
                f"akshare 新浪通道查询失败（{sina_symbol}）: {type(exc).__name__}: {exc}"
            ) from exc

    def _pacing_s(self) -> float:
        """限流间隔 = 60 / rate_limit_per_min（M-17）。"""
        rate = self.capabilities.rate_limit_per_min
        if not rate:
            return 0.0
        return 60.0 / float(rate)


# ============================================================
# 行组装（纯函数，独立可测）
# ============================================================


def _to_bars(
    rows: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    market: str,
    as_of: datetime,
) -> list[Bar]:
    """新浪通道原始行 → 领域 Bar。

    ★ 新浪通道只在交易日给行（停牌日直接缺席，无 preclose 平铺），
      因此 `is_suspended` 恒 False、`is_trading_day` 恒 True。
    ★ `adj_factor=1` 是占位而非事实 —— 所以 `source` 必须带 `_legacy`
      后缀，下游看见它就知道"跨除权日不可直接比价"。
    """
    bars: list[Bar] = []
    for row in rows:
        day = _row_date(row, symbol=symbol)
        bars.append(
            Bar(
                symbol=symbol,
                market=market,
                date=day,
                open=_to_decimal(row.get("open"), context=f"{symbol}.open@{day}"),
                high=_to_decimal(row.get("high"), context=f"{symbol}.high@{day}"),
                low=_to_decimal(row.get("low"), context=f"{symbol}.low@{day}"),
                close=_to_decimal(row.get("close"), context=f"{symbol}.close@{day}"),
                volume=_to_decimal(row.get("volume") or 0, context=f"{symbol}.volume@{day}"),
                amount=_to_decimal(row.get("amount") or 0, context=f"{symbol}.amount@{day}"),
                adj_factor=Decimal("1"),  # ★ 占位：新浪通道无因子（见模块 docstring）
                currency="CNY",
                source="akshare_legacy",  # ★ legacy 标记（端口契约：缺因子必须可见）
                as_of=as_of,
                is_trading_day=True,
                is_suspended=False,
            )
        )
    return bars


def _row_date(row: Mapping[str, Any], *, symbol: str) -> date:
    """行日期解析（新浪通道给 date 列，str 或 Timestamp）。"""
    raw = row.get("date")
    if raw is None:
        raise ValueError(f"{symbol} 的行缺少 date 列，禁止猜测日期")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{symbol} 的 date = {raw!r} 不是合法日期") from exc
