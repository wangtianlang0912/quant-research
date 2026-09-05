# v1 遗留数据

## var/legacy/v1-klines/

v1 抓取的 615 个港股日线 K 线缓存（原始 JSON，未转换为 v2 的 Bar 契约）。

- **用途**：v1.5 时由 `scripts/migrate_v1_cache.py` 一次性转换为 `var/bars/market=hk/dt=*/bars.parquet`
- **转换时必须打标**：`source='v1_legacy'` + 真实的 `as_of`，明示 provenance。
  没有 provenance 的数据等于没有来源的数据，不能进回测。
- **不入库**：4.8MB 二进制/半结构化缓存属于运行时数据，落在 `var/` 下（全量 gitignore）。

> 原位置是 `data/cache/klines/`。v2 把运行时数据统一收敛到唯一根 `var/`：
> 两个运行时根目录意味着两份要解释、两份要备份、两份会忘记清理。
> 保留 `data/README.txt` 这个指针文件，避免后人再建 `data/` 目录。

## 为什么源码树里不允许出现名为 `data` 的目录

v1 的 `.gitignore` 写了 `data/`（无前导斜杠）。Git 会**递归匹配任意层级的同名目录**，
于是 `src/data/` 整个包被静默忽略 —— 7 个模块从未入库，仓库 clone 下来
`ModuleNotFoundError`，而这个包从未被提交过，所以没人发现。

v2 的三道防线：

1. `.gitignore` 目录规则一律带前导斜杠（`/var/`）
2. 源码树中不存在任何名为 `data` 的目录（`tests/architecture/test_no_data_package.py`）
3. `git ls-files --others` 必须为空（ARCH009，CI 强制）
