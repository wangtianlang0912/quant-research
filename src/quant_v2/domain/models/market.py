"""市场画像（D-02）—— 市场的全部差异集中于此。

★ 这是"一套框架多市场"的核心，**也是 v2 消灭 `if market == 'A'` 的手段**。

抽象纪律（三条铁律，ARCH001 强制）：

1. **配置优先于分支**：市场差异尽量表达为"数值不同"（涨跌停 10% vs 无涨跌停）。
2. **`None` 优先于特例**：无涨跌停 = `price_limit_pct: None`，
   而不是写一条 `if market != 'cn_a'`。
3. **极端特例用类路径注入**：实在无法数值化的（如 A 股 ST 涨跌幅判定），
   在 `hooks` 里写 dotted path，由 `importlib` 加载。
   ★ 加载器（`adapters/clock/market_profile_loader.py`）是唯一出现"按市场取配置"的地方，
   且它不在 CI 的 ARCH001 扫描目录内。

**禁止把 MarketProfile 膨胀成"半个策略"**：这里只放"市场规则"，
不放"这个市场该用什么参数赚钱"—— 后者属于 `configs/strategies/`。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Final, Literal

from quant_v2.domain.services.cost_model import compute_cost

if TYPE_CHECKING:  # pragma: no cover - 避免 models.market <-> models.order 运行时循环导入
    from quant_v2.domain.models.order import OrderSide

__all__ = [
    "ONE",
    "ZERO",
    "Availability",
    "CostModel",
    "DataCapabilities",
    "DataSourceSpec",
    "MarketProfile",
    "PriceLimitSpec",
    "TickSpec",
]

ZERO: Final[Decimal] = Decimal("0")
ONE: Final[Decimal] = Decimal("1")

# 财务/退市数据的可得性档位（D-13 / OQ-8）
Availability = Literal["FULL", "PARTIAL", "NONE"]


@dataclass(frozen=True)
class CostModel:
    """交易成本模型 —— 全部数值化，零分支。

    ★ 与 §4.2 的一处偏离：设计稿写的是单个 `tax_rate`，
    这里拆成 `tax_rate_buy` / `tax_rate_sell`。

    理由：一个 `tax_rate` 意味着代码里必须写 `if side == SELL: tax = ... else: 0`
    —— 那是把"哪个方向征税"这条**市场规则**塞进代码。
    两个数字可以直接查表，零分支，且新增"双边征税"市场时只需改 YAML。
    """

    commission_rate: Decimal  # 佣金率（双边）
    commission_min: Decimal  # 最低佣金（元）
    tax_rate_sell: Decimal  # 卖出印花税（A 股 0.0005）
    tax_rate_buy: Decimal  # 买入印花税（A 股 0；港股/美股可能有其他税费）
    transfer_fee_rate: Decimal  # 过户费（沪深 0.00001）
    exchange_fee_rate: Decimal  # 交易所规费
    slippage_bps: int  # 默认滑点基点（10 bps = 0.10%）

    def total_cost(
        self,
        notional: Decimal,
        side: OrderSide,
        *,
        slippage_bps: int | None = None,
    ) -> Decimal:
        """总成本（含滑点）。

        纯计算的数学部分在 `domain/services/cost_model.py`（有对账测试），
        这里只做委托，避免两处各写一份公式。
        """
        return compute_cost(notional, side, self, slippage_bps=slippage_bps).total

    def explicit_cost(self, notional: Decimal, side: OrderSide) -> Decimal:
        """显式成本（佣金 + 税费，不含滑点）—— 用于对账券商账单。"""
        return compute_cost(notional, side, self, slippage_bps=0).explicit_total


@dataclass(frozen=True)
class PriceLimitSpec:
    """涨跌停：**全部数值化**。`None` = 该市场无此约束。

    ★ `None` 优先于特例：美股/港股没有涨跌停，就写 `limit_pct: None`，
    而不是在代码里 `if market != 'cn_a'`。
    """

    limit_pct: Decimal | None = None  # 普通股 ±10%
    st_limit_pct: Decimal | None = None  # ST / *ST ±5%
    new_listing_free_days: int = 0  # 次新股无涨跌幅天数（创业板/科创板 5）
    ipo_first_day_pct: Decimal | None = None

    def pct_for(self, *, is_st: bool) -> Decimal | None:
        """取适用的涨跌幅比例；无涨跌停限制时返回 `None`。"""
        if is_st and self.st_limit_pct is not None:
            return self.st_limit_pct
        return self.limit_pct


@dataclass(frozen=True)
class TickSpec:
    """最小报价单位：固定值 或 分段表。

    分段表格式：`((价格上界, tick), ...)` 升序排列。
    A 股固定 0.01 元；港股的 tick 随价格分段，用表表达即可，无需特例代码。
    """

    tick_size: Decimal | None = None
    tick_table: tuple[tuple[Decimal, Decimal], ...] = ()

    def tick_for(self, price: Decimal) -> Decimal | None:
        """该价格档位对应的最小报价单位；无 tick 约束时返回 `None`。

        ★ 返回 `None` 而不是给一个默认 tick：
        "不知道"和"0.01"是两件事，混在一起会让价格精度问题静默消失。
        """
        if self.tick_table:
            for upper, tick in self.tick_table:
                if price <= upper:
                    return tick
            return self.tick_table[-1][1]
        return self.tick_size

    def round_price(self, price: Decimal) -> Decimal:
        """按最小报价单位取整（四舍五入到最近的 tick）。

        无 tick 约束时原样返回 —— 这不是"兜底"，而是该市场本就允许任意精度报价。
        """
        tick = self.tick_for(price)
        if tick is None:
            return price
        steps = (price / tick).quantize(ONE, rounding=ROUND_HALF_UP)
        return steps * tick


@dataclass(frozen=True)
class DataCapabilities:
    """数据源能力声明。

    ★ 能力必须**如实声明**：v1 的教训是所有适配器都假装自己什么都能给，
    于是"退市股历史数据拿不到"这件事在数据层被吞掉，到回测层才变成一个偏乐观的结论。
    """

    daily_bars: bool = True
    adj_factor: bool = True
    delisting_history: Availability = "NONE"  # ★ OQ-8 关键开关
    delisting_list: bool = False
    trading_calendar: bool = True
    fundamentals: bool = False
    intraday: bool = False
    rate_limit_per_min: int | None = None


@dataclass(frozen=True)
class DataSourceSpec:
    """数据源声明：`source_id` + 适配器 dotted path + 优先级 + 能力。"""

    source_id: str
    # dotted class path，如 'quant_v2.adapters.market_data.akshare_cn.AkshareCnAdapter'
    adapter: str
    priority: int  # 0 = primary
    capabilities: DataCapabilities = field(default_factory=DataCapabilities)


@dataclass(frozen=True)
class MarketProfile:
    """市场的全部差异，集中于此。

    ★ 引擎只读字段，**不做 `if` 判断**。市场差异的三条表达路径（按优先级）：

    1. 数值不同（`limit_pct`、`lot_size`、`tick`）
    2. `None` 表示"无此约束"
    3. `hooks` 注入极端特例的类路径

    `symbol_pattern` 是**正则字符串**而不是已编译对象：
    frozen dataclass 持有编译后的正则会让对象不可比较、不可 repr 得很难看，
    且编译成本在配置加载这种低频路径上可以忽略。
    """

    market_code: str
    display_name: str
    timezone: str  # IANA: 'Asia/Shanghai'
    calendar_id: str  # 交易日历 ID
    currency: str  # 计价币种
    settlement_currency: str | None  # 结算币种（港股 HKD）—— D-12 预留
    lot_size: int  # 最小交易单位（A 股 100）
    odd_lot_allowed: bool
    tick: TickSpec
    price_limit: PriceLimitSpec
    t_plus: int  # 0 / 1（A 股 1）
    shortable: bool
    cost: CostModel
    symbol_pattern: str  # 正则，用于校验与归一化
    half_day_dates: tuple[date, ...]  # 半天市（D-07）
    extra_holidays: tuple[date, ...]  # 临时休市
    fund_availability: Availability  # D-13 财务可得性
    delisting_data_availability: Availability  # ★ OQ-8 关键开关
    max_symbols: int
    data_sources: tuple[DataSourceSpec, ...]
    hooks: Mapping[str, str] = field(default_factory=dict)  # 极端特例的类路径注入

    def __post_init__(self) -> None:
        """构造即校验：正则可编译、关键数值合法。

        ★ 早失败：一个写错的正则如果留到运行时才炸，
        炸的位置会在很远的调用栈里，排查成本极高。
        """
        re.compile(self.symbol_pattern)
        if self.lot_size <= 0:
            raise ValueError(f"lot_size 必须为正，收到 {self.lot_size}")
        if self.t_plus < 0:
            raise ValueError(f"t_plus 不能为负，收到 {self.t_plus}")
        if self.max_symbols <= 0:
            raise ValueError(f"max_symbols 必须为正，收到 {self.max_symbols}")
        if self.cost.slippage_bps < 0:
            raise ValueError(f"slippage_bps 不能为负，收到 {self.cost.slippage_bps}")

    def cost_model(self) -> CostModel:
        """成本模型（供 Sizer / 回测撮合使用）。"""
        return self.cost

    def round_lot(self, quantity: int) -> int:
        """按最小交易单位**向下取整**。

        向下而不是四舍五入：多买一手就可能突破单笔仓位上限，
        宁可少买也不能超风控预算。
        """
        return (quantity // self.lot_size) * self.lot_size

    def matches_symbol(self, symbol: str) -> bool:
        """标的代码是否符合本市场的命名规则。"""
        return re.match(self.symbol_pattern, symbol) is not None

    def is_half_day(self, day: date) -> bool:
        """是否半天市（D-07）。"""
        return day in self.half_day_dates

    def is_extra_holiday(self, day: date) -> bool:
        """是否临时休市。"""
        return day in self.extra_holidays

    def limit_prices(
        self,
        prev_close: Decimal,
        *,
        is_st: bool,
        listing_days: int,
    ) -> tuple[Decimal, Decimal] | None:
        """返回 `(涨停价, 跌停价)`；**无涨跌停限制时返回 `None`**。

        ★ 返回 `None` 而不是 `(+inf, -inf)`：
        `None` 强迫调用方显式处理"无约束"这个情况，而无穷大会静默通过所有比较。

        Args:
            prev_close: 前收盘价。
            is_st: 是否 ST / *ST（用数值字段消费，不进 if 分支）。
            listing_days: 已上市天数（含今日）；次新股无涨跌幅时用得到。
        """
        spec = self.price_limit
        if spec.new_listing_free_days > 0 and listing_days <= spec.new_listing_free_days:
            return None  # 次新股无涨跌幅限制
        pct = spec.pct_for(is_st=is_st)
        if pct is None:
            return None  # 该市场无涨跌停制度
        limit_up = self.tick.round_price(prev_close * (ONE + pct))
        limit_down = self.tick.round_price(prev_close * (ONE - pct))
        return (limit_up, limit_down)

    def primary_source(self) -> DataSourceSpec:
        """优先级最高（数值最小）的数据源。

        ★ 没有配置数据源时抛异常而不是返回 `None`：
        没有数据源的市场根本无法运行，"让它跑起来再说"只会推迟故障。
        """
        if not self.data_sources:
            raise ValueError(
                f"市场 {self.market_code} 未配置任何 data_sources："
                "没有数据源的市场无法取数，请在 configs/markets/ 中补齐"
            )
        return min(self.data_sources, key=lambda spec: spec.priority)
