# 2026-07-22 全球资金流向模块

## 功能
7大市场指数归一化到同一走势图（起点=100），自动检测交叉信号。

指数：上证综指 / 恒生 / 日经225 / KOSPI / 新加坡STI / 标普500 / 纳斯达克

数据源：Yahoo Finance，每日缓存 `data/cache/global_indices.json`

## 交叉检测逻辑
- 两条线在最近N天内发生穿越 → 资金跨市场流动
- 跨市场（不同region）→ major 信号
- 同市场内（如标普500 vs 纳斯达克）→ minor 信号

## 首次运行结果 (7/22)
- 7天2次跨市场交叉
- A股→港股 (7/20)
- 美股→新加坡 (7/16)
- 6个月累计：KOSPI +34.3%, 日经 +19.6%, A股 -7.9%

## 文件
- 代码：`src/dashboard/global_flow.py`
- 图表输出：`reports/charts/global_flow_{date}.png`
- 已接入每日16:00 cron（job 80cd494b）
