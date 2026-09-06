"""MarketProfile 加载器 —— YAML → frozen dataclass。

★ **这是全项目唯一允许出现"按市场取配置"的地方**（`ARCH001` 白名单）。

设计要点：

1. **配置优先于分支**：市场差异表达为数值（`limit_pct` / `lot_size` / `tick`）。
2. **`None` 优先于特例**：无涨跌停 = `limit_pct: null`，而不是 `if market != 'cn_a'`。
3. **极端特例用类路径注入**：`hooks` 里写 dotted path，由 `load_hook()` 用 importlib 加载。

**抽象纪律：禁止把 MarketProfile 膨胀成"半个策略"。**
这个文件只加载"市场规则"，不加载"这个市场该怎么赚钱"——后者属于 `configs/strategies/`。
一旦这里开始出现 `breakout_threshold`、`momentum_window` 之类的字段，
就等于把策略参数偷偷搬进了市场配置，多市场复用会立刻崩掉。

## 缓存

加载结果按 `(目录, 文件 mtime, 文件大小)` 缓存。文件大小和 mtime 进 key 是为了
**改了 YAML 立刻生效**（热加载），不需要重启进程。
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quant_v2.domain.errors import ConfigValidationError, MarketProfileNotFoundError
from quant_v2.domain.models.market import (
    Availability,
    CostModel,
    DataCapabilities,
    DataSourceSpec,
    MarketProfile,
    PriceLimitSpec,
    TickSpec,
)
from quant_v2.domain.services.fingerprint import fingerprint_mapping

__all__ = [
    "DEFAULT_MARKETS_DIR",
    "CostModelConfig",
    "DataCapabilitiesConfig",
    "DataSourceSpecConfig",
    "MarketProfileConfig",
    "PriceLimitSpecConfig",
    "TickSpecConfig",
    "available_markets",
    "clear_cache",
    "load_all_market_profiles",
    "load_hook",
    "load_market_profile",
    "profile_fingerprint",
]

# 默认配置目录（相对仓库根）。CLI 与测试可通过 `config_dir` 覆盖。
DEFAULT_MARKETS_DIR: Path = Path("configs/markets")

# 只加载 `.yaml`；`.yaml.template` 是注释模板，本来就不完整，不参与加载
_MARKET_FILE_SUFFIX: str = ".yaml"

_CACHE: dict[tuple[str, int, int], MarketProfile] = {}

_T = TypeVar("_T")


# ============================================================================
# 配置 schema（Pydantic）—— extra="forbid" 是"配置写错即报错"的关键
# ============================================================================


class TickSpecConfig(BaseModel):
    """最小报价单位配置。

    `tick_table` 为分段表 `((价格上界, tick), ...)` 升序；港股用得到。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tick_size: Decimal | None = None
    tick_table: tuple[tuple[Decimal, Decimal], ...] = ()


class PriceLimitSpecConfig(BaseModel):
    """涨跌停配置。全部可空 —— `null` 表示"该市场无此约束"。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    limit_pct: Decimal | None = None
    st_limit_pct: Decimal | None = None
    new_listing_free_days: int = 0
    ipo_first_day_pct: Decimal | None = None


class CostModelConfig(BaseModel):
    """成本配置。

    ★ 买入/卖出税率分开两个字段（而不是单个 `tax_rate` + 代码里判方向）：
    两个数字可以直接查表，零分支。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    commission_rate: Decimal = Field(ge=0)
    commission_min: Decimal = Field(ge=0)
    tax_rate_sell: Decimal = Field(default=Decimal("0"), ge=0)
    tax_rate_buy: Decimal = Field(default=Decimal("0"), ge=0)
    transfer_fee_rate: Decimal = Field(default=Decimal("0"), ge=0)
    exchange_fee_rate: Decimal = Field(default=Decimal("0"), ge=0)
    slippage_bps: int = Field(default=0, ge=0)


class DataCapabilitiesConfig(BaseModel):
    """数据源能力声明配置。★ 必须如实填写。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    daily_bars: bool = True
    adj_factor: bool = True
    delisting_history: Availability = "NONE"
    delisting_list: bool = False
    trading_calendar: bool = True
    fundamentals: bool = False
    intraday: bool = False
    rate_limit_per_min: int | None = None


class DataSourceSpecConfig(BaseModel):
    """数据源声明配置。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    adapter: str
    priority: int = 0
    capabilities: DataCapabilitiesConfig = Field(default_factory=DataCapabilitiesConfig)


class MarketProfileConfig(BaseModel):
    """MarketProfile 的配置 schema。

    ★ `extra="forbid"`：字段名拼错直接报错，而不是被静默丢弃。
    默默用默认值的配置比没有配置更危险 —— 你以为生效了，其实没有。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    market_code: str
    display_name: str
    timezone: str  # IANA 时区名
    calendar_id: str
    currency: str
    settlement_currency: str | None = None
    lot_size: int = Field(gt=0)
    odd_lot_allowed: bool = False
    tick: TickSpecConfig
    price_limit: PriceLimitSpecConfig = Field(default_factory=PriceLimitSpecConfig)
    t_plus: int = Field(default=0, ge=0)
    shortable: bool = False
    cost: CostModelConfig
    symbol_pattern: str
    half_day_dates: tuple[date, ...] = ()
    extra_holidays: tuple[date, ...] = ()
    fund_availability: Availability = "NONE"
    delisting_data_availability: Availability = "NONE"
    max_symbols: int = Field(gt=0)
    data_sources: tuple[DataSourceSpecConfig, ...] = ()
    hooks: Mapping[str, str] = Field(default_factory=dict)

    def to_domain(self) -> MarketProfile:
        """转成领域层的 frozen `MarketProfile`。"""
        return MarketProfile(
            market_code=self.market_code,
            display_name=self.display_name,
            timezone=self.timezone,
            calendar_id=self.calendar_id,
            currency=self.currency,
            settlement_currency=self.settlement_currency,
            lot_size=self.lot_size,
            odd_lot_allowed=self.odd_lot_allowed,
            tick=TickSpec(tick_size=self.tick.tick_size, tick_table=self.tick.tick_table),
            price_limit=PriceLimitSpec(
                limit_pct=self.price_limit.limit_pct,
                st_limit_pct=self.price_limit.st_limit_pct,
                new_listing_free_days=self.price_limit.new_listing_free_days,
                ipo_first_day_pct=self.price_limit.ipo_first_day_pct,
            ),
            t_plus=self.t_plus,
            shortable=self.shortable,
            cost=CostModel(
                commission_rate=self.cost.commission_rate,
                commission_min=self.cost.commission_min,
                tax_rate_sell=self.cost.tax_rate_sell,
                tax_rate_buy=self.cost.tax_rate_buy,
                transfer_fee_rate=self.cost.transfer_fee_rate,
                exchange_fee_rate=self.cost.exchange_fee_rate,
                slippage_bps=self.cost.slippage_bps,
            ),
            symbol_pattern=self.symbol_pattern,
            half_day_dates=self.half_day_dates,
            extra_holidays=self.extra_holidays,
            fund_availability=self.fund_availability,
            delisting_data_availability=self.delisting_data_availability,
            max_symbols=self.max_symbols,
            data_sources=tuple(
                DataSourceSpec(
                    source_id=source.source_id,
                    adapter=source.adapter,
                    priority=source.priority,
                    capabilities=DataCapabilities(
                        daily_bars=source.capabilities.daily_bars,
                        adj_factor=source.capabilities.adj_factor,
                        delisting_history=source.capabilities.delisting_history,
                        delisting_list=source.capabilities.delisting_list,
                        trading_calendar=source.capabilities.trading_calendar,
                        fundamentals=source.capabilities.fundamentals,
                        intraday=source.capabilities.intraday,
                        rate_limit_per_min=source.capabilities.rate_limit_per_min,
                    ),
                )
                for source in self.data_sources
            ),
            hooks=dict(self.hooks),
        )


# ============================================================================
# 加载入口
# ============================================================================


def _resolve_dir(config_dir: Path | None) -> Path:
    """解析配置目录；`None` 时用默认目录。"""
    return DEFAULT_MARKETS_DIR if config_dir is None else Path(config_dir)


def _market_file(config_dir: Path, market_code: str) -> Path:
    """市场配置文件路径。"""
    return config_dir / f"{market_code}{_MARKET_FILE_SUFFIX}"


def clear_cache() -> None:
    """清空加载缓存（测试与热加载场景使用）。"""
    _CACHE.clear()


def available_markets(*, config_dir: Path | None = None) -> tuple[str, ...]:
    """列出该目录下所有**已实装**的市场代码（不含 `.yaml.template`）。

    `*_calendar_overrides.yaml` 是交易日历手工表（T02.4），与市场 profile
    同目录但不是 profile —— 显式排除，避免被当作市场代码加载。
    """
    directory = _resolve_dir(config_dir)
    if not directory.is_dir():
        return ()
    codes = [
        path.name[: -len(_MARKET_FILE_SUFFIX)]
        for path in directory.iterdir()
        if path.is_file()
        and path.name.endswith(_MARKET_FILE_SUFFIX)
        and not path.name.endswith("_calendar_overrides.yaml")
    ]
    return tuple(sorted(codes))


def _load_uncached(directory: Path, market_code: str) -> MarketProfile:
    """真正的一次加载（无缓存）。"""
    path = _market_file(directory, market_code)
    if not path.is_file():
        raise MarketProfileNotFoundError(
            f"找不到市场配置 {path}："
            f"已实装的市场为 {list(available_markets(config_dir=directory))}。"
            f"（.yaml.template 是注释模板，不参与加载）"
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigValidationError(f"YAML 解析失败 {path}：{exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigValidationError(
            f"市场配置 {path} 的顶层必须是映射（mapping），收到 {type(raw).__name__}"
        )
    if raw.get("market_code") != market_code:
        raise ConfigValidationError(
            f"市场配置 {path} 的 market_code={raw.get('market_code')!r} "
            f"与文件名暗示的 {market_code!r} 不一致："
            "文件名与内容不一致会让【按代码加载】变成猜谜"
        )

    try:
        config = MarketProfileConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigValidationError(f"市场配置 {path} 未通过 schema 校验：\n{exc}") from exc

    return config.to_domain()


def load_market_profile(
    market_code: str,
    *,
    config_dir: Path | None = None,
) -> MarketProfile:
    """加载单个市场画像。

    Args:
        market_code: 市场代码，如 `'cn_a'`。
        config_dir: 配置目录；`None` 时用 `configs/markets`。

    Returns:
        frozen 的 `MarketProfile`。

    Raises:
        MarketProfileNotFoundError: 配置文件不存在。
        ConfigValidationError: YAML 解析失败或未通过 schema 校验。
    """
    directory = _resolve_dir(config_dir)
    path = _market_file(directory, market_code)
    stat = path.stat() if path.is_file() else None
    key = (
        str(path.resolve()) if stat is not None else str(path),
        stat.st_mtime_ns if stat is not None else -1,
        stat.st_size if stat is not None else -1,
    )
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    profile = _load_uncached(directory, market_code)
    _CACHE[key] = profile
    return profile


def load_all_market_profiles(
    *,
    config_dir: Path | None = None,
) -> Mapping[str, MarketProfile]:
    """加载目录下全部已实装的市场画像。

    Returns:
        `{market_code: MarketProfile}`。
    """
    directory = _resolve_dir(config_dir)
    return {
        code: load_market_profile(code, config_dir=directory)
        for code in available_markets(config_dir=directory)
    }


def load_hook(profile: MarketProfile, name: str) -> Callable[..., Any]:
    """★ 极端特例的类路径注入（抽象纪律第三条）。

    实在无法数值化的市场特例（例如"A 股 ST 股涨跌幅判定"），
    在 YAML 的 `hooks` 里写 dotted path，由这里用 `importlib` 加载。

    Args:
        profile: 市场画像。
        name: hook 名称。

    Returns:
        可调用对象。

    Raises:
        ConfigValidationError: 未配置该 hook，或 dotted path 无法导入。
    """
    dotted = profile.hooks.get(name)
    if not dotted:
        raise ConfigValidationError(
            f"市场 {profile.market_code} 未配置 hook {name!r}；"
            f"已配置的 hooks：{sorted(profile.hooks)}"
        )
    module_path, _, attr = dotted.rpartition(".")
    if not module_path:
        raise ConfigValidationError(
            f"hook {name!r} 的 dotted path 非法：{dotted!r}（应为 'pkg.module.attr'）"
        )
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ConfigValidationError(
            f"无法导入 hook {name!r} 的模块 {module_path!r}：{exc}"
        ) from exc
    target = getattr(module, attr, None)
    if target is None:
        raise ConfigValidationError(f"hook {name!r} 的模块 {module_path!r} 中不存在属性 {attr!r}")
    if not callable(target):
        raise ConfigValidationError(
            f"hook {name!r} 指向的 {dotted!r} 不可调用（实际类型 {type(target).__name__}）"
        )
    return target


def profile_fingerprint(profile: MarketProfile) -> str:
    """市场配置指纹（写进 `run_manifest.market_profiles_hash`）。

    配置变了，回测结论就可能变 —— 不记下来就无法解释"为什么两次回测不一样"。
    """
    payload: dict[str, Any] = {
        "market_code": profile.market_code,
        "timezone": profile.timezone,
        "calendar_id": profile.calendar_id,
        "currency": profile.currency,
        "settlement_currency": profile.settlement_currency,
        "lot_size": profile.lot_size,
        "odd_lot_allowed": profile.odd_lot_allowed,
        "tick_size": str(profile.tick.tick_size),
        "tick_table": [[str(u), str(t)] for u, t in profile.tick.tick_table],
        "price_limit": {
            "limit_pct": str(profile.price_limit.limit_pct),
            "st_limit_pct": str(profile.price_limit.st_limit_pct),
            "new_listing_free_days": profile.price_limit.new_listing_free_days,
            "ipo_first_day_pct": str(profile.price_limit.ipo_first_day_pct),
        },
        "t_plus": profile.t_plus,
        "shortable": profile.shortable,
        "cost": {
            "commission_rate": str(profile.cost.commission_rate),
            "commission_min": str(profile.cost.commission_min),
            "tax_rate_sell": str(profile.cost.tax_rate_sell),
            "tax_rate_buy": str(profile.cost.tax_rate_buy),
            "transfer_fee_rate": str(profile.cost.transfer_fee_rate),
            "exchange_fee_rate": str(profile.cost.exchange_fee_rate),
            "slippage_bps": profile.cost.slippage_bps,
        },
        "symbol_pattern": profile.symbol_pattern,
        "half_day_dates": [d.isoformat() for d in profile.half_day_dates],
        "extra_holidays": [d.isoformat() for d in profile.extra_holidays],
        "fund_availability": profile.fund_availability,
        "delisting_data_availability": profile.delisting_data_availability,
        "max_symbols": profile.max_symbols,
        "data_sources": [
            {
                "source_id": spec.source_id,
                "adapter": spec.adapter,
                "priority": spec.priority,
            }
            for spec in profile.data_sources
        ],
        "hooks": dict(profile.hooks),
    }
    return fingerprint_mapping(payload)
