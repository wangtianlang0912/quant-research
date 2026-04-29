# quant-research

> **量化交易研究与执行项目** — MVP 阶段 · 正在执行  
> 目标：构建从策略研究→回测→纸盘的完整闭环，为实盘决策提供数据支撑。

---

## 项目状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| 基础设施搭建 | 🔄 进行中 | 目录骨架已建立，数据管道待开发 |
| 策略研究与回测 | ⏳ 待启动 | 目标：趋势策略 + 均值回归策略 |
| 纸盘交易 | ⏳ 待启动 | 需完成回测验证后启动 |
| 实盘交易 | 🔒 未开放 | 需满足所有上线门禁后决策 |

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

## 仓库结构

```
quant-research/
├── docs/                                      # 项目执行文档
│   ├── project-plan.md                        # 可执行项目计划书
│   ├── strategy-template.md                   # 策略研究文档模板
│   ├── risk-rules.md                          # 风险控制规则
│   └── release-checklist.md                   # 策略发布检查清单
│
├── src/                                       # 核心源代码（待开发）
│   ├── data/                                  # 数据层
│   ├── strategy/                              # 策略层
│   ├── risk/                                  # 风控层
│   └── execution/                             # 执行层
│
├── configs/                                   # 配置文件
├── research/                                  # 策略研究材料（Notebook 等）
├── tests/                                     # 测试代码
│
├── quant-system-design.md                     # 系统架构设计参考
├── quant-core-principles.md                   # 策略核心本质提炼
├── quantitative-trading-strategies-guide.md   # 策略全体系参考手册
└── README.md                                  # 本文件
```

---

## 研究参考文档

| 文件 | 说明 |
|------|------|
| `quantitative-trading-strategies-guide.md` | 量化策略全体系参考手册（研究用，非执行计划）|
| `quant-core-principles.md` | 各策略核心本质提炼：盈利逻辑、适用场景、关键风险 |
| `quant-system-design.md` | 系统架构设计参考（完整系统愿景，首期按 MVP 实现）|

> ⚠️ 以上研究文档描述的是系统的完整愿景和参考知识体系。  
> 首期 MVP 仅实现其中的核心子集，高级功能（HFT、LLM 因子、大规模分布式等）标注为未来阶段。

---

## 更新日志

- **2026-04-29**：补全项目骨架，添加 `docs/`、`src/`、`configs/`、`research/`、`tests/` 目录结构，重写 README 为可执行项目入口
- **2026-04-23**：初始版本，包含策略核心提炼与系统设计方案
