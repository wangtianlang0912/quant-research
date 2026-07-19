# 突破策略扫描规约

## 两阶段扫描流程

### Phase 1: 动量初筛（轻量，~4s）
- 批量拉取全市场实时行情（4689只有效，新浪API，800只/批）
- 基于已缓存的日K线计算半年涨幅
- 取涨幅Top 2% → 约30-90只进入深扫池
- 同时过滤：30天内有交易 + 非ST + 价格>0

### Phase 2: 形态深扫（计算密集，每只~0.5s）
- 对动量池内每只调用 `is_breakout_signal()`
- 6维评分：前段涨幅/回调幅度/MA企稳/HigherLow/ATR收窄/放量确认
- 阈值 28分 = 严格入场信号
- 行业去重：同行业只保留最高分一只

## 数据缓存
| 文件 | 内容 | 更新频率 |
|------|------|---------|
| `data/cache/a_codes.json` | 全市场5052只代码 | 每周 |
| `data/cache/all_quotes.json` | 全市场实时行情 | 每日扫描前 |
| `data/cache/klines_{code}.json` | 个股日K线(600根) | 每日更新 |
| `data/cache/momentum_top.json` | 动量Top2%代码 | 每日扫描前 |
| `data/cache/breakout_watchlist.json` | 监控清单 | 持续 |
