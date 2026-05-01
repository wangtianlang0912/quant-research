# quant-research

> **量化交易研究与执行项目** — MVP 阶段 · 正在执行  
> 目标：构建从策略研究→回测→纸盘的完整闭环，为实盘决策提供数据支撑。

---

## 项目状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| 基础设施搭建 | ✅ 基本完成 | 目录骨架、报告输出、市场数据抽象已具备 |
| 策略研究与回测 | ✅ 基本完成 | 已具备趋势、均值回归、OOS、压力测试、稳健性分析、组合回测 |
| 纸盘交易 | 🔄 进行中 | 已具备纸盘日志、月度报告、对齐分析 |
| 实盘交易 | 🔒 未开放 | 需完成真实券商执行、外部数据源稳定性和实盘门禁 |

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

## 当前已实现能力

- 本地 CSV 日线 / 分钟线数据读取（`1d` / `1m` / `5m` / `15m` / `30m` / `60m`）
- AKShare 外部数据源最小接入（支持日线 / 分钟线取数的适配器实现）
- 趋势跟随与均值回归策略
- 回测报告、OOS 报告、压力测试、稳健性分析、组合回测报告
- 纸盘净值日志、持仓日志、阶段绩效报告、月度报告、纸盘/回测对齐分析
- CLI 支持指定回测频率与数据源

---

## 回测使用示例

### 本地 CSV 日线回测

```bash
python -m src.app.cli backtest \
  --data-path ./data \
  --symbol 000300.SH
```

### 本地 CSV 分钟线回测

```bash
python -m src.app.cli backtest \
  --data-path ./data \
  --symbol 000300.SH \
  --frequency 5m
```

### AKShare 数据源回测

```bash
python -m src.app.cli backtest \
  --data-path ./data \
  --symbol 600519 \
  --market-data-source akshare \
  --frequency 1d
```

> 说明：AKShare 适配器依赖本地安装 `akshare`。如需启用，请先安装相应依赖。

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

## 更新日志

- **2026-05-01**：真实接入 AKShare 适配器最小实现；新增可指定 `frequency` 与 `market_data_source` 的回测入口；补充 CLI 与 README 使用说明
- **2026-04-30**：完善 `docs/risk-rules.md` 的代码映射说明；新增外部数据源适配器骨架；补全分钟线本地数据读取说明
- **2026-04-29**：补全项目骨架，添加 `docs/`、`src/`、`configs/`、`research/`、`tests/` 目录结构，重写 README 为可执行项目入口
- **2026-04-23**：初始版本，包含策略核心提炼与系统设计方案
