# quant-research

> **量化交易研究与执行项目** — MVP 阶段 · 正在执行  
> 目标：构建从策略研究→回测→纸盘的完整闭环，为实盘决策提供数据支撑。

---

## 项目状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| 基础设施搭建 | ✅ 基本完成 | 目录骨架、报告输出、市场数据抽象已具备 |
| 策略研究与回测 | ✅ 基本完成 | 已具备趋势、均值回归、OOS、压力测试、稳健性分析、组合回测；支持日线与分钟线频率 |
| 纸盘交易 | 🔄 进行中 | 已具备纸盘日志、月度报告、对齐分析 |
| 实盘交易 | 🔒 未开放 | 需完成实盘门禁与经纪商对接 |

---

## MVP 边界

**首期聚焦**：
- A 股日线/分钟线策略
- 1–2 个策略：趋势跟随 + 均值回归
- 完整回测（含手续费、滑点）→ 样本外验证 → 纸盘 ≥ 3 个月

**首期明确排除**：
- 高频交易 / Tick 级策略
- LLM 驱动全自动交易
- 期权、期货、加密货币执行闭环
- K8s 微服务化大规模部署

---

## 推荐阅读顺序

如果你是第一次接触本项目，按以下顺序阅读：

1. **[docs/project-plan.md](docs/project-plan.md)** — 项目执行计划（目标、里程碑、验收标准）
2. **[docs/risk-rules.md](docs/risk-rules.md)** — 风险控制规则（所有策略必须遵守）
3. **[docs/strategy-template.md](docs/strategy-template.md)** — 策略研究文档模板
4. **[quant-system-design.md](quant-system-design.md)** — 系统架构设计参考
5. **[quant-core-principles.md](quant-core-principles.md)** — 策略核心本质提炼
6. **[quantitative-trading-strategies-guide.md](quantitative-trading-strategies-guide.md)** — 策略全体系参考手册

---

## 当前已实现能力

- 本地 CSV 日线 / 分钟线数据读取（`1d` / `1m` / `5m` / `15m` / `30m` / `60m`）
- 趋势跟随与均值回归策略
- 回测报告、OOS 报告、压力测试、稳健性分析、组合回测报告
- **分钟线回测入口**：可通过 CLI 或 API 指定频率（`1m` / `5m` / `15m` / `30m` / `60m`）运行回测
- 纸盘净值日志、持仓日志、阶段绩效报告、月度报告、纸盘/回测对齐分析
- **AKShare 真实数据适配器**：支持日线与分钟线拉取、实时报价、A 股交易日历
- `TushareAdapter`（骨架，待接入真实 token）

---

## AKShare 外部数据源配置

[AKShare](https://github.com/akfamily/akshare) 是一个开源的 A 股数据库，**大多数接口无需 token**，可直接使用。

### 安装依赖

```bash
pip install akshare
```

### 环境变量（可选）

| 变量名 | 说明 |
|--------|------|
| `AKSHARE_TOKEN` | AKShare API token（大多数接口无需设置；如需要，在此传入） |

```bash
export AKSHARE_TOKEN=your_token_here  # 可选
```

### 代码使用示例

```python
from src.adapters.market_data import AkshareAdapter
from src.domain.enums import Frequency, AdjustType
from datetime import datetime

adapter = AkshareAdapter()  # token 自动从 AKSHARE_TOKEN 环境变量读取

# 获取日线 K 线
bars = adapter.get_bars(
    symbol="000300",          # 或 "000300.SH"，自动剥离交易所后缀
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 31),
    frequency=Frequency.DAY_1,
    adjust_type=AdjustType.QFQ,  # 前复权
)

# 获取 5 分钟线
bars_5m = adapter.get_bars(
    symbol="000300",
    start=datetime(2024, 1, 2, 9, 30),
    end=datetime(2024, 1, 2, 11, 30),
    frequency=Frequency.MIN_5,
)

# 获取最新实时报价
quote = adapter.get_latest_quote("000300")

# 获取 A 股交易日历
from datetime import date
trading_days = adapter.list_trading_days(date(2024, 1, 1), date(2024, 12, 31))
```

### 错误处理

| 场景 | 行为 |
|------|------|
| `akshare` 未安装 | 抛出 `DataError`，提示执行 `pip install akshare` |
| API 请求失败（网络超时等） | 抛出 `DataError`，包含原始错误信息 |
| 返回空数据 | `get_bars` 返回空列表；`get_latest_bar` / `get_latest_quote` 返回 `None` |
| 交易日历接口失败 | 自动回退到工作日近似 |

---

## 分钟线回测

### CLI 使用

```bash
# 日线回测（默认）
python -m src.app.cli backtest \
  --data-path /path/to/data \
  --symbol 000300.SH \
  --strategy trend_following

# 1 分钟线回测
python -m src.app.cli backtest \
  --data-path /path/to/data \
  --symbol 000300.SH \
  --frequency 1m \
  --strategy trend_following

# 5 分钟线回测
python -m src.app.cli backtest \
  --data-path /path/to/data \
  --symbol 000300.SH \
  --frequency 5m

# 支持的频率：1d（默认）/ 1m / 5m / 15m / 30m / 60m
```

### Python API

```python
from src.app.backtest_app import run_backtest, run_minute_backtest
from src.domain.enums import Frequency

# 日线回测
summary = run_backtest(
    data_path="/path/to/data",
    symbol="000300.SH",
    strategy_name="trend_following",
)

# 分钟线回测（推荐使用 run_minute_backtest）
summary = run_minute_backtest(
    data_path="/path/to/data",
    symbol="000300.SH",
    strategy_name="trend_following",
    frequency="5m",   # 1m / 5m / 15m / 30m / 60m
)

# 也可以通过 run_backtest 的 frequency 参数直接指定
summary = run_backtest(
    data_path="/path/to/data",
    symbol="000300.SH",
    frequency=Frequency.MIN_15,
)
```

### 本地分钟线数据目录结构

```text
data/
└── 1m/           # 或 5m / 15m / 30m / 60m
    └── 000300.SH.csv
```

CSV 格式与日线一致：

```csv
timestamp,open,high,low,close,volume,amount
2024-01-02T09:31:00,10.0,10.1,9.9,10.05,500,5025
2024-01-02T09:32:00,10.05,10.2,10.0,10.15,600,6090
```

### 回测报告

分钟线回测报告与日线格式一致，输出到 `reports/backtest/`，报告中包含：

- `context.frequency`：记录本次回测使用的频率（如 `"5m"`）
- `context.metadata.frequency`：同样记录频率字段，方便检索

---

## 仓库结构

```text
quant-research/
├── docs/
├── src/
│   ├── adapters/
│   │   └── market_data/
│   │       ├── akshare_adapter.py   # AKShare 真实实现
│   │       ├── tushare_adapter.py   # Tushare 骨架（待接入）
│   │       └── local_csv_adapter.py # 本地 CSV 适配器
│   ├── app/
│   │   ├── backtest_app.py          # run_backtest / run_minute_backtest
│   │   └── cli.py                   # CLI 入口（支持 --frequency）
│   ├── domain/
│   ├── engines/
│   ├── orchestrators/
│   ├── services/
│   └── strategies/
├── configs/
├── research/
├── tests/
│   ├── test_akshare_adapter.py      # AKShare 适配器测试
│   ├── test_minute_backtest.py      # 分钟线回测入口测试
│   └── ...
├── quant-system-design.md
├── quant-core-principles.md
├── quantitative-trading-strategies-guide.md
└── README.md
```

---

## 更新日志

- **2026-05-01**：实现 `AkshareAdapter` 真实 API 对接（日线、分钟线、实时报价、交易日历）；新增 `run_minute_backtest` 分钟线回测入口；CLI 支持 `--frequency` 和 `--strategy` 参数；修复 `paper_app.py` 中 `Decimal` 未导入的 bug
- **2026-04-30**：完善 `docs/risk-rules.md` 的代码映射说明；新增外部数据源适配器骨架；补全分钟线本地数据读取说明
- **2026-04-29**：补全项目骨架，添加 `docs/`、`src/`、`configs/`、`research/`、`tests/` 目录结构，重写 README 为可执行项目入口
- **2026-04-23**：初始版本，包含策略核心提炼与系统设计方案

