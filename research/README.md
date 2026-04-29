# research/ — 策略研究目录

本目录存放策略研究过程中产生的所有研究材料，包括 Jupyter Notebook、回测报告、数据分析等。

---

## 目录结构约定

每个策略独立一个子目录，命名格式：`<策略ID>/`

```
research/
├── STR-20260429-001/          # 策略 ID（见 strategy-template.md 封面信息）
│   ├── README.md              # 策略简介（名称、假设、当前状态）
│   ├── exploration.ipynb      # 数据探索 Notebook
│   ├── backtest.ipynb         # 回测 Notebook
│   ├── report.html            # 回测报告（由 Notebook 导出）
│   └── data_spec.md           # 数据规格说明
└── shared/                    # 跨策略共享的工具和分析
    ├── data_quality_check.ipynb
    └── market_regime.ipynb
```

---

## Notebook 管理规范

- **命名规则**：`<用途>_<日期>.ipynb`，如 `backtest_20260501.ipynb`
- **每个 Notebook 顶部**必须包含：策略 ID、作者、目的描述
- **提交前**：清除所有 Output（`Cell → All Output → Clear`），避免大文件
- **最终结果**：导出为 HTML 报告存入同目录，Notebook 本身仅保留代码

---

## 研究产出物归档规则

| 产出物 | 存放位置 | 格式 |
|--------|---------|------|
| 策略研究文档 | `docs/` 按模板填写 | Markdown |
| 回测 Notebook | `research/<策略ID>/` | .ipynb |
| 回测报告 | `research/<策略ID>/report.html` | HTML |
| 数据探索图表 | `research/<策略ID>/charts/` | PNG / SVG |

---

## 注意事项

- 研究目录中**不存放真实账户数据或含敏感信息的文件**
- 大数据文件（> 10MB）不提交到 Git，使用 `.gitignore` 排除
- 研究中使用的原始数据缓存存放在项目外部，不提交到 Git
