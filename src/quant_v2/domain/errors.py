"""领域异常。

设计原则（诊断直接来源）：**所有"取不到就抛"的错误集中在此，禁止静默兜底**。

v1 的三处最惨 P0，本质都是"该抛异常的地方填了个默认值"：

- `basic_risk_manager.py:112-116` 取不到价格 → 用 `Decimal("100")` 兜底 → 风控永远按 100 元估值
- `order_pipeline.py:40` 取不到股数 → 写死 `Decimal("100")` → 每笔都买 100 股
- `NullNotificationAdapter` 吞掉全部发送异常 → 40+ 天没人收到告警

因此本模块的每一条异常都对应一条 CI 静态扫描规则或守卫测试，
**新增异常就必须新增断言，否则等于没加**。
"""

from __future__ import annotations

__all__ = [
    "AdjustmentError",
    "ConfigValidationError",
    "DataQualityGateError",
    "FingerprintError",
    "IllegalTransitionError",
    "InsufficientHistoryError",
    "KillSwitchActiveError",
    "LookaheadViolationError",
    "MarketProfileNotFoundError",
    "NotTradingDayError",
    "NotificationConfigError",
    "PriceUnavailableError",
    "QuantV2Error",
    "SourceUnavailableError",
    "SurvivorshipBiasError",
]


class QuantV2Error(Exception):
    """quant_v2 全部领域异常的基类。

    捕获面建议：只在编排层（`orchestration/`、`ops/`）按具体子类捕获并转成告警；
    领域层与引擎层一律不捕获 —— 让错误在最靠近源头的地方暴露。
    """


class LookaheadViolationError(QuantV2Error):
    """访问了 `as_of` 之后的数据（未来函数）。

    由 `SafeSeries` 抛出。**引擎不得捕获后继续执行**（ARCH012 静态扫描强制）。
    """


class PriceUnavailableError(QuantV2Error):
    """取不到真实价格时抛出。**禁止任何默认值兜底**。

    v1 反例：`basic_risk_manager.py:112-116` 用 `Decimal("100")` 兜底，
    导致风控模块永远按 100 元估值 —— 比崩溃更危险，因为它看起来在正常跑。
    """


class SurvivorshipBiasError(QuantV2Error):
    """用"今天在市的池子"去回测历史时抛出（幸存者偏差硬拦截）。

    对应 OQ-8：退市股历史数据拿不到，此时不是"数据少一点"，
    而是回测结论**系统性偏乐观**，必须中止而不是带病运行。
    """


class InsufficientHistoryError(QuantV2Error):
    """数据长度 < 策略声明的 `required_history_bars`。

    由框架统一校验，策略内部禁止自己写长度校验（v1 的"四道互相矛盾的门槛"就是这样来的）。
    """


class IllegalTransitionError(QuantV2Error):
    """生命周期迁移表中未定义的迁移。**禁止静默通过**。

    v1 没有迁移表，状态靠散落各处的赋值改，于是"信号永远停在 WATCHING"无人知晓。
    """


class NotificationConfigError(QuantV2Error):
    """渠道凭证缺失或无效。

    启动时抛出 → **进程拒绝启动**。禁止 Null / NoOp 适配器（ARCH005 静态扫描）。
    """


class DataQualityGateError(QuantV2Error):
    """数据质量 P0 门禁不通过 → 中止信号生成，**不是警告**。

    v1 实证：覆盖数从 3025 掉到 990 时系统照常推送，用户拿到的是残缺池子的结果。
    """


class KillSwitchActiveError(QuantV2Error):
    """熔断开关处于激活态，禁止新开仓。"""


class ConfigValidationError(QuantV2Error):
    """配置未通过 schema 校验。

    ★ 配置字段写错必须报错，不允许"静默用默认值"——
      默默用默认值的问题在于：你以为配置生效了，其实没有。
    """


class MarketProfileNotFoundError(ConfigValidationError):
    """请求的 market_code 在 `configs/markets/` 下不存在。"""


class NotTradingDayError(QuantV2Error):
    """请求 PIT 快照的 `as_of` 不是交易日（或早于市场开市日）。

    M-19：baostock `query_all_stock(day=)` 在非交易日返回 **0 rows**，
    0 rows ≠ 空池子 —— 必须先过交易日历再查源，否则节假日会被误判成
    空池子并写入脏数据。M-15：A 股快照最早 1990-12-19（上交所开市首日）。
    """


class AdjustmentError(QuantV2Error):
    """复权换算失败：如 adj_factor 序列非法（含 ≤ 0、长度不匹配）。"""


class FingerprintError(QuantV2Error):
    """数据指纹计算失败：如输入行集为空或字段缺失。"""


class SourceUnavailableError(QuantV2Error):
    """数据源连续超时/挂死，当日拉黑（§5.11 / M-14）。

    由 `SubprocessWorker` 在**连续 2 次**子进程超时后抛出；
    编排层捕获后应切换备源并告警 P1，**禁止静默重试或返回空数据** ——
    空数据会顺着管道变成"覆盖暴跌门禁 FAIL"，那已经是灾难的下游了。
    """
