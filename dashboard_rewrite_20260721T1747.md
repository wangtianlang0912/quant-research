# Dashboard.html 重写完成

## 修改内容

### 1. 策略 Tab 从 2 个扩展到 6 个
- 左侧策略选择卡片从 `tabs` 样式改为 2 行 × 3 列的 `strategy-grid` 网格布局
- 新增 4 个策略：布林带、MACD+RSI、VWAP、唐奇安通道
- `STRATEGY_SCHEMA` 扩展了所有 6 个策略的完整参数定义（与后端一致）
- `PRESETS` 为每个策略添加了快速预设
- `scanGrid` 补全了所有策略的参数扫描网格
- 历史回测记录表的策略标签支持所有 6 种策略的颜色映射 (`STRATEGY_TAGS`)
- 策略名称映射统一到 `STRATEGY_LABELS`

### 2. AI 热度仪表盘
- 新卡片插入到主内容区 K 线图下方
- JS 中新增 `loadAIHeat()`  → `fetchJSON('/api/ai-heat')` → `renderAIHeat(data)`
- 显示：综合热度分数（大数字，颜色按分数分级）、等级、进度条、板块热力图（5 个细分板块各行带涨跌幅条形图）、一句话题结论、策略建议
- 样式：`ai-heat-*` 前缀 CSS 类，暗色主题一致

### 3. 荐股日历 → 万年历月视图
- 原列表式日历移除，替换为月视图日历
- 顶部月份导航（◀ 2026年7月 ▶）
- 7 列网格（日一二三四五六）
- 每个格子显示日期数字 + 荐股数量徽章
- 当天高亮
- 点击某天在下方展开详情列表
- JS 状态：`calYear`、`calMonth`、`selectedCalDate`、`picksByDate`
- 核心函数：`loadPicksCalendar()`、`renderMonthCalendar()`、`selectCalendarDay()`、`updatePicksDetail()`

### 保持不变的约束
- `:root` CSS 变量不变
- `renderKline` 函数完全不变
- 回测运行逻辑不变
- sidebar + main 布局结构不变
- 中文编码正常
