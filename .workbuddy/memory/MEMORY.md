# quant-research 项目长期记忆

## 代码位置
- **工作区（旧）**: `/Users/leon/WorkBuddy/Claw/quant-research` — 数据缓存停在 2026-09-01
- **GitHub 克隆（新）**: `~/Documents/code/quant-research` — 远端 `git@github.com:wangtianlang0912/quant-research.git`
- 两边是同一项目的不同版本，远端更新（含 `src/dashboard/global_flow.py`、`sector_rotation.py` 等新模块）

## GitHub 访问
- 本机 **无 SSH 密钥**（`~/.ssh/` 只有 known_hosts），`git@github.com` 走不通
- 仓库是公开的，改用 HTTPS：`git clone https://github.com/wangtianlang0912/quant-research.git`
- 如需推送：`ssh-keygen -t ed25519` 后添加到 GitHub

## 运行可视化面板
```bash
cd ~/Documents/code/quant-research
/Users/leon/.workbuddy/binaries/python/envs/default/bin/python -m visualization.app
# 访问 http://localhost:8899
```
依赖（已装在 managed venv）：fastapi、uvicorn、jinja2、akshare、pandas、numpy、matplotlib
容器 Python 用 `/Users/leon/.workbuddy/binaries/python/envs/default/bin/python`（隔离环境，别用系统 python）

## 重要陷阱：src/data 曾被 gitignore 吞掉
- `.gitignore` 原写 `data/`（无前导斜杠）→ 匹配**任意层级**的 data 目录 → `src/data/`（数据适配层源码）从未入库
- 已修复为 `/data/`（仅忽略根目录行情数据）
- 影响：`src.data.akshare_client` 缺失导致 10 个模块 import 失败、3 个 API 500
- 该文件已按调用方接口重建（见下）

## 腾讯行情接口规范（实测 2026-09-05，易踩坑）
**报价** `http://qt.gtimg.cn/q=sh688256,hkHSI`（GBK 编码，`v_代码="字段~字段~..."`）
- 通用: [1]名称 [2]代码 [3]现价 [4]昨收 [5]今开 [6]成交量
- [30]时间 [31]涨跌 [32]涨跌% [33]最高 [34]最低 [37]成交额 [38]换手率 [39]PE [44]流通市值(亿) [45]总市值(亿) [46]PB
- **港股与 A 股索引完全一致**（无偏移，别被网上资料误导）
- **成交额单位不统一**：A股/港股指数 = 万元，港股个股 = 元 → 需在代码里换算

**K线** `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh688256,day,,,320,qfq`
- 必须 **HTTPS**（HTTP 返回 302）
- 字段顺序是 `[日期, 开, 收, 高, 低, 量]` —— **O-C-H-L，不是 OHLC**
- A股取 `data[code]['qfqday']`（前复权）；港股/指数只有 `data[code]['day']`
- 单请求上限 640 根

## StockQuote.code 约定
- A 股返回裸代码 `688256`（`ai_heat` 剥离 sh/sz 前缀后查 map）
- 港股保留 `hkHSI`（`asia_chart` 用它映射中文名）
- 两边都有 fallback，不可随意更改

## 已知非阻断问题
- `/api/symbols` 返回空数组：`data/1d/` 无 CSV（该目录被 gitignore，需自行放置行情数据）→ 前端 K 线图表区无数据
