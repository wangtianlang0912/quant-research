# src/ — 核心源代码目录

本目录包含量化交易研究与执行系统的核心 Python 模块。

---

## 模块划分与边界

```
src/
├── __init__.py          # 包入口
├── data/                # 数据层：数据接入、清洗、存储
├── strategy/            # 策略层：信号生成、因子计算
├── risk/                # 风控层：风控规则执行引擎
├── execution/           # 执行层：下单、成交回报、对账
└── utils/               # 工具层：日志、配置加载、通用工具
```

---

## 各模块职责边界

### `data/` — 数据层

**职责**：
- 历史行情数据获取（Tushare / AKShare）
- 数据清洗、复权处理
- 数据质量检查
- 本地数据存储与缓存

**对外接口**：
- `get_daily(symbol, start, end)` → 日线数据
- `get_minute(symbol, start, end)` → 分钟线数据

**边界**：数据层不做任何交易决策逻辑。

---

### `strategy/` — 策略层

**职责**：
- 信号计算（基于 `data/` 提供的数据）
- 因子计算
- 目标仓位生成

**对外接口**：
- `generate_signals(data) → signals`
- `compute_target_positions(signals, portfolio) → positions`

**边界**：策略层不直接调用下单接口，不做风控判断。

---

### `risk/` — 风控层

**职责**：
- 按 `docs/risk-rules.md` 执行所有风控规则
- 交易前仓位检查
- 持仓中止损/止盈监控
- 回撤熔断

**对外接口**：
- `pre_trade_check(order) → (approved: bool, reason: str)`
- `check_portfolio(portfolio) → risk_actions`

**边界**：风控层是独立防线，不依赖策略层逻辑。

---

### `execution/` — 执行层

**职责**：
- 委托下单（纸盘模拟 / 实盘 API）
- 成交回报处理
- 对账

**对外接口**：
- `place_order(order) → order_id`
- `get_positions() → portfolio`

**边界**：执行层在下单前必须调用风控层检查。

---

### `utils/` — 工具层

**职责**：日志配置、配置文件加载、时间工具、告警通知

---

## 开发规范

- 所有公共函数必须有 docstring
- 关键逻辑必须有单元测试，覆盖率目标 ≥ 80%
- 模块间通过接口通信，避免跨层直接调用
- 禁止在代码中硬编码 API Key 或密码，使用 `configs/` 配置
