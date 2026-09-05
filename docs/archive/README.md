# v1 存档（纯存档，不进运行时）

| 目录 | 内容 | 说明 |
| --- | --- | --- |
| `v1-reports/` | v1 每日推送/追踪/复盘报告、扫描与回测 JSON、v1 设计笔记 | **不可复现**：v1 没有 `run_manifest`，无法回溯 git sha / 数据指纹 / 配置哈希 |
| `v1-notes/` | v1 期的量化方法论参考资料（外部资料与草稿） | 仅供参考，非 v2 的设计依据 |

v2 的设计依据只有三份文档：

- `00-diagnosis.md` —— v1 缺陷诊断（27 P0 / 34 P1 / 22 P2）
- `01-PRD.md` —— 产品需求
- `docs/architecture/02-architecture.md` —— 架构设计

v1 任何被删除的代码都可从 `archive/v1-20260905` 分支取回：

```bash
git show archive/v1-20260905:<path>
```
