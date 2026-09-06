"""baostock A 股主源适配器（§5.2 / §5.11 / M-3 / M-5）。

## 职责边界

- 本类是**主进程**里的适配器：只做符号归一化、因子合并、Bar 组装；
  **永不 import baostock**（ARCH014）—— 所有网络查询经 `SubprocessWorker`
  转发给隔离子进程。
- `Bar.adj_factor` 语义 = **累积后复权因子**（`raw_close × adj_factor == hfq_close`，
  见 `domain.services.adjustment`）。

## 因子合并规则（M-5）

baostock 的 `query_adjust_factor` 给的是**事件表**（dividOperateDate + backAdjustFactor）。
某交易日 D 的有效因子 = dividOperateDate ≤ D 的最近一条 backAdjustFactor；
D 早于首个除权日 → 因子为 1（上市后从未除权 = 原始价即后复权基准）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from quant_v2.adapters.market_data.capabilities import (
    BAOSTOCK_CAPABILITIES,
    SourceHealth,
    utc_now,
)
from quant_v2.adapters.market_data.subprocess_worker import (
    SubprocessWorker,
    WorkerCall,
    WorkerResult,
)
from quant_v2.domain.errors import SourceUnavailableError
from quant_v2.domain.models.bar import Bar

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from quant_v2.domain.ports.market_data_port import BarRequest

__all__ = [
    "BaostockCnAdapter",
    "from_baostock_code",
    "merge_adjust_factors",
    "to_baostock_code",
]

# 归一化后缀 ↔ baostock 前缀（baostock 只覆盖沪深两市，无北交所）
_SUFFIX_TO_PREFIX = {"SH": "sh", "SZ": "sz"}
_PREFIX_TO_SUFFIX = {"sh": "SH", "sz": "SZ"}


def to_baostock_code(symbol: str) -> str:
    """归一化代码 → baostock 代码：`600000.SH` → `sh.600000`。"""
    code, _, suffix = symbol.partition(".")
    prefix = _SUFFIX_TO_PREFIX.get(suffix.upper())
    if prefix is None or not code:
        raise ValueError(f"无法把 {symbol!r} 转成 baostock 代码：只支持 .SH / .SZ")
    return f"{prefix}.{code}"


def from_baostock_code(code: str) -> str:
    """baostock 代码 → 归一化代码：`sh.600000` → `600000.SH`。"""
    prefix, _, code_part = code.partition(".")
    suffix = _PREFIX_TO_SUFFIX.get(prefix.lower())
    if suffix is None or not code_part:
        raise ValueError(f"无法把 {code!r} 转成归一化代码：只支持 sh. / sz. 前缀")
    return f"{code_part}.{suffix}"


def merge_adjust_factors(
    factor_rows: Sequence[dict[str, str]],
    day: date,
) -> Decimal:
    """取交易日 `day` 的有效后复权因子（dividOperateDate ≤ day 的最近一条）。

    无任何 ≤ day 的除权事件 → Decimal("1")（**不是 0**：因子语义是乘子，
    1 = 从未除权，`raw × 1 = hfq` 恒成立）。
    输入先按 dividOperateDate 排序 —— 事件表顺序是源的实现细节，不是契约。
    """
    ordered = sorted(factor_rows, key=lambda row: row["dividOperateDate"])
    effective = Decimal("1")
    for row in ordered:
        if date.fromisoformat(row["dividOperateDate"]) <= day:
            effective = _to_decimal(row["backAdjustFactor"], context=f"backAdjustFactor@{day}")
    return effective


class BaostockCnAdapter:
    """baostock A 股主源。

    实现了 `MarketDataAdapter` 端口的**行情子集**（healthcheck / fetch_bars）；
    `list_instruments`（PIT 池）在 T02.5 落地、`fetch_trading_calendar` 由
    `adapters/clock/` 的日历适配器承担（数据来自 profile YAML 而非在线源）。
    因此本类**不冒充**完整 Protocol 实现 —— 没实现的就是没实现。
    """

    source_id = "baostock"
    supported_markets = frozenset({"cn_a"})
    capabilities = BAOSTOCK_CAPABILITIES

    def __init__(
        self,
        *,
        worker: SubprocessWorker | None = None,
        as_of: datetime | None = None,
    ) -> None:
        self._worker = worker if worker is not None else SubprocessWorker()
        self._as_of = as_of

    # -- 健康检查 ---------------------------------------------

    def healthcheck(self) -> SourceHealth:
        """一次最小语义请求（单标的单日因子）探活。

        ★ 失败不抛 —— 返回 `reachable=False` 的 SourceHealth，
          降级与告警决策留给编排层（D-10：失败必须告警，但由上层统一发）。
        """
        started = utc_now()
        try:
            result = self._worker.run(
                WorkerCall(
                    call_id=f"healthcheck-{started.isoformat()}",
                    kind="factors",
                    symbol="sh.600000",
                    start=date(2020, 1, 2),
                    end=date(2020, 1, 3),
                )
            )
        except SourceUnavailableError as exc:
            return SourceHealth(
                source_id=self.source_id,
                reachable=False,
                checked_at=started,
                detail=str(exc),
            )
        if not result.ok:
            return SourceHealth(
                source_id=self.source_id,
                reachable=False,
                checked_at=started,
                detail=result.error or "unknown",
            )
        return SourceHealth(
            source_id=self.source_id,
            reachable=True,
            checked_at=started,
            latency_s=result.elapsed_s,
        )

    # -- 行情 -------------------------------------------------

    def fetch_bars(self, req: BarRequest) -> Sequence[Bar]:
        """拉日线（RAW 价格 + 合并后的累积后复权因子）。

        每只标的两个 call（bars + factors），一次 `run_batch` 执行；
        checkpoint key 由请求参数派生，进程崩溃后重跑自动续传。
        """
        if req.market != "cn_a":
            raise ValueError(f"baostock 适配器只服务 cn_a，收到 {req.market!r}")
        as_of = self._as_of if self._as_of is not None else datetime.now(UTC)

        calls: list[WorkerCall] = []
        for symbol in req.symbols:
            bs_code = to_baostock_code(symbol)
            calls.append(
                WorkerCall(
                    call_id=f"bars:{symbol}:{req.start}:{req.end}",
                    kind="bars",
                    symbol=bs_code,
                    start=req.start,
                    end=req.end,
                )
            )
            calls.append(
                WorkerCall(
                    call_id=f"factors:{symbol}:{req.start}:{req.end}",
                    kind="factors",
                    symbol=bs_code,
                    start=req.start,
                    end=req.end,
                )
            )

        # ★ checkpoint key 必须跨进程稳定（断点续跑的前提）：
        #   内建 hash() 每次进程启动都变，必须用内容摘要。
        symbols_digest = hashlib.sha256("\n".join(sorted(req.symbols)).encode()).hexdigest()[:12]
        checkpoint_key = (
            f"baostock_bars_{req.start.isoformat()}_{req.end.isoformat()}_{symbols_digest}"
        )
        results = self._worker.run_batch(calls, checkpoint_key=checkpoint_key)

        bars: list[Bar] = []
        for symbol in req.symbols:
            bar_rows = _require_ok(results, f"bars:{symbol}:{req.start}:{req.end}", symbol)
            factor_rows = _require_ok(results, f"factors:{symbol}:{req.start}:{req.end}", symbol)
            bars.extend(
                _to_bars(
                    rows=bar_rows,
                    factor_rows=factor_rows,
                    symbol=symbol,
                    market=req.market,
                    as_of=as_of,
                )
            )
        return bars


# ============================================================
# 行组装（纯函数，独立可测）
# ============================================================


def _require_ok(
    results: dict[str, WorkerResult],
    call_id: str,
    symbol: str,
) -> list[dict[str, str]]:
    """取该 call 的成功 payload；缺失或失败即抛（禁止静默少一只股票）。"""
    result = results.get(call_id)
    if result is None:
        raise SourceUnavailableError(f"{symbol} 的查询结果缺失（call_id={call_id}）")
    if not result.ok:
        raise SourceUnavailableError(f"{symbol} 查询失败: {result.error}（call_id={call_id}）")
    payload = result.payload
    if not isinstance(payload, list):
        raise SourceUnavailableError(f"{symbol} 查询返回形态异常: {type(payload).__name__}")
    return [dict(row) for row in payload]


def _to_decimal(raw: str, *, context: str) -> Decimal:
    """字符串 → Decimal；空/非法值**抛错而非兜底**（errors.py 的设计原则）。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError(f"{context} 为空值：baostock 返回了不完整行，禁止用默认价兜底")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{context} = {raw!r} 不是合法数值") from exc


def _price_from_row(
    row: Mapping[str, str],
    field: str,
    *,
    symbol: str,
    day: date,
    is_suspended: bool,
) -> Decimal:
    """价格字段：正常日必须有值；停牌日 baostock 可能给空 → 用前收。"""
    raw = row.get(field, "")
    if (raw or "").strip():
        return _to_decimal(raw, context=f"{symbol}.{field}@{day}")
    if is_suspended and (row.get("preclose") or "").strip():
        # 停牌日价格平铺前收（Bar 校验对停牌行不生效，此值仅占位）
        return _to_decimal(row["preclose"], context=f"{symbol}.preclose@{day}")
    raise ValueError(
        f"{symbol} {day} 的 {field} 为空且无 preclose 可用 —— "
        "禁止编造价格（errors.py: 该抛的地方绝不兜底）"
    )


def _to_bars(
    *,
    rows: Sequence[dict[str, str]],
    factor_rows: Sequence[dict[str, str]],
    symbol: str,
    market: str,
    as_of: datetime,
) -> list[Bar]:
    """baostock 原始行 + 因子事件表 → 领域 Bar 列表。"""
    bars: list[Bar] = []
    for row in rows:
        day = date.fromisoformat(row["date"])
        is_suspended = row.get("tradestatus", "1") == "0"
        adj_factor = merge_adjust_factors(factor_rows, day)
        prices = {
            field: _price_from_row(row, field, symbol=symbol, day=day, is_suspended=is_suspended)
            for field in ("open", "high", "low", "close")
        }
        volume_raw = (row.get("volume") or "0").strip() or "0"
        amount_raw = (row.get("amount") or "0").strip() or "0"
        bars.append(
            Bar(
                symbol=symbol,
                market=market,
                date=day,
                open=prices["open"],
                high=prices["high"],
                low=prices["low"],
                close=prices["close"],
                volume=Decimal(volume_raw),
                amount=Decimal(amount_raw),
                adj_factor=adj_factor,
                currency="CNY",
                source="baostock",
                as_of=as_of,
                is_trading_day=True,  # baostock 只在交易日给行
                is_suspended=is_suspended,
            )
        )
    return bars
