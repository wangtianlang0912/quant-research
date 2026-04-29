from __future__ import annotations

from pathlib import Path

import pytest

from src.adapters.market_data import LocalParquetAdapter
from src.domain.enums import Frequency


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """创建本地行情CSV测试样例。"""
    data_dir = tmp_path / "1d"
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "000300.SH.csv"
    file_path.write_text(
        "timestamp,open,high,low,close,volume,amount\n"
        "2024-01-02T00:00:00,10,11,9,10.5,1000,10500\n"
        "2024-01-03T00:00:00,10.5,11.5,10,11,1200,13200\n",
        encoding="utf-8",
    )
    return tmp_path


def test_get_bars_returns_rows_within_range(sample_csv: Path) -> None:
    """验证本地行情适配器能够返回指定区间内的K线。"""
    from datetime import datetime

    adapter = LocalParquetAdapter(base_path=str(sample_csv))
    bars = adapter.get_bars(
        symbol="000300.SH",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 1, 31),
        frequency=Frequency.DAY_1,
    )
    assert len(bars) == 2
    assert bars[-1].close == 11
