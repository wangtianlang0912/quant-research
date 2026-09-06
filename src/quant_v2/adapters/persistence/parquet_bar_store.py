"""Parquet 行情存储（BarStore 实现，T02.1 / D-11）。

## 分区布局

```
var/bars/market=cn_a/dt=2026-09-05/bars.parquet
```

每个 (market, dt) 一个文件，**覆盖写**（幂等）：
同一天重跑 `qv2 data sync`，用同样的数据覆盖同一分区，
行集按 (symbol, date) 排序 + 数值用 decimal128(38,8) 定点存储，
逻辑指纹（`fingerprint_of`）必然一致 —— 这是 D-11 的验收方式。

## 为什么不用文件哈希做幂等验收

pyarrow 的 parquet footer 含写入器版本等元数据，不同版本写出的文件字节可能不同；
**幂等的正确口径是"逻辑行集指纹一致"**，文件字节级一致既不必要也不可控。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from quant_v2.domain.errors import FingerprintError
from quant_v2.domain.models.bar import Bar, InstrumentType
from quant_v2.domain.ports.market_data_port import BarRequest
from quant_v2.domain.services.fingerprint import fingerprint_bars

__all__ = ["ParquetBarStore"]

# decimal128(38, 8)：价格/金额/因子统一精度。
# 38 位有效数字 > 任何行情字段的现实量级（A 股成交额 ~1e12），8 位小数 > 源数据 4 位。
_DECIMAL = pa.decimal128(38, 8)

_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("market", pa.string(), nullable=False),
        pa.field("date", pa.date32(), nullable=False),
        pa.field("open", _DECIMAL, nullable=False),
        pa.field("high", _DECIMAL, nullable=False),
        pa.field("low", _DECIMAL, nullable=False),
        pa.field("close", _DECIMAL, nullable=False),
        pa.field("volume", _DECIMAL, nullable=False),
        pa.field("amount", _DECIMAL, nullable=False),
        pa.field("adj_factor", _DECIMAL, nullable=False),
        pa.field("currency", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("as_of", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("is_trading_day", pa.bool_(), nullable=False),
        pa.field("is_suspended", pa.bool_(), nullable=False),
        pa.field("is_limit_up", pa.bool_(), nullable=True),  # 源未提供时为 null
        pa.field("is_limit_down", pa.bool_(), nullable=True),
        pa.field("instrument_type", pa.string(), nullable=False),
    ]
)


class ParquetBarStore:
    """按 (market, dt) 分区的 Parquet 行情存储。

    实现 `domain.ports.repository_port.BarStore`。
    """

    def __init__(self, root: Path) -> None:
        """Args:
        root: 存储根目录（如 `var/bars/`）。目录不存在则创建 ——
              这是显式指定的数据目录，与 SQLite 的"父目录必须已存在"
              不同（那个防的是把库建到错误位置）。
        """
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------
    # 路径
    # ----------------------------------------------------------
    def partition_path(self, market: str, day: date) -> Path:
        """分区文件路径 `root/market=X/dt=Y/bars.parquet`。"""
        return self.root / f"market={market}" / f"dt={day.isoformat()}" / "bars.parquet"

    # ----------------------------------------------------------
    # BarStore 协议
    # ----------------------------------------------------------
    def save_bars(self, bars: Sequence[Bar]) -> None:
        """写入 bars；同 (market, dt) 分区**覆盖写**（幂等）。

        同一分区内出现多个 (market, dt) 是调用方错误 —— 抛 ValueError，
        防止一次写入悄悄铺到多个分区、回滚不完整。
        """
        if not bars:
            raise ValueError("save_bars 不接受空序列：空写入意味着上游没取到数据，应视为故障")

        markets = {bar.market for bar in bars}
        days = {bar.date for bar in bars}
        if len(markets) > 1 or len(days) > 1:
            raise ValueError(
                f"save_bars 一次只能写一个分区（market={markets}, dt={days}）："
                "多分区写入应按分区拆分后逐个调用，保证覆盖语义清晰"
            )

        market = bars[0].market
        day = bars[0].date

        table = _bars_to_table(bars)
        path = self.partition_path(market, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 先写临时文件再原子替换：进程中途被杀不会留下半截分区
        tmp = path.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(path)

    def partition_dates(self, market: str) -> list[date]:
        """磁盘上某市场已存在的分区日期（升序）。

        门禁执行器 / CLI 用它找"as_of 之前最近的分区"，
        不依赖交易日历种子（种子数据要等 T02.2 数据同步才有）。
        """
        base = self.root / f"market={market}"
        if not base.exists():
            return []
        out: list[date] = []
        for dt_dir in base.iterdir():
            if not (dt_dir / "bars.parquet").exists():
                continue
            try:
                out.append(date.fromisoformat(dt_dir.name.removeprefix("dt=")))
            except ValueError:
                continue  # 目录名不是 dt=YYYY-MM-DD：未知目录不炸，跳过
        return sorted(out)

    def load_bars(self, req: BarRequest) -> Sequence[Bar]:
        """按请求读 bars：区间内各分区逐一加载，按 (symbol, date) 排序返回。

        请求的 `adjust` 不影响存储层读取 —— 存储恒为 RAW + 因子，
        视图换算是 `BarPanel.to_view()` 的职责（单一存储口径，D-03）。
        """
        wanted_symbols = frozenset(req.symbols)
        wanted_types = frozenset(req.instrument_types)
        out: list[Bar] = []
        for day in _iter_days(req.start, req.end):
            path = self.partition_path(req.market, day)
            if not path.exists():
                continue  # 缺分区 = 该日无数据（节假日/未同步），不是错误
            table = pq.read_table(path, schema=_SCHEMA)
            for batch in table.to_batches():
                as_of_col = batch.column("as_of").to_pylist()
                for i in range(batch.num_rows):
                    row = {name: batch.column(name)[i].as_py() for name in _SCHEMA.names}
                    if row["symbol"] not in wanted_symbols:
                        continue
                    if InstrumentType(row["instrument_type"]) not in wanted_types:
                        continue
                    out.append(
                        Bar(
                            symbol=row["symbol"],
                            market=row["market"],
                            date=row["date"],
                            open=row["open"],
                            high=row["high"],
                            low=row["low"],
                            close=row["close"],
                            volume=row["volume"],
                            amount=row["amount"],
                            adj_factor=row["adj_factor"],
                            currency=row["currency"],
                            source=row["source"],
                            as_of=as_of_col[i],
                            is_trading_day=row["is_trading_day"],
                            is_suspended=row["is_suspended"],
                            is_limit_up=row["is_limit_up"],
                            is_limit_down=row["is_limit_down"],
                            instrument_type=InstrumentType(row["instrument_type"]),
                        )
                    )
        out.sort(key=lambda bar: (bar.symbol, bar.date))
        return out

    def fingerprint_of(self, market: str, day: date) -> str:
        """分区逻辑指纹（D-11 幂等验收）。

        同一批数据覆盖写入 N 次 → 指纹恒定；改任何一行 → 指纹必变。
        分区不存在 → FingerprintError（缺分区不是"空指纹"，是故障）。
        """
        bars = self.load_partition(market, day)
        if not bars:
            raise FingerprintError(f"分区无数据，无法计算指纹：market={market} dt={day}")
        # source/as_of 用分区级固定口径：指纹只对"行集内容"敏感
        return fingerprint_bars(
            bars,
            source=f"partition/{market}",
            as_of=datetime.combine(day, time(0), tzinfo=UTC),
        )

    # ----------------------------------------------------------
    # 内部
    # ----------------------------------------------------------
    def load_partition(self, market: str, day: date) -> list[Bar]:
        """加载整个分区（不过滤）。分区缺失返回空列表 ——
        "缺分区"是不是故障由调用方（门禁/指纹）判断，存储层不越权。"""
        path = self.partition_path(market, day)
        if not path.exists():
            return []
        table = pq.read_table(path, schema=_SCHEMA)
        bars: list[Bar] = []
        for batch in table.to_batches():
            as_of_col = batch.column("as_of").to_pylist()
            for i in range(batch.num_rows):
                row = {name: batch.column(name)[i].as_py() for name in _SCHEMA.names}
                bars.append(
                    Bar(
                        symbol=row["symbol"],
                        market=row["market"],
                        date=row["date"],
                        open=row["open"],
                        high=row["high"],
                        low=row["low"],
                        close=row["close"],
                        volume=row["volume"],
                        amount=row["amount"],
                        adj_factor=row["adj_factor"],
                        currency=row["currency"],
                        source=row["source"],
                        as_of=as_of_col[i],
                        is_trading_day=row["is_trading_day"],
                        is_suspended=row["is_suspended"],
                        is_limit_up=row["is_limit_up"],
                        is_limit_down=row["is_limit_down"],
                        instrument_type=InstrumentType(row["instrument_type"]),
                    )
                )
        return bars


def _bars_to_table(bars: Sequence[Bar]) -> pa.Table:
    """Bar 序列 → 排序后的 arrow Table（写入前按 (symbol, date) 排序保证幂等）。"""
    ordered = sorted(bars, key=lambda bar: (bar.symbol, bar.date))
    return pa.Table.from_pydict(
        {
            "symbol": [b.symbol for b in ordered],
            "market": [b.market for b in ordered],
            "date": [b.date for b in ordered],
            "open": [b.open for b in ordered],
            "high": [b.high for b in ordered],
            "low": [b.low for b in ordered],
            "close": [b.close for b in ordered],
            "volume": [b.volume for b in ordered],
            "amount": [b.amount for b in ordered],
            "adj_factor": [b.adj_factor for b in ordered],
            "currency": [b.currency for b in ordered],
            "source": [b.source for b in ordered],
            "as_of": [b.as_of for b in ordered],
            "is_trading_day": [b.is_trading_day for b in ordered],
            "is_suspended": [b.is_suspended for b in ordered],
            "is_limit_up": [b.is_limit_up for b in ordered],
            "is_limit_down": [b.is_limit_down for b in ordered],
            "instrument_type": [b.instrument_type.value for b in ordered],
        },
        schema=_SCHEMA,
    )


def _iter_days(start: date, end: date) -> list[date]:
    """闭区间逐日迭代。区间过大是调用方的问题，这里不做日历裁剪 ——
    日历裁剪是 `TradingCalendar` 的职责，存储层不做重复判断。"""
    days: list[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        # date 迭代无迭代器协议，用 toordinal 步进避免 timedelta 溢出边缘
        cur = date.fromordinal(cur.toordinal() + 1)
    return days
