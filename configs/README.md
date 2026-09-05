# configs/

**全部配置，全部入库，全部有 schema 校验。**

| 路径 | 作用 |
| --- | --- |
| `markets/cn_a.yaml` | v1 唯一实装的 `MarketProfile` |
| `markets/hk.yaml.template` | 港股注释模板（v1.5 启用） |
| `markets/us.yaml.template` | 美股注释模板（v2.0 启用） |
| `schemas/*.json` | 由 Pydantic 模型导出的数据契约，**不要手改** —— `make schema` 重新生成 |

## 纪律

1. **任何配置改动都要能被 schema 拦住**：加载器用 Pydantic 校验，`ValidationError` 直接抛，
   不允许"字段写错就静默用默认值"。
2. **凭证永不入库**：一律走环境变量；`*.secret.yaml` 与 `runtime.yaml` 已在 `.gitignore`。
3. **schema 与模型必须一致**：CI 会重新导出并 `git diff --exit-code`，漂移即失败
   （`python -m quant_v2.tools.export_schemas --check`）。
4. **`.template` 后缀的文件不参与加载**，也不参与 YAML 语法校验 —— 它们是待填的注释模板，
   本来就不完整。
