"""腾讯直连兜底适配器（§4.2 priority=2 / T02.3）。

## 职责边界

- **只做交叉验证**：主备源都拿不到的退市股行情，用腾讯 kline 端点做
  "不复权价"层面的交叉验证（M-2：只比 raw，绝不比复权价）。
  本源**不进回测主链路** —— 腾讯通道不含停牌期填充，也不含成交额。
- **协议**：`web.ifzq.gtimg.cn` 的 JSON kline 接口（HTTP，认代理环境变量），
  行结构 `[date, open, close, high, low, volume]`（注意列序：close 在 high 前），
  最多一次返回 `max_count` 根（默认 640，足够覆盖任何单次增量窗口）。

## 数据缺口（如实声明，禁止静默补齐）

- 无复权因子 → `adj_factor=1` 占位 + `source="tencent_legacy"`；
- 无成交额列 → `amount=0` 占位（本源仅用于价格交叉验证，金额不被消费；
  若未来要入库，必须先补一个能给 amount 的通道，而不是拿 close×volume 编造）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from quant_v2.adapters.market_data.capabilities import (
    TENCENT_CAPABILITIES,
    SourceHealth,
    utc_now,
)
from quant_v2.domain.errors import SourceUnavailableError
from quant_v2.domain.models.bar import Bar

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from quant_v2.domain.ports.market_data_port import BarRequest

__all__ = [
    "TencentAdapter",
    "from_tencent_symbol",
    "to_tencent_symbol",
]

# 腾讯 kline JSON 端点（普通 HTTP，实测可达；非东财 push2 系，不在禁用清单）
KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

# 抓取函数：(tencent_symbol, start, end, max_count) -> 解析后的 JSON dict
KlineFetcher = Callable[[str, date, date, int], Mapping[str, Any]]

_SUFFIX_TO_PREFIX = {"SH": "sh", "SZ": "sz"}

# 腾讯代码形如 sh600000：2 位交易所前缀 + 6 位证券代码
_TX_SYMBOL_LEN = 8

# kline 行至少 6 列：[date, open, close, high, low, volume]（★ close 在第 2 列）
_MIN_KLINE_COLUMNS = 6


def to_tencent_symbol(symbol: str) -> str:
    """归一化代码 → 腾讯代码：`600000.SH` → `sh600000`。"""
    code, _, suffix = symbol.partition(".")
    prefix = _SUFFIX_TO_PREFIX.get(suffix.upper())
    if prefix is None or not code:
        raise ValueError(f"无法把 {symbol!r} 转成腾讯代码：只支持 .SH / .SZ")
    return f"{prefix}{code}"


def from_tencent_symbol(tx: str) -> str:
    """腾讯代码 → 归一化代码：`sh600000` → `600000.SH`。"""
    if len(tx) != _TX_SYMBOL_LEN or tx[:2] not in ("sh", "sz"):
        raise ValueError(f"无法把 {tx!r} 解析为腾讯代码：期望 shXXXXXX / szXXXXXX")
    return f"{tx[2:]}.{tx[:2].upper()}"


def _default_fetcher(symbol: str, start: date, end: date, max_count: int) -> Mapping[str, Any]:
    """默认抓取器：requests GET（带超时；无 requests 时启动即炸，不静默）。"""
    import requests  # noqa: PLC0415 -- ARCH011：adapters/ 内允许

    param = f"{symbol},day,{start.isoformat()},{end.isoformat()},{max_count},"
    response = requests.get(
        KLINE_URL,
        params={"param": param},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _to_decimal(value: Any, *, context: str) -> Decimal:
    """腾讯 JSON 标量（str）→ Decimal；空/非法值抛错而非兜底。"""
    text = str(value if value is not None else "").strip()
    if not text:
        raise ValueError(f"{context} 为空值：腾讯通道返回了不完整行，禁止用默认价兜底")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{context} = {value!r} 不是合法数值") from exc


class TencentAdapter:
    """腾讯直连兜底源（行情子集：healthcheck / fetch_bars）。"""

    source_id = "tencent"
    supported_markets = frozenset({"cn_a"})
    capabilities = TENCENT_CAPABILITIES

    def __init__(
        self,
        *,
        fetcher: KlineFetcher | None = None,
        as_of: datetime | None = None,
        max_count: int = 640,
    ) -> None:
        self._fetcher = fetcher if fetcher is not None else _default_fetcher
        self._as_of = as_of
        self._max_count = max_count

    # -- 健康检查 ---------------------------------------------

    def healthcheck(self) -> SourceHealth:
        """一次最小语义请求（浦发银行近 5 个交易日）探活。失败不抛（D-10）。"""
        started = utc_now()
        try:
            rows = self._fetch_rows(
                to_tencent_symbol("600000.SH"),
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
                detail="最小语义请求返回 0 行：腾讯通道响应异常",
            )
        return SourceHealth(source_id=self.source_id, reachable=True, checked_at=started)

    # -- 行情 -------------------------------------------------

    def fetch_bars(self, req: BarRequest) -> Sequence[Bar]:
        """拉日线（腾讯原始价；无因子、无成交额，见模块 docstring 的缺口声明）。"""
        if req.market != "cn_a":
            raise ValueError(f"腾讯兜底源只服务 cn_a，收到 {req.market!r}")
        as_of = self._as_of if self._as_of is not None else datetime.now(UTC)

        bars: list[Bar] = []
        for symbol in req.symbols:
            rows = self._fetch_rows(to_tencent_symbol(symbol), req.start, req.end)
            bars.extend(_to_bars(rows, symbol=symbol, market=req.market, as_of=as_of))
        return bars

    def _fetch_rows(self, tx_symbol: str, start: date, end: date) -> Sequence[Sequence[str]]:
        """单标的抓取 + JSON 解包；异常归一化为 SourceUnavailableError。

        返回 kline 行列表（每行 `[date, open, close, high, low, volume]`）。
        窗口超过 max_count 根时分段抓（腾讯接口按 count 截尾，静默丢头部行 ——
        必须显式分段，否则拿到的"开头几行"其实是窗口中段，是脏数据不是缺口）。
        """
        collected: list[Sequence[str]] = []
        window_start = start
        while window_start <= end:
            payload = self._fetch_one(tx_symbol, window_start, end)
            rows = _extract_kline_rows(payload, tx_symbol=tx_symbol)
            collected.extend(rows)
            if len(rows) < self._max_count:
                break  # 窗口内全部拿到，无需分段
            # 拿满了 max_count 根：窗口还有剩余，从最后一行的次日继续
            last_day = date.fromisoformat(str(rows[-1][0]))
            window_start = last_day + timedelta(days=1)
        return collected

    def _fetch_one(self, tx_symbol: str, start: date, end: date) -> Mapping[str, Any]:
        try:
            return self._fetcher(tx_symbol, start, end, self._max_count)
        except SourceUnavailableError:
            raise
        except Exception as exc:
            raise SourceUnavailableError(
                f"腾讯通道查询失败（{tx_symbol}）: {type(exc).__name__}: {exc}"
            ) from exc


def _extract_kline_rows(payload: Mapping[str, Any], *, tx_symbol: str) -> Sequence[Sequence[str]]:
    """从腾讯 JSON 里取日线行（data.<symbol>.day；容错 qfqday 键名变体）。"""
    data_node = payload.get("data")
    if not isinstance(data_node, Mapping):
        raise SourceUnavailableError(f"腾讯通道响应缺少 data 节点（{tx_symbol}）")
    code_node = data_node.get(tx_symbol)
    if not isinstance(code_node, Mapping):
        raise SourceUnavailableError(f"腾讯通道响应缺少 {tx_symbol} 节点")
    rows = code_node.get("day")
    if rows is None:
        rows = code_node.get("qfqday")  # 部分行情变体键名；仍是原始请求口径
    if not isinstance(rows, list):
        raise SourceUnavailableError(f"腾讯通道响应缺少 day 行数组（{tx_symbol}）")
    return [list(row) for row in rows]


def _to_bars(
    rows: Sequence[Sequence[str]],
    *,
    symbol: str,
    market: str,
    as_of: datetime,
) -> list[Bar]:
    """腾讯 kline 行 → 领域 Bar。

    ★ 列序 `[date, open, close, high, low, volume]`（close 在 high 前，
      腾讯接口的历史约定，与常见 OHLC 顺序不同 —— 这里显式按下标取，绝不猜）。
    """
    bars: list[Bar] = []
    for row in rows:
        if len(row) < _MIN_KLINE_COLUMNS:
            raise ValueError(f"{symbol} 的腾讯行只有 {len(row)} 列（期望 ≥6），禁止猜测缺失列")
        day = date.fromisoformat(str(row[0]).strip()[:10])
        bars.append(
            Bar(
                symbol=symbol,
                market=market,
                date=day,
                open=_to_decimal(row[1], context=f"{symbol}.open@{day}"),
                close=_to_decimal(row[2], context=f"{symbol}.close@{day}"),
                high=_to_decimal(row[3], context=f"{symbol}.high@{day}"),
                low=_to_decimal(row[4], context=f"{symbol}.low@{day}"),
                volume=_to_decimal(row[5] or 0, context=f"{symbol}.volume@{day}"),
                amount=Decimal("0"),  # ★ 腾讯无成交额列：0 占位（仅交叉验证用，见 docstring）
                adj_factor=Decimal("1"),  # ★ 占位：腾讯通道无因子
                currency="CNY",
                source="tencent_legacy",  # ★ legacy 标记（端口契约：缺因子必须可见）
                as_of=as_of,
                is_trading_day=True,  # 腾讯 kline 只在交易日给行
                is_suspended=False,
            )
        )
    return bars
