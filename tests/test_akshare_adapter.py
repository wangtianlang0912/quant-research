from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.adapters.market_data import AkshareAdapter
from src.domain.enums import AdjustType, Frequency
from src.domain.exceptions import DataError
from src.domain.models.market import Bar, Quote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_daily_df(rows: list[dict]) -> "pd.DataFrame":
    """构建模拟日线 DataFrame（含 AKShare 中文列名）。"""
    import pandas as pd  # noqa: PLC0415

    return pd.DataFrame(rows)


def _make_minute_df(rows: list[dict]) -> "pd.DataFrame":
    """构建模拟分钟线 DataFrame（含 AKShare 中文列名）。"""
    import pandas as pd  # noqa: PLC0415

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# get_bars — daily
# ---------------------------------------------------------------------------

class TestAkshareAdapterGetBarsDaily:
    """验证 AkshareAdapter.get_bars 日线逻辑。"""

    def test_returns_bars_in_range(self) -> None:
        """正常返回区间内的日线K线列表。"""
        mock_df = _make_daily_df([
            {"日期": "2024-01-02", "开盘": "10.0", "最高": "11.0", "最低": "9.0", "收盘": "10.5", "成交量": "1000", "成交额": "10500"},
            {"日期": "2024-01-03", "开盘": "10.5", "最高": "11.5", "最低": "10.0", "收盘": "11.0", "成交量": "1200", "成交额": "13200"},
        ])
        adapter = AkshareAdapter()
        with patch("akshare.stock_zh_a_hist", return_value=mock_df):
            bars = adapter.get_bars(
                symbol="000300.SH",
                start=datetime(2024, 1, 1),
                end=datetime(2024, 1, 31),
                frequency=Frequency.DAY_1,
            )
        assert len(bars) == 2
        assert bars[0].close == Decimal("10.5")
        assert bars[1].close == Decimal("11.0")
        assert bars[0].source == "akshare"
        assert bars[0].frequency == Frequency.DAY_1

    def test_strips_exchange_suffix_from_symbol(self) -> None:
        """传入带交易所后缀的代码（如 000300.SH）时，应自动剥离后缀传给 AKShare。"""
        mock_df = _make_daily_df([
            {"日期": "2024-01-02", "开盘": "10.0", "最高": "11.0", "最低": "9.0", "收盘": "10.5", "成交量": "1000", "成交额": "10500"},
        ])
        adapter = AkshareAdapter()
        with patch("akshare.stock_zh_a_hist", return_value=mock_df) as mock_hist:
            adapter.get_bars(
                symbol="000300.SH",
                start=datetime(2024, 1, 1),
                end=datetime(2024, 1, 31),
                frequency=Frequency.DAY_1,
            )
        call_kwargs = mock_hist.call_args.kwargs
        assert call_kwargs["symbol"] == "000300"

    def test_returns_empty_list_when_df_is_empty(self) -> None:
        """AKShare 返回空 DataFrame 时，应返回空列表而不是抛出异常。"""
        import pandas as pd  # noqa: PLC0415
        adapter = AkshareAdapter()
        with patch("akshare.stock_zh_a_hist", return_value=pd.DataFrame()):
            bars = adapter.get_bars(
                symbol="000300.SH",
                start=datetime(2024, 1, 1),
                end=datetime(2024, 1, 31),
                frequency=Frequency.DAY_1,
            )
        assert bars == []

    def test_raises_data_error_on_api_failure(self) -> None:
        """AKShare API 抛出异常时，应包装成 DataError。"""
        adapter = AkshareAdapter()
        with patch("akshare.stock_zh_a_hist", side_effect=Exception("网络超时")):
            with pytest.raises(DataError, match="请求失败"):
                adapter.get_bars(
                    symbol="000300.SH",
                    start=datetime(2024, 1, 1),
                    end=datetime(2024, 1, 31),
                    frequency=Frequency.DAY_1,
                )

    def test_raises_data_error_for_unsupported_frequency(self) -> None:
        """传入不在映射表内的频率时，应抛出 DataError。"""
        adapter = AkshareAdapter()
        # 通过直接传入不合法的 Frequency 来模拟
        with pytest.raises(DataError, match="不支持的频率"):
            # 临时注入一个假 Frequency 枚举值
            class FakeFreq:
                value = "99d"
            adapter.get_bars(
                symbol="000300.SH",
                start=datetime(2024, 1, 1),
                end=datetime(2024, 1, 31),
                frequency=FakeFreq(),  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# get_bars — minute
# ---------------------------------------------------------------------------

class TestAkshareAdapterGetBarsMinute:
    """验证 AkshareAdapter.get_bars 分钟线逻辑。"""

    def test_returns_minute_bars(self) -> None:
        """正常返回分钟线K线列表。"""
        mock_df = _make_minute_df([
            {"时间": "2024-01-02 09:31:00", "开盘": "10.0", "最高": "10.1", "最低": "9.9", "收盘": "10.05", "成交量": "500", "成交额": "5025"},
            {"时间": "2024-01-02 09:32:00", "开盘": "10.05", "最高": "10.2", "最低": "10.0", "收盘": "10.15", "成交量": "600", "成交额": "6090"},
        ])
        adapter = AkshareAdapter()
        with patch("akshare.stock_zh_a_hist_min_em", return_value=mock_df):
            bars = adapter.get_bars(
                symbol="000300.SH",
                start=datetime(2024, 1, 2, 9, 30),
                end=datetime(2024, 1, 2, 10, 0),
                frequency=Frequency.MIN_1,
            )
        assert len(bars) == 2
        assert bars[0].frequency == Frequency.MIN_1
        assert bars[0].close == Decimal("10.05")

    def test_uses_correct_period_for_5m(self) -> None:
        """5 分钟频率应传 period='5' 给 AKShare。"""
        import pandas as pd  # noqa: PLC0415
        adapter = AkshareAdapter()
        with patch("akshare.stock_zh_a_hist_min_em", return_value=pd.DataFrame()) as mock_min:
            adapter.get_bars(
                symbol="000300.SH",
                start=datetime(2024, 1, 2, 9, 30),
                end=datetime(2024, 1, 2, 11, 0),
                frequency=Frequency.MIN_5,
            )
        call_kwargs = mock_min.call_args.kwargs
        assert call_kwargs["period"] == "5"


# ---------------------------------------------------------------------------
# get_latest_bar
# ---------------------------------------------------------------------------

class TestAkshareAdapterGetLatestBar:
    """验证 AkshareAdapter.get_latest_bar 逻辑。"""

    def test_returns_last_bar(self) -> None:
        """应返回区间内最后一根K线。"""
        mock_df = _make_daily_df([
            {"日期": "2026-01-02", "开盘": "10.0", "最高": "11.0", "最低": "9.0", "收盘": "10.5", "成交量": "1000", "成交额": "10500"},
            {"日期": "2026-01-03", "开盘": "10.5", "最高": "11.5", "最低": "10.0", "收盘": "11.0", "成交量": "1200", "成交额": "13200"},
        ])
        adapter = AkshareAdapter()
        with patch("akshare.stock_zh_a_hist", return_value=mock_df):
            bar = adapter.get_latest_bar("000300.SH", Frequency.DAY_1)
        assert bar is not None
        assert bar.close == Decimal("11.0")

    def test_returns_none_on_failure(self) -> None:
        """API 失败时应返回 None 而不抛出异常。"""
        adapter = AkshareAdapter()
        with patch("akshare.stock_zh_a_hist", side_effect=Exception("超时")):
            bar = adapter.get_latest_bar("000300.SH", Frequency.DAY_1)
        assert bar is None


# ---------------------------------------------------------------------------
# get_latest_quote
# ---------------------------------------------------------------------------

class TestAkshareAdapterGetLatestQuote:
    """验证 AkshareAdapter.get_latest_quote 逻辑。"""

    def test_returns_quote_from_spot(self) -> None:
        """能够从实时行情接口构造 Quote 对象。"""
        import pandas as pd  # noqa: PLC0415
        spot_df = pd.DataFrame([{"代码": "000300", "最新价": "10.5", "成交量": "5000"}])
        adapter = AkshareAdapter()
        with patch("akshare.stock_zh_a_spot_em", return_value=spot_df):
            quote = adapter.get_latest_quote("000300.SH")
        assert quote is not None
        assert quote.last == Decimal("10.5")
        assert quote.source == "akshare"

    def test_falls_back_to_latest_bar_when_spot_empty(self) -> None:
        """实时行情中找不到该标的时，应回退到历史K线构造 Quote。"""
        import pandas as pd  # noqa: PLC0415
        spot_df = pd.DataFrame(columns=["代码", "最新价", "成交量"])
        daily_df = _make_daily_df([
            {"日期": "2026-01-03", "开盘": "10.5", "最高": "11.5", "最低": "10.0", "收盘": "11.0", "成交量": "1200", "成交额": "13200"},
        ])
        adapter = AkshareAdapter()
        with patch("akshare.stock_zh_a_spot_em", return_value=spot_df), \
             patch("akshare.stock_zh_a_hist", return_value=daily_df):
            quote = adapter.get_latest_quote("000300.SH")
        assert quote is not None
        assert quote.last == Decimal("11.0")


# ---------------------------------------------------------------------------
# list_trading_days
# ---------------------------------------------------------------------------

class TestAkshareAdapterListTradingDays:
    """验证 AkshareAdapter.list_trading_days 逻辑。"""

    def test_returns_trading_days_from_akshare(self) -> None:
        """正常从 AKShare 返回交易日列表。"""
        import pandas as pd  # noqa: PLC0415
        trade_df = pd.DataFrame({"trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"]})
        adapter = AkshareAdapter()
        with patch("akshare.tool_trade_date_hist_sina", return_value=trade_df):
            days = adapter.list_trading_days(date(2024, 1, 1), date(2024, 1, 5))
        assert date(2024, 1, 2) in days
        assert date(2024, 1, 4) in days

    def test_falls_back_to_weekdays_on_failure(self) -> None:
        """AKShare 失败时，应回退到工作日近似。"""
        adapter = AkshareAdapter()
        with patch("akshare.tool_trade_date_hist_sina", side_effect=Exception("超时")):
            days = adapter.list_trading_days(date(2024, 1, 1), date(2024, 1, 7))
        # 2024-01-01 是周一，2024-01-05 是周五，2024-01-06/07 是周末
        assert date(2024, 1, 1) in days
        assert date(2024, 1, 5) in days
        assert date(2024, 1, 6) not in days


# ---------------------------------------------------------------------------
# Token / env var
# ---------------------------------------------------------------------------

class TestAkshareAdapterTokenHandling:
    """验证 AkshareAdapter 对 token 和环境变量的处理。"""

    def test_reads_token_from_env(self, monkeypatch) -> None:
        """应从 AKSHARE_TOKEN 环境变量读取 token。"""
        monkeypatch.setenv("AKSHARE_TOKEN", "test-token-123")
        adapter = AkshareAdapter()
        assert adapter.token == "test-token-123"

    def test_token_is_none_when_env_not_set(self, monkeypatch) -> None:
        """未设置环境变量时，token 应为 None。"""
        monkeypatch.delenv("AKSHARE_TOKEN", raising=False)
        adapter = AkshareAdapter()
        assert adapter.token is None
