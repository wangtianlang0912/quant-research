"""ParquetBarStore 测试（T02.1 / D-11）。

验收点：
- 分区路径 `market=cn_a/dt=X/bars.parquet`
- 保存 → 读取往返等值（含 Decimal / None / 停牌标记）
- ★ 幂等（D-11）：同日重跑指纹一致；乱序写入指纹一致；改一行指纹必变
- 多分区一次写入被拒（防半截覆盖）
- 缺分区的指纹是 FingerprintError 而非空值
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from tests.conftest import START_DATE, make_bar

from quant_v2.adapters.persistence.parquet_bar_store import ParquetBarStore
from quant_v2.domain.errors import FingerprintError
from quant_v2.domain.models.bar import AdjustType, InstrumentType
from quant_v2.domain.ports.market_data_port import BarRequest

pytestmark = pytest.mark.unit

DAY1 = START_DATE
DAY2 = date(2026, 1, 6)


def test_分区路径布局(tmp_path: Path) -> None:
    """★ T02.1 验收标准原文：`var/bars/market=cn_a/dt=X/bars.parquet`。"""
    store = ParquetBarStore(tmp_path / "bars")
    path = store.partition_path("cn_a", DAY1)
    assert path == tmp_path / "bars" / "market=cn_a" / f"dt={DAY1.isoformat()}" / "bars.parquet"


def test_保存读取往返等值(tmp_path: Path) -> None:
    """Decimal / None 涨跌停标记 / 停牌标记全部无损往返。"""
    store = ParquetBarStore(tmp_path / "bars")
    bars = [
        make_bar(symbol="601186.SH", day=DAY1, close="10.2", adj_factor="1.5"),
        make_bar(symbol="000001.SZ", day=DAY1, close="12.34", adj_factor="2.0"),
    ]
    store.save_bars(bars)

    req = BarRequest(
        symbols=("601186.SH", "000001.SZ"),
        market="cn_a",
        start=DAY1,
        end=DAY1,
        adjust=AdjustType.RAW,
    )
    loaded = store.load_bars(req)
    assert len(loaded) == 2
    # 按 (symbol, date) 排序返回
    assert loaded[0].symbol == "000001.SZ"
    # 字段逐一比对（pydantic 等值比较，Decimal 数值相等即等）
    by_symbol = {b.symbol: b for b in loaded}
    assert by_symbol["601186.SH"].close == bars[0].close
    assert by_symbol["601186.SH"].adj_factor == bars[0].adj_factor
    assert by_symbol["601186.SH"].source == "test"
    assert by_symbol["601186.SH"].as_of == bars[0].as_of


def test_涨跌停None无损往返(tmp_path: Path) -> None:
    """is_limit_up/down 为 None（源未提供）不能被写成 False。"""
    store = ParquetBarStore(tmp_path / "bars")
    bar = make_bar(symbol="601186.SH", day=DAY1, close="10")
    assert bar.is_limit_up is None and bar.is_limit_down is None
    store.save_bars([bar])
    loaded = store.load_bars(
        BarRequest(
            symbols=("601186.SH",),
            market="cn_a",
            start=DAY1,
            end=DAY1,
            adjust=AdjustType.RAW,
        )
    )
    assert loaded[0].is_limit_up is None
    assert loaded[0].is_limit_down is None


def test_幂等_同数据重跑指纹一致(tmp_path: Path) -> None:
    """★ D-11 核心验收：同日重跑（覆盖写）指纹一致。"""
    store = ParquetBarStore(tmp_path / "bars")
    bars = [
        make_bar(symbol="601186.SH", day=DAY1, close="10.2", adj_factor="1.5"),
        make_bar(symbol="000001.SZ", day=DAY1, close="12.34"),
    ]
    store.save_bars(bars)
    fp1 = store.fingerprint_of("cn_a", DAY1)

    store.save_bars(bars)  # 同日重跑 → 覆盖
    fp2 = store.fingerprint_of("cn_a", DAY1)
    assert fp1 == fp2


def test_幂等_乱序写入指纹一致(tmp_path: Path) -> None:
    """行序不影响指纹（写入前强制 (symbol, date) 排序）。"""
    store = ParquetBarStore(tmp_path / "bars")
    a = make_bar(symbol="601186.SH", day=DAY1, close="10.2")
    b = make_bar(symbol="000001.SZ", day=DAY1, close="12.34")
    store.save_bars([a, b])
    fp1 = store.fingerprint_of("cn_a", DAY1)
    store.save_bars([b, a])  # 乱序重写
    fp2 = store.fingerprint_of("cn_a", DAY1)
    assert fp1 == fp2


def test_改一行指纹必变(tmp_path: Path) -> None:
    store = ParquetBarStore(tmp_path / "bars")
    store.save_bars([make_bar(symbol="601186.SH", day=DAY1, close="10.2")])
    fp1 = store.fingerprint_of("cn_a", DAY1)
    store.save_bars([make_bar(symbol="601186.SH", day=DAY1, close="10.3")])  # 改一行
    fp2 = store.fingerprint_of("cn_a", DAY1)
    assert fp1 != fp2


def test_缺分区指纹抛错而非空值(tmp_path: Path) -> None:
    """★ 空指纹 = 静默失败（v1 病根）：缺分区必须是显式故障。"""
    store = ParquetBarStore(tmp_path / "bars")
    with pytest.raises(FingerprintError, match="分区无数据"):
        store.fingerprint_of("cn_a", DAY1)


def test_多分区一次写入被拒(tmp_path: Path) -> None:
    """防半截覆盖：一次调用只能写一个 (market, dt) 分区。"""
    store = ParquetBarStore(tmp_path / "bars")
    bars = [
        make_bar(symbol="601186.SH", day=DAY1, close="10"),
        make_bar(symbol="601186.SH", day=DAY2, close="10.1"),
    ]
    with pytest.raises(ValueError, match="一次只能写一个分区"):
        store.save_bars(bars)


def test_空写入被拒(tmp_path: Path) -> None:
    store = ParquetBarStore(tmp_path / "bars")
    with pytest.raises(ValueError, match="不接受空序列"):
        store.save_bars([])


def test_读取过滤标的与区间(tmp_path: Path) -> None:
    store = ParquetBarStore(tmp_path / "bars")
    store.save_bars(
        [
            make_bar(symbol="601186.SH", day=DAY1, close="10"),
            make_bar(symbol="000001.SZ", day=DAY1, close="12"),
        ]
    )
    store.save_bars([make_bar(symbol="601186.SH", day=DAY2, close="10.5")])

    req = BarRequest(
        symbols=("601186.SH",),
        market="cn_a",
        start=DAY1,
        end=DAY2,
        adjust=AdjustType.RAW,
    )
    loaded = store.load_bars(req)
    assert len(loaded) == 2
    assert {b.date for b in loaded} == {DAY1, DAY2}

    # 区间只取 DAY2
    req2 = BarRequest(
        symbols=("601186.SH",), market="cn_a", start=DAY2, end=DAY2, adjust=AdjustType.RAW
    )
    assert len(store.load_bars(req2)) == 1


def test_读取过滤品种类型(tmp_path: Path) -> None:
    """指数（INDEX）默认不进 EQUITY 请求（诊断 #10 的存储层落点）。"""
    store = ParquetBarStore(tmp_path / "bars")
    equity = make_bar(symbol="601186.SH", day=DAY1, close="10")
    index_bar = make_bar(symbol="000300.SH", day=DAY1, close="4000")
    # make_bar 不支持 instrument_type 参数，手工构造 INDEX bar
    from quant_v2.domain.models.bar import Bar  # noqa: PLC0415

    index_bar = Bar(
        **{
            **index_bar.model_dump(),
            "instrument_type": InstrumentType.INDEX,
        }
    )
    store.save_bars([equity, index_bar])

    req = BarRequest(
        symbols=("601186.SH", "000300.SH"),
        market="cn_a",
        start=DAY1,
        end=DAY1,
        adjust=AdjustType.RAW,
    )
    loaded = store.load_bars(req)
    assert {b.symbol for b in loaded} == {"601186.SH"}

    req_all = BarRequest(
        symbols=("601186.SH", "000300.SH"),
        market="cn_a",
        start=DAY1,
        end=DAY1,
        adjust=AdjustType.RAW,
        instrument_types=(InstrumentType.EQUITY, InstrumentType.INDEX),
    )
    assert len(store.load_bars(req_all)) == 2


def test_缺分区静默跳过(tmp_path: Path) -> None:
    """区间内没有分区的日子不是错误（节假日/未同步）。"""
    store = ParquetBarStore(tmp_path / "bars")
    store.save_bars([make_bar(symbol="601186.SH", day=DAY2, close="10")])
    loaded = store.load_bars(
        BarRequest(
            symbols=("601186.SH",),
            market="cn_a",
            start=DAY1,
            end=DAY2,
            adjust=AdjustType.RAW,
        )
    )
    assert len(loaded) == 1  # DAY1 无分区，只拿到 DAY2
