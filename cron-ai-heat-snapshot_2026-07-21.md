# AI热度每日快照 - 定时任务

**任务ID**: 9d703055-a995-48c8-8313-428f72d516e9
**创建时间**: 2026-07-21 19:34 GMT+8
**目标**: 每个交易日（周一至五）15:05 自动调用 `/api/ai-heat` 存储历史快照
**方式**: isolated agentTurn，curl 调用本地 API，静默无推送
**数据**: 存入 `quant-research/data/ai_heat_history.json`，保留最近60天

**相关改动**:
- `app.py`: 每次调用 `/api/ai-heat` 时自动追加当天快照到历史文件（去重）
- `app.py`: 新增 `/api/ai-heat-history` 返回最近60天趋势数据
- `dashboard.html`: AI热度卡片改为左趋势图 + 右今日快照布局
