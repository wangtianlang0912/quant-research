from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.domain.enums import AdjustType, Frequency
from src.domain.exceptions import DataError
from src.domain.models.market import Bar, Quote
from src.domain.ports.market_data_port import BaseRemoteMarketDataAdapter

# AKShare frequency mapping
_AKSHARE_PERIOD_MAP: dict[Frequency, str] = {
    Frequency.DAY_1: "daily",
    Frequency.MIN_1: "1",
    Frequency.MIN_5: "5",
    Frequency.MIN_15: "15",
    Frequency.MIN_30: "30",
    Frequency.MIN_60: "60",
}

# AKShare adjust type mapping
_AKSHARE_ADJUST_MAP: dict[AdjustType, str] = {
    AdjustType.NONE: "",
    AdjustType.QFQ: "qfq",
    AdjustType.HFQ: "hfq",
}


def _import_akshare():
    """动态导入 akshare，若未安装则抛出清晰异常。"""
    try:
        import akshare as ak  # noqa: PLC0415
        return ak
    except ImportError as exc:
        raise DataError(
            "akshare 未安装，请执行 `pip install akshare` 后重试。"
        ) from exc


@dataclass
class AkshareAdapter(BaseRemoteMarketDataAdapter):
    """基于 AKShare 的真实外部数据源适配器。

    认证信息：AKShare 大部分接口无需 token，可直接使用。
    若部分接口需要，请通过环境变量 AKSHARE_TOKEN 传入。

    环境变量：
        AKSHARE_TOKEN: （可选）AKShare API token，当前多数接口无需设置。
    """

    source_name: str = "akshare"

    def __post_init__(self) -> None:
        if self.token is None:
            self.token = os.environ.get("AKSHARE_TOKEN")

    def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        frequency: Frequency,
        adjust_type: AdjustType = AdjustType.NONE,
    ) -> list[Bar]:
        """从 AKShare 拉取指定标的在指定时间区间内的K线数据。

        Args:
            symbol: 标的代码，如 '000300' 或 '000300.SH'。
            start: 起始时间（含）。
            end: 结束时间（含）。
            frequency: 数据频率，支持日线与分钟线。
            adjust_type: 复权类型。

        Returns:
            K线列表，按时间升序排列。

        Raises:
            DataError: 当 AKShare 未安装、返回空数据或请求失败时。
        """
        ak = _import_akshare()
        clean_symbol = symbol.split(".")[0]
        period = _AKSHARE_PERIOD_MAP.get(frequency)
        if period is None:
            raise DataError(f"AkshareAdapter: 不支持的频率 {frequency}")
        adjust = _AKSHARE_ADJUST_MAP.get(adjust_type, "")

        try:
            if frequency == Frequency.DAY_1:
                df = ak.stock_zh_a_hist(
                    symbol=clean_symbol,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust=adjust,
                )
            else:
                df = ak.stock_zh_a_hist_min_em(
                    symbol=clean_symbol,
                    period=period,
                    start_date=start.strftime("%Y-%m-%d %H:%M:%S"),
                    end_date=end.strftime("%Y-%m-%d %H:%M:%S"),
                    adjust=adjust,
                )
        except Exception as exc:
            raise DataError(f"AkshareAdapter.get_bars 请求失败: {exc}") from exc

        if df is None or df.empty:
            return []

        bars: list[Bar] = []
        for _, row in df.iterrows():
            try:
                if frequency == Frequency.DAY_1:
                    ts = datetime.strptime(str(row["日期"]), "%Y-%m-%d")
                    open_price = Decimal(str(row["开盘"]))
                    high_price = Decimal(str(row["最高"]))
                    low_price = Decimal(str(row["最低"]))
                    close_price = Decimal(str(row["收盘"]))
                    volume = Decimal(str(row.get("成交量", 0)))
                    amount = Decimal(str(row["成交额"])) if "成交额" in row else None
                else:
                    ts = datetime.strptime(str(row["时间"]), "%Y-%m-%d %H:%M:%S")
                    open_price = Decimal(str(row["开盘"]))
                    high_price = Decimal(str(row["最高"]))
                    low_price = Decimal(str(row["最低"]))
                    close_price = Decimal(str(row["收盘"]))
                    volume = Decimal(str(row.get("成交量", 0)))
                    amount = Decimal(str(row["成交额"])) if "成交额" in row else None

                if ts < start or ts > end:
                    continue

                bars.append(
                    Bar(
                        symbol=symbol,
                        timestamp=ts,
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        volume=volume,
                        amount=amount,
                        frequency=frequency,
                        adjust_type=adjust_type,
                        source="akshare",
                    )
                )
            except (KeyError, ValueError) as exc:
                raise DataError(f"AkshareAdapter: 解析K线数据失败: {exc}") from exc

        return bars

    def get_latest_bar(self, symbol: str, frequency: Frequency) -> Bar | None:
        """获取最新一根K线。

        Returns:
            最新K线，若数据不可用则返回 None。
        """
        now = datetime.now()
        # 用较宽的时间窗口确保能取到历史数据
        lookback_days = 365 if frequency == Frequency.DAY_1 else 7
        start = now - timedelta(days=lookback_days)
        try:
            bars = self.get_bars(symbol, start, now, frequency)
        except DataError:
            return None
        return bars[-1] if bars else None

    def get_latest_quote(self, symbol: str) -> Quote | None:
        """从 AKShare 获取最新实时报价。

        Returns:
            最新报价，若数据不可用则返回 None。
        """
        ak = _import_akshare()
        clean_symbol = symbol.split(".")[0]
        try:
            df = ak.stock_zh_a_spot_em()
            row = df[df["代码"] == clean_symbol]
            if row.empty:
                bar = self.get_latest_bar(symbol, Frequency.DAY_1)
                if bar is None:
                    return None
                return Quote(
                    symbol=symbol,
                    timestamp=bar.timestamp,
                    bid=bar.close,
                    ask=bar.close,
                    last=bar.close,
                    volume=bar.volume,
                    source="akshare",
                )
            r = row.iloc[0]
            price = Decimal(str(r["最新价"])) if r.get("最新价") else None
            volume = Decimal(str(r["成交量"])) if r.get("成交量") else None
            return Quote(
                symbol=symbol,
                timestamp=datetime.now(),
                bid=price,
                ask=price,
                last=price,
                volume=volume,
                source="akshare",
            )
        except Exception:  # noqa: BLE001
            bar = self.get_latest_bar(symbol, Frequency.DAY_1)
            if bar is None:
                return None
            return Quote(
                symbol=symbol,
                timestamp=bar.timestamp,
                bid=bar.close,
                ask=bar.close,
                last=bar.close,
                volume=bar.volume,
                source="akshare",
            )

    def list_trading_days(self, start: date, end: date) -> list[date]:
        """使用 AKShare 获取 A 股交易日历。

        若 AKShare 请求失败，回退到工作日近似。

        Returns:
            交易日列表，按升序排列。
        """
        ak = _import_akshare()
        try:
            df = ak.tool_trade_date_hist_sina()
            days = [
                datetime.strptime(str(d), "%Y-%m-%d").date()
                for d in df["trade_date"]
                if start <= datetime.strptime(str(d), "%Y-%m-%d").date() <= end
            ]
            return sorted(days)
        except Exception:  # noqa: BLE001
            return super().list_trading_days(start, end)

