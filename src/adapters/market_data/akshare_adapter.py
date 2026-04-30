from __future__ import annotations

from dataclasses import dataclass

from src.domain.ports.market_data_port import BaseRemoteMarketDataAdapter


@dataclass
class AkshareAdapter(BaseRemoteMarketDataAdapter):
    """AKShare 外部数据源适配器骨架。"""

    source_name: str = "akshare"
