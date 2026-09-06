"""baostock PIT 股票池提供者（T02.5 / D-05 / M-12 / M-15 / M-19 / M-20）。

## 纯日快照路径（M-15 实测定稿）

`bs.query_all_stock(day=as_of)` 能**直接取历史某日在市快照，且含后来的
退市股**（最早 1990-12-19）。`ipoDate+outDate` 区间推算不进生产代码 ——
避免双份实现与一致性问题（区间推算只作建池后的一次性交叉抽检）。

## 三条硬约束（实测驱动，违反任何一条都会产生脏数据）

1. **M-19**：非交易日该接口返回 **0 rows**（1991-06-01 周六实测）。
   0 rows ≠ 空池子 —— 查源前必须先过交易日历；"交易日 + 0 rows"
   → P0 门禁（`DataQualityGateError`），拒绝写入。
2. **M-20**：返回字段只有 `code / tradeStatus / code_name`。
   `tradeStatus` 是**停牌**标记（不是 ST）；`is_st` 从 `code_name`
   正则解析并标 `is_st_source='NAME_PARSE'`；快照**含指数**
   （`sh.00xxxx` / `sz.39xxxx` 前缀），必须按前缀过滤。
3. **M-12**：退市标的池上界 = `outDate + 1`（本表不存 outDate，
   缓冲由查询侧 `delist_buffer_days` 处理，见架构文档 §5.6）。

## 依赖方向

本模块在 `adapters/`，通过 `SubprocessWorker` 间接使用 baostock
（ARCH014：本文件**不** import baostock，物理隔离由 worker 子进程保证）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from quant_v2.adapters.market_data.subprocess_worker import (
    SubprocessWorker,
    WorkerCall,
    WorkerResult,
)
from quant_v2.adapters.persistence.repositories import PitRow
from quant_v2.domain.errors import (
    DataQualityGateError,
    NotTradingDayError,
    SourceUnavailableError,
)
from quant_v2.domain.models.bar import InstrumentType
from quant_v2.domain.ports.pipeline_port import (
    SurvivorshipRisk,
    SymbolSnapshot,
)
from quant_v2.domain.services.pit_universe import (
    PIT_EARLIEST_DATE,
    parse_is_st,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期需要
    from quant_v2.adapters.persistence.repositories import (
        SqlitePitUniverseRepository,
    )
    from quant_v2.domain.ports.market_data_port import TradingCalendar

__all__ = [
    "AllStockFetcher",
    "BaostockPitUniverseProvider",
    "default_all_stock_fetcher",
]

# 抓取函数：day → 原始行（code / tradeStatus / code_name）
AllStockFetcher = Callable[[date], Sequence[Mapping[str, Any]]]

# M-20：快照含指数 —— sh.00xxxx（上证指数族）/ sz.39xxxx（深证指数族）。
# ★ sz.00xxxx 是个股（如 sz.000001 平安银行），不能误伤；
#   个股前缀：sh.60 / sh.68 / sz.00 / sz.30。
_INDEX_CODE_PREFIXES = ("sh.00", "sz.39")

# baostock tradeStatus 的合法取值（实测：'1'=交易 '0'=停牌）
_TRADING_STATUS_VALUES = frozenset({"1", 1})
_SUSPENDED_STATUS_VALUES = frozenset({"0", 0})


def default_all_stock_fetcher(
    worker: SubprocessWorker | None = None,
) -> AllStockFetcher:
    """生产抓取器：经 `SubprocessWorker` 走隔离子进程调 `query_all_stock`。

    ★ 子进程复用：传入共享 worker（建池作业一夫一妻，1400 次调用共享会话
      重建/限流/checkpoint 逻辑）；不传则每次调用起一个临时 worker。
    """

    def fetch(day: date) -> Sequence[Mapping[str, Any]]:
        own_worker = worker is None
        w = worker if worker is not None else SubprocessWorker()
        try:
            result: WorkerResult = w.run(WorkerCall.all_stock(f"all_stock-{day.isoformat()}", day))
        finally:
            if own_worker:
                w.close()
        if not result.ok:
            raise SourceUnavailableError(f"baostock query_all_stock({day}) 失败: {result.error}")
        rows = result.payload
        if not isinstance(rows, list):
            raise SourceUnavailableError(
                f"baostock query_all_stock({day}) 返回类型异常: {type(rows).__name__}"
            )
        return rows

    return fetch


@dataclass(frozen=True)
class _RawRow:
    """规范化后的原始行（baostock code + 解析好的字段）。"""

    symbol: str
    code_name: str
    is_st: bool
    trade_status: str


class BaostockPitUniverseProvider:
    """A 股 PIT 池提供者：实现 `UniverseProvider` 端口（Tier A，风险 = NONE）。

    读取路径（`symbols()`）：

    1. 命中 `pit_universe` 表 → 直接返回（已落库的不问源）；
    2. 未命中 → M-15/ M-19 前置校验 → `query_all_stock(day=)` →
       M-20 过滤/解析 → M-19 空池门禁 → 落库并返回。
    """

    supported_markets = frozenset({"cn_a"})

    def __init__(
        self,
        *,
        repo: SqlitePitUniverseRepository,
        calendar: TradingCalendar,
        fetcher: AllStockFetcher,
        market: str = "cn_a",
    ) -> None:
        if market not in self.supported_markets:
            raise ValueError(
                f"BaostockPitUniverseProvider 只支持 {sorted(self.supported_markets)}，"
                f"收到 {market!r}"
            )
        self._repo = repo
        self._calendar = calendar
        self._fetcher = fetcher
        self._market = market

    # -- UniverseProvider 协议 --------------------------------

    @property
    def survivorship_risk(self) -> SurvivorshipRisk:
        """真实 PIT 切片（Tier A）：含退市股，可直接用于回测。"""
        return SurvivorshipRisk.NONE

    @property
    def pool_build_date(self) -> date:
        """池子可回测的最早日期 = 数据源快照最早可用日（M-15）。

        快照缓存未命中时 provider 会**按需**向源查历史快照，
        因此理论上界是上交所开市首日，而不是"已落库的最早一天"。
        """
        return PIT_EARLIEST_DATE

    def symbols(self, *, as_of: date, market: str) -> Sequence[SymbolSnapshot]:
        """`as_of` 当天在市的标的（PIT 语义：含当日尚未退市的退市股）。"""
        if market != self._market:
            raise ValueError(f"未知市场 {market!r}（本 provider 只服务 {self._market}）")

        cached = self._repo.load_snapshot(as_of)
        if cached:
            return [self._to_snapshot(row) for row in cached]

        self._require_fetchable(as_of)
        raw_rows = self._fetcher(as_of)
        rows = self._normalize(raw_rows, as_of)
        if not raw_rows:
            raise DataQualityGateError(
                f"PIT 快照门禁（M-19）：{as_of} 是交易日但 query_all_stock 返回 0 行 —— "
                "拒绝写入（0 rows ≠ 空池子，这是静默失败陷阱，已按 P0 处理）"
            )
        if not rows:
            raise DataQualityGateError(
                f"PIT 快照门禁（M-20）：{as_of} 快照 {len(raw_rows)} 行全部被指数过滤规则"
                f"（{_INDEX_CODE_PREFIXES}）剔除 —— 过滤规则与源格式疑似不符，拒绝写入"
            )
        self._repo.save_snapshot(rows)
        return [self._to_snapshot(row) for row in rows]

    # -- 内部 -------------------------------------------------

    def _require_fetchable(self, as_of: date) -> None:
        """M-15 / M-19 前置校验：开市日之内 + 必须是交易日。"""
        if as_of < PIT_EARLIEST_DATE:
            raise NotTradingDayError(
                f"as_of={as_of} 早于 A 股快照最早可用日 {PIT_EARLIEST_DATE}"
                "（M-15：上交所开市首日），query_all_stock 在此之前无数据"
            )
        if not self._calendar.is_trading_day(self._market, as_of):
            raise NotTradingDayError(
                f"as_of={as_of} 不是 {self._market} 的交易日（M-19）："
                "query_all_stock 在非交易日返回 0 rows，0 rows ≠ 空池子 —— 拒绝查询"
            )

    def _normalize(self, raw_rows: Sequence[Mapping[str, Any]], as_of: date) -> list[PitRow]:
        """M-20 字段处理：过滤指数 + ST 正则 + 停牌映射 → PitRow。"""
        normalized: list[PitRow] = []
        for raw in raw_rows:
            code = str(raw.get("code", ""))
            if not code or code.startswith(_INDEX_CODE_PREFIXES):
                continue
            name = str(raw.get("code_name", ""))
            if not name:
                raise DataQualityGateError(
                    f"PIT 快照门禁（M-20）：{as_of} 的 {code} 缺 code_name"
                    "（实测 100% 非空，缺失说明源格式变了）"
                )
            normalized.append(
                PitRow(
                    as_of=as_of,
                    symbol=self._to_symbol(code),
                    code_name=name,
                    is_st=parse_is_st(name),
                    is_st_source="NAME_PARSE",
                    trade_status=self._to_trade_status(raw.get("tradeStatus"), code, as_of),
                )
            )
        return normalized

    def _to_symbol(self, code: str) -> str:
        """baostock 代码 → 归一化代码：`sh.600000` → `600000.SH`。"""
        prefix, _, code_part = code.partition(".")
        suffix = {"sh": "SH", "sz": "SZ"}.get(prefix.lower())
        if suffix is None or not code_part:
            raise DataQualityGateError(
                f"PIT 快照门禁：无法把 {code!r} 解析为沪深个股代码（只支持 sh. / sz. 前缀）"
            )
        return f"{code_part}.{suffix}"

    def _to_trade_status(self, value: Any, code: str, as_of: date) -> str:
        """tradeStatus → 'TRADING' | 'SUSPENDED'（★ 停牌标记，不是 ST）。"""
        if value in _TRADING_STATUS_VALUES:
            return "TRADING"
        if value in _SUSPENDED_STATUS_VALUES:
            return "SUSPENDED"
        raise DataQualityGateError(
            f"PIT 快照门禁（M-20）：{as_of} 的 {code} tradeStatus={value!r}"
            " 不是 '0'/'1'（实测只有两值，出现第三种说明源格式变了，禁止猜测）"
        )

    def _to_snapshot(self, row: PitRow) -> SymbolSnapshot:
        """PitRow → 端口契约 SymbolSnapshot。"""
        return SymbolSnapshot(
            symbol=row.symbol,
            market=self._market,
            name=row.code_name,
            instrument_type=InstrumentType.EQUITY,
            is_st=row.is_st,
        )
