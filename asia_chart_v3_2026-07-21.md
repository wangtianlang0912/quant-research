# 亚太走势图 v3 — 折线图

## 时间
2026-07-21 15:27

## 任务
Boss 发现日韩新指数线不完整 → 根因是缓存只有 6/18 起的数据 → 补 4-5 月历史点位

## 变更
- `src/dashboard/asia_chart.py` — 柱状图 → 折线图，同轴叠加 A 股 + 日经 + KOSPI + STI
- `data/cache/asia_indices.json` — 补日经(58k→66k)、KOSPI(5.8k→6.7k)、STI(4.9k→5.5k) 三个市场的 4-7 月点位
- x 轴用数字索引避免 datetime/date 混用导致的 matplotlib 类型冲突

## 结果
7 条归一化折线（A 股 4 + 日经 + KOSPI + STI），底部标注恒生/科技今日涨跌。已接入 16:00 cron。
