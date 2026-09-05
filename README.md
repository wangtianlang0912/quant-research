# quant_research_v2

**个人级可解释投研助手** —— 不是机构级量化平台。

目标用户是**股市小白**。因此有两条一等需求，高于一切技术指标：

1. **每条推荐都能讲清楚**：六个解释区块（一句话结论 / 为什么买 / 打分明细 / 行动计划 / 风险 / 现在怎么样）任一缺失，门禁直接拒绝该信号。
2. **推荐出去的票有始有终**：每条信号都有显式生命周期状态机，8 个业务终态、3 个终止节点，**禁止"其他"兜底**。孤儿信号每日巡检。

---

## 快速开始

```bash
git checkout v2
uv sync --frozen          # 依赖安装（与 CI 同款）
make check                # 等价于 CI 全量门禁：lint + format + type + arch + test
./scripts/smoke_e2e.sh    # 一键端到端冒烟（推荐首次 clone 后跑）
```

常用命令：

| 命令 | 作用 |
| --- | --- |
| `make help` | 列出全部 target |
| `make test` | 跑全部测试 |
| `make coverage` | 覆盖率双阈值（整体 ≥60%、核心域 ≥85%） |
| `make arch` | 架构静态扫描 `ARCH001~013` |
| `make schema` | 重新导出 `configs/schemas/*.json` |

---

## 目录速查

```
configs/            全部配置，全部入库，全部有 schema 校验
  markets/          MarketProfile（cn_a 已实装；hk/us 为注释模板）
  schemas/          Pydantic 导出的 JSON Schema（D-01 落盘）
src/quant_v2/
  domain/           纯领域层：零外部依赖，只依赖标准库 + pydantic
    models/         不可变数据契约（Bar / Instrument / Signal / Order / ...）
    ports/          全部外部能力的 Protocol 定义（无 ABC）
    services/       纯计算：复权 / 成本 / 指纹 / 生命周期迁移表
    guard/          SafeSeries —— 未来函数守卫
    errors.py       全部领域异常，禁止静默兜底
  indicators/       向量化指标库（单一实现 + golden 测试）
  adapters/         唯一允许碰外部世界的层
  engines/ strategies/ factors/   （T02~T04 填充）
tools/arch_lint/    自研 AST 静态扫描（ARCH001~013）
tests/
  architecture/     架构守卫测试 —— 不可协商的不变量
  regression/       v1 实证缺陷的回归测试，删除即 CI 失败
  doubles/          各 Protocol 的测试替身
var/                ★ 运行时数据根，全量 gitignore，永不入库
docs/archive/       v1 历史报告与笔记（纯存档，不可复现）
```

---

## 三条不可协商的架构铁律

它们都不是"靠自觉"，而是由 `make arch` 与 `pytest tests/architecture` 机械强制：

1. **领域层零外部依赖** —— `domain/` 不得 import `adapters/`、`pandas`、`requests`、任何 SDK（`ARCH010`/`ARCH011`）。
2. **引擎代码里零市场分支** —— 不允许 `if market == 'A'`。市场差异全部表达为 `MarketProfile` 的数值字段；实在数值化不了的用 `hooks` 注入类路径，且只允许在 `adapters/clock/market_profile_loader.py` 出现"按市场取配置"（`ARCH001`）。
3. **全程 Decimal** —— 金额/价格计算不得出现 float。浮点只允许出现在绘图与统计展示层（`ARCH013`）。

---

## 能力边界（诚实清单）

**v2 已做到（T01 完成时）**

- 三市场统一的 `Bar` 契约，价格恒为 RAW + `adj_factor`，三种复权视图由 `BarPanel.to_view()` 换算（**含 10 送 10 除权 golden 用例**）
- `SafeSeries` 未来函数守卫：越界访问必抛 `LookaheadViolationError`
- 生命周期状态机：显式迁移表 + 导入时自校验
- 向量化指标库：MA / EMA / MACD / Wilder RSI / Wilder ATR / Donchian，全部有 golden 测试
- `MarketProfile` 加载器 + `cn_a.yaml`；合成市场可零改动加载
- 数据指纹（sha256，改一行必变）、A 股成本模型
- 自研 AST 静态扫描 `ARCH001~013` + 架构守卫测试

**当前明确不做**

- 无实盘下单（`OrderIntent` 只是"建议订单"，永不发送；纸盘排 v2.0）
- 无参数寻优、无组合优化（回测只做单策略 + 修正版样本外验证）
- 无前端页面（T05）
- 无港股/美股实装（仅注释模板）
- 无复盘报告前端页（v1 只推送，落 `var/reports/weekly/*.md`）

**v1 数据的可信度警告**

`docs/archive/v1-reports/` 下的 v1 历史报告**不可复现** —— v1 没有 `run_manifest`，无法回溯当次运行的 git sha、数据指纹与配置哈希。它们是"当时发生过什么"的记录，不是可验证的业绩。

---

## 关于 v1

v1 代码库经完整评审发现 **27 个 P0 / 34 个 P1 / 22 个 P2** 缺陷，已推倒重来。
v1 完整存档在分支 `archive/v1-20260905`（已推送远端），任何被删除的文件都可以这样取回：

```bash
git show archive/v1-20260905:<path>
git log --all -- <path>
```

v1 的 615 个港股 K 线缓存已迁至 `var/legacy/v1-klines/`（留待 v1.5 迁移脚本处理，不入库）。
