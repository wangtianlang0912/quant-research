# 量化交易策略系统说明书

> **整理日期**：2026-04-23
> **研究范围**：2019-2026 年主流量化策略与最新研究进展
> **适用范围**：A股、港股、美股、期货、加密货币、期权

---

## 目录

1. [量化交易基础框架](#一-量化交易基础框架)
2. [趋势跟踪策略](#二-趋势跟踪策略)
3. [均值回归策略](#三-均值回归策略)
4. [统计套利策略](#四-统计套利策略)
5. [做市商策略](#五-做市商策略)
6. [多因子策略](#六-多因子策略)
7. [机器学习与深度学习策略](#七-机器学习与深度学习策略)
8. [LLM 与大模型量化策略](#八-llm-与大模型量化策略)
9. [高频交易与市场微观结构](#九-高频交易与市场微观结构)
10. [期权与波动率策略](#十-期权与波动率策略)
11. [加密货币量化策略](#十一-加密货币量化策略)
12. [风险管理框架](#十二-风险管理框架)
13. [回测方法论](#十三-回测方法论)
14. [组合优化与执行](#十四-组合优化与执行)
15. [策略开发checklist](#十五-策略开发checklist)

---

## 一、量化交易基础框架

### 1.1 量化交易定义

量化交易（Quantitative Trading）是一种利用**数学模型、统计分析和自动化执行**来识别和利用市场机会的系统性投资方法。与主观交易不同，量化交易将交易决策转化为可重复验证的算法逻辑。

**核心优势**：
- 纪律性强，消除情绪干扰
- 可回溯验证，可系统性评估
- 并行处理多资产、多市场
- 可规模化执行

### 1.2 量化交易流程

```
数据获取 → 因子/信号构建 → 策略研究 → 回测验证 → 风险建模
    ↓                                         ↓
执行下单 ←←←←←←←←←←←←←←←←←←←←←←←← 组合优化 ← 头寸管理
```

### 1.3 市场环境识别

| 市场状态 | 特征 | 适用策略 |
|---------|------|---------|
| 趋势型 | 波动率聚集、动量持续 | 趋势跟踪、动量 |
| 震荡型 | 价格围绕均值波动 | 均值回归、套利 |
| 高波动型 | 波动率急剧上升 | 波动率交易、CTA |
| 低流动性型 | 买卖价差扩大 | 减少交易、套利 |

**Regime Detection 方法**：
- 滚动波动率窗口检测（10/20/60日）
- Hidden Markov Model（HMM）状态识别
- VIX / 恐慌指数监控
- 宏观因子切换检测

---

## 二、趋势跟踪策略

### 2.1 核心理念

**趋势跟踪（Trend Following）** 的核心假设：资产价格一旦形成趋势，会持续一段时间。策略在趋势启动时入场，在趋势反转时出场。

**学术支撑**：Moskowitz et al. (2012) 提出的 **Time Series Momentum (TSMOM)** 证明了动量效应在期货市场的普遍存在性。

### 2.2 趋势识别指标

| 指标 | 公式/原理 | 参数 | 适用场景 |
|------|---------|------|---------|
| **简单移动平均 (SMA)** | N日均价 | 10/20/50/200 | 长周期趋势 |
| **指数移动平均 (EMA)** | 指数加权均价 | 12/26 (MACD) | 中短周期 |
| **布林带 (Bollinger Bands)** | 均线±2倍标准差 | 20,2 | 趋势确认+突破 |
| **ATR (Average True Range)** | 真范围均值 | 14 | 波动率调整 |
| **ADX (Average Directional Index)** | 趋势强度 | 14 | 过滤假突破 |
| **Donchian Channel** | N日最高/最低价 | 20/55 | 趋势突破信号 |

### 2.3 趋势策略类型

#### 2.3.1 趋势线交叉策略

```python
# Python 示例：双均线趋势策略
import pandas as pd
import numpy as np

def trend_strategy(prices: pd.Series, short_window: int = 20, long_window: int = 50):
    """
    双均线交叉策略
    - 短期均线上穿长期均线 → 做多
    - 短期均线下穿长期均线 → 做空/平仓
    """
    signals = pd.Series(0, index=prices.index)
    sma_short = prices.rolling(short_window).mean()
    sma_long = prices.rolling(long_window).mean()

    signals[short_window:] = np.where(
        sma_short[short_window:] > sma_long[short_window:], 1, -1
    )
    # 去除初始信号的虚假交叉
    signals = signals.replace(signals.shift(1))
    return signals
```

#### 2.3.2 布林带突破策略

```python
def bollinger_breakout(prices: pd.Series, window: int = 20, num_std: float = 2.0):
    """
    布林带突破策略
    - 价格上穿上轨 → 做多
    - 价格下穿下轨 → 做空
    """
    sma = prices.rolling(window).mean()
    std = prices.rolling(window).std()
    upper_band = sma + num_std * std
    lower_band = sma - num_std * std

    signals = pd.Series(0, index=prices.index)
    signals[prices > upper_band] = 1   # 做多
    signals[prices < lower_band] = -1  # 做空
    return signals, upper_band, lower_band
```

#### 2.3.3 ATR 波动率止损

```python
def atr_trailing_stop(prices: pd.Series, high: pd.Series, low: pd.Series,
                       period: int = 14, multiplier: float = 3.0):
    """
    ATR 追踪止损策略
    使用 ATR 作为波动率调整后的止损距离
    """
    tr = pd.concat([
        high - low,
        (high - prices.shift()).abs(),
        (low - prices.shift()).abs()
    ], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()

    # 计算追踪止损线
    trailing_stop = prices - multiplier * atr
    stop_line = trailing_stop.expanding().max() * 0.95  # 上行保护

    return atr, stop_line
```

### 2.4 趋势策略参数

| 参数类型 | 常见设置 | 说明 |
|---------|---------|------|
| 入场周期 | 5/10/20 日 | 短期信号更灵敏但假信号多 |
| 出场周期 | 50/100/200 日 | 长周期过滤噪声 |
| 持仓周期 | 1天 - 数月 | 根据品种波动率调整 |
| 止损幅度 | 1-3 倍 ATR | 波动率自适应 |
| 仓位计算 | Risk Parity | 每笔交易承担等额风险 |

### 2.5 CTA 策略（商品交易顾问）

CTA 基金主要策略为趋势跟踪，典型持仓周期 **1天-3个月**：

| 要素 | 说明 |
|------|------|
| 品种覆盖 | 期货、期权、外汇、债券、加密货币 |
| 信号来源 | 价格趋势、期限结构、波动率 |
| 风险管理 | 分散化、止损、仓位控制 |
| 典型收益 | 年化 5-15%（趋势行情）|
| 典型回撤 | 20-40%（趋势失效时）|

**来源**：BarclayHedge CTA 指数；IASG Trend Following Index；Sepp & Lukman (2025) "The Science and Practice of Trend-following Systems"

---

## 三、均值回归策略

### 3.1 核心理念

**均值回归（Mean Reversion）** 的核心假设：价格偏离基本面（均值）后，会向均值回归。适用于震荡市场。

### 3.2 经典均值回归策略

#### 3.2.1 布封带策略（Bollinger Band Mean Reversion）

```python
def bollinger_mean_reversion(prices: pd.Series, window: int = 20, num_std: float = 2.0,
                              exit_threshold: float = 0.5):
    """
    布林带均值回归策略
    - 价格触及下轨 → 预期回归 → 做多
    - 价格触及上轨 → 预期回归 → 做空
    - 价格回归至均线附近 → 平仓
    """
    sma = prices.rolling(window).mean()
    std = prices.rolling(window).std()
    upper_band = sma + num_std * std
    lower_band = sma - num_std * std

    signals = pd.Series(0, index=prices.index)
    position = 0

    for i in range(window, len(prices)):
        if prices.iloc[i] <= lower_band.iloc[i] and position == 0:
            signals.iloc[i] = 1   # 入场做多
            position = 1
        elif prices.iloc[i] >= upper_band.iloc[i] and position == 0:
            signals.iloc[i] = -1  # 入场做空
            position = -1
        elif position != 0 and abs(prices.iloc[i] - sma.iloc[i]) < exit_threshold * std.iloc[i]:
            signals.iloc[i] = 0   # 回归均线，平仓
            position = 0

    return signals
```

#### 3.2.2 行业轮动均值回归

```python
def sector_mean_reversion(sector_returns: pd.DataFrame, lookback: int = 20,
                           z_threshold: float = 1.5, holding_days: int = 5):
    """
    行业轮动均值回归策略
    - 做多近期表现最差的行业（负alpha回归）
    - 做空近期表现最好的行业
    """
    # 计算行业动量
    momentum = sector_returns.rolling(lookback).sum()

    # Z-Score 标准化
    z_score = (momentum - momentum.mean(axis=1).values.reshape(-1, 1)) / momentum.std(axis=1).values.reshape(-1, 1)

    signals = pd.DataFrame(0, index=momentum.index, columns=momentum.columns)

    # Z-Score 超过阈值时反向操作
    for col in momentum.columns:
        signals.loc[z_score[col] < -z_threshold, col] = 1   # 做多低估（跌太多）
        signals.loc[z_score[col] > z_threshold, col] = -1  # 做空高估（涨太多）

    return signals
```

### 3.3 均值回归关键参数

| 参数 | 说明 | 建议 |
|------|------|------|
| 回望期 (lookback) | 计算均值的窗口 | 10-60 日，依据波动率调整 |
| 标准化阈值 | Z-Score 入场阈值 | 1.5-2.5 |
| 波动率调整 | 用 ATR 或历史波动率归一化 | 防止高波动期假信号 |
| 持仓时间 | 避免无限持仓 | 设置最大持仓期 |

### 3.4 适用与不适用场景

| ✅ 适合 | ❌ 不适合 |
|--------|---------|
| 区间震荡行情 | 强趋势行情（均值回归失效）|
| 高股息股票 | 趋势跟踪强的品种（国债、黄金）|
| 期权隐含波动率高估 | 市场情绪极端驱动时 |
| 跨交易所价差 | 流动性极差的市场 |

---

## 四、统计套利策略

### 4.1 核心理念

**统计套利（Statistical Arbitrage）** 利用资产之间的**价格关系偏离**进行交易，期望价差回归均值。核心是构建一个均值回归的价差组合。

### 4.2 配对交易（Pairs Trading）

```python
def pairs_trading(stock1: pd.Series, stock2: pd.Series, lookback: int = 60,
                   entry_threshold: float = 2.0, exit_threshold: float = 0.5):
    """
    配对交易策略
    基于协整关系构建配对
    - 当 spread 超过历史均值 2 倍标准差 → 价差收窄预期 → 卖空 S1 买多 S2
    - 当 spread 低于历史均值 2 倍标准差 → 价差扩大预期 → 买多 S1 卖空 S2
    """
    # 计算价差（对数价格差分）
    spread = np.log(stock1) - np.log(stock2)

    # 滚动均值和标准差
    mean = spread.rolling(lookback).mean()
    std = spread.rolling(lookback).std()

    # Z-Score
    z_score = (spread - mean) / std

    signals = pd.Series(0, index=spread.index)

    # 入场信号
    signals[z_score > entry_threshold] = -1   # spread 过高 → 做空 spread
    signals[z_score < -entry_threshold] = 1   # spread 过低 → 做多 spread

    # 平仓信号
    signals[z_score.abs() < exit_threshold] = 0

    return signals, z_score, mean, std
```

### 4.3 协整检验

```python
from statsmodels.tsa.stattools import coint, adfuller

def find_cointegrated_pairs(prices_df: pd.DataFrame, significance: float = 0.05):
    """
    寻找协整资产对
    使用 Engle-Granger 两步法和 ADF 检验
    """
    n = prices_df.shape[1]
    pairs = []

    for i in range(n):
        for j in range(i + 1, n):
            stock1 = prices_df.iloc[:, i]
            stock2 = prices_df.iloc[:, j]

            # 协整检验
            score, pvalue, _ = coint(stock1, stock2)

            if pvalue < significance:
                # ADF 检验残差的平稳性
                spread = stock1 - stock2
                adf_result = adfuller(spread)
                if adf_result[1] < significance:
                    pairs.append({
                        'stock1': prices_df.columns[i],
                        'stock2': prices_df.columns[j],
                        'pvalue': pvalue,
                        'adf_pvalue': adf_result[1]
                    })

    return pd.DataFrame(pairs)
```

### 4.4 多因子统计套利

| 因子类型 | 说明 | 套利逻辑 |
|---------|------|---------|
| **行业动量** | 同行业股票动量分化 | 做多动量最强 + 做空动量最弱 |
| **价值因子** | PE/PB/PS 偏离行业均值 | 做多低估 + 做空高估 |
| **分析师预期** | 盈利预测调整分歧 | 预期修正带来回归 |
| **期限结构** | 期货升贴水偏离 | 基差回归收益 |

**来源**：ArXiv 2403.12180 "Advanced Statistical Arbitrage with Reinforcement Learning"；MDPI Finance 2024 "Mean-Reverting Statistical Arbitrage Strategies"

---

## 五、做市商策略

### 5.1 核心理念

**做市商（Market Making）** 通过同时提供**买入报价（bid）和卖出报价（ask）**，赚取买卖价差（spread）。策略的核心是**存货管理与订单簿预测**。

### 5.2 订单簿建模

```python
def order_book_predictor(mid_prices: pd.Series, order_flow: pd.Series,
                          depth_levels: int = 5):
    """
    基于订单流预测短期价格变动
    - 买入压力（正向订单流）→ 价格短期上涨
    - 卖出压力（负向订单流）→ 价格短期下跌
    """
    # 订单流累积
    cumulative_flow = order_flow.rolling(20).sum()

    # 订单流与价格动量结合
    signal = cumulative_flow * mid_prices.pct_change().rolling(10).sum()

    return signal
```

### 5.3 价差设定模型

```python
def optimal_spread(inventory: float, volatility: float, risk_aversion: float = 1e-6,
                   lambda_bid: float = 0.3, lambda_ask: float = 0.3):
    """
    GCL (Glosten-Milgrom) 模型的最优价差
    价差 = 2 * (风险溢价 + 信息成本)

    参数：
    - inventory: 当前存货（正=多头，负=空头）
    - volatility: 资产波动率
    - risk_aversion: 风险厌恶系数
    - lambda_bid/ask: 订单到达率
    """
    # 基本价差（覆盖库存成本）
    inventory_component = 2 * risk_aversion * abs(inventory) * volatility**2

    # 信息不对称成本
    adverse_selection = 2 * (1 / lambda_bid + 1 / lambda_ask)

    # 最优 bid-ask 价差
    optimal_spread = np.sqrt(inventory_component + adverse_selection)

    return optimal_spread
```

### 5.4 做市商风险管理

| 风险类型 | 控制方法 |
|---------|---------|
| **存货风险** | 设置最大持仓限额；delta 对冲 |
| **逆向选择** | 根据订单流调整价差；信号驱动 |
| **价格极端波动** | 波动率放大时扩大价差或暂停报价 |
| **串场风险** | 多交易所间对冲 |

---

## 六、多因子策略

### 6.1 核心理念

**多因子模型（Multi-Factor Model）** 假设资产收益率由多个可量化的**风险因子**驱动。策略通过因子暴露构建组合，获取因子风险溢价。

### 6.2 经典因子

| 因子类别 | 具体因子 | 因子逻辑 |
|---------|---------|---------|
| **价值因子** | PE、PB、PCF、PS | 低估值股票长期跑赢 |
| **动量因子** | 1月/3月/12月收益率 | 趋势持续性 |
| **质量因子** | ROE、ROA、毛利率、资产负债率 | 高质量公司溢价 |
| **规模因子** | 市值（log） | 小盘股溢价 |
| **波动率因子** | 历史波动率、特雷诺波动率 | 低波动异象 |
| **利差因子** | 期限利差、信用利差 | 固收联动 |
| **情绪因子** | 分析师评级、机构持仓变化 | 市场情绪 |

### 6.3 Barra 多因子模型

```python
def barra_risk_model(factor_exposures: pd.DataFrame, factor_returns: pd.DataFrame,
                      specific_returns: pd.Series, market_cap: pd.Series):
    """
    Barra 风险模型简化版
    r = X * f + s + ε
    其中：
    - X: 因子暴露矩阵
    - f: 因子收益率
    - s: 特异性收益（残差）
    - ε: 随机误差
    """
    # 市值加权计算因子收益率
    weights = market_cap / market_cap.sum()

    # 因子收益率 = X' * W * r / var(X'WX)
    # ...
    return factor_returns

def construct_factor_portfolio(factor_data: pd.DataFrame, factor: str,
                                top_pct: float = 0.2, bottom_pct: float = 0.2):
    """
    构建因子组合
    - 做多因子暴露最高的 top_pct 股票
    - 做空因子暴露最低的 bottom_pct 股票
    """
    # 按因子值排序
    ranked = factor_data[factor].rank(ascending=False)
    n = len(ranked)

    signals = pd.Series(0, index=factor_data.index)
    signals[ranked <= n * top_pct] = 1      # 做多
    signals[ranked >= n * (1 - bottom_pct)] = -1  # 做空

    return signals
```

### 6.4 因子正交化与合成

```python
from sklearn.decomposition import PCA
from sklearn.linear_model import LinearRegression

def orthogonalize_factors(factor_matrix: pd.DataFrame, n_components: int = None):
    """
    PCA 正交化因子
    去除因子间共线性，提高因子有效性
    """
    # 标准化
    factor_std = (factor_matrix - factor_matrix.mean()) / factor_matrix.std()

    # PCA 降维
    pca = PCA(n_components=n_components)
    orthogonal_factors = pca.fit_transform(factor_std)

    return pd.DataFrame(orthogonal_factors,
                        index=factor_matrix.index,
                        columns=[f'PC{i+1}' for i in range(orthogonal_factors.shape[1])])
```

### 6.5 因子有效性评估指标

| 指标 | 计算 | 有效性判断 |
|------|------|---------|
| **IC (Information Coefficient)** | Spearman 相关系数（因子值 vs 下期收益）| IC > 0.03 持续为有效 |
| **IR (Information Ratio)** | IC均值 / IC标准差 | IR > 0.5 为高效因子 |
| **分组回测** | 按因子值分组，看各组收益差 | 多空组合收益显著 |
| **衰减分析** | IC 随持仓周期的变化 | IC 在哪一天开始衰减 |

---

## 七、机器学习与深度学习策略

### 7.1 机器学习流程

```
原始数据 → 特征工程 → 标签定义 → 模型训练 → 信号生成 → 组合优化 → 执行
```

### 7.2 特征工程

| 特征类型 | 示例 | 构建方法 |
|---------|------|---------|
| 价格类 | 收益率、波动率、动量 | OHLCV 数据计算 |
| 技术类 | RSI、MACD、布林带、KDJ | 技术指标公式 |
| 基本面类 | PE、PB、ROE、增长率 | 财务数据 |
| 宏观类 | 利率、汇率、CPI、PMI | 宏观数据 |
| 文本类 | 研报情感、新闻情绪 | NLP 提取 |
| 关系类 | 相关性、协整关系、图网络 | 关系建模 |

### 7.3 主要模型架构

#### 7.3.1 LSTM（长短期记忆网络）

```python
import torch
import torch.nn as nn

class LSTMModel(nn.Module):
    def __init__(self, input_size: int, hidden_size: int, num_layers: int, output_size: int):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_size, output_size)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        # x shape: (batch, seq_len, input_size)
        lstm_out, _ = self.lstm(x)
        # 取最后一个时间步
        out = self.fc(lstm_out[:, -1, :])
        return self.sigmoid(out)
```

**适用场景**：时序价格预测、波动率预测、多步未来收益预测

#### 7.3.2 CNN（卷积神经网络）

```python
class CNN1DModel(nn.Module):
    def __init__(self, input_size: int, num_filters: int = 64, kernel_size: int = 3):
        super().__init__()
        self.conv1 = nn.Conv1d(input_size, num_filters, kernel_size, padding=kernel_size//2)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.fc = nn.Linear(num_filters, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        # x shape: (batch, seq_len, input_size) → (batch, input_size, seq_len)
        x = x.permute(0, 2, 1)
        x = torch.relu(self.conv1(x))
        x = self.pool(x).squeeze(-1)
        return self.sigmoid(self.fc(x))
```

**适用场景**：技术指标图谱识别、价格模式识别、订单流分析

#### 7.3.3 Transformer

```python
class TransformerModel(nn.Module):
    def __init__(self, input_size: int, d_model: int = 128, nhead: int = 8,
                 num_layers: int = 4, dim_feedforward: int = 512):
        super().__init__()
        self.input_proj = nn.Linear(input_size, d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=dim_feedforward,
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.fc = nn.Linear(d_model, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        x = self.input_proj(x)
        x = self.transformer(x)
        x = self.fc(x[:, -1, :])  # 取最后一个时间步
        return self.sigmoid(x)
```

**适用场景**：多因子时序建模、跨资产关系建模、长期依赖关系捕捉

#### 7.3.4 强化学习（RL）

```python
class DQNAgent:
    def __init__(self, state_size: int, action_size: int, epsilon: float = 1.0,
                 epsilon_decay: float = 0.995, epsilon_min: float = 0.01,
                 gamma: float = 0.95, lr: float = 0.001):
        self.state_size = state_size
        self.action_size = action_size
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.epsilon_min = epsilon_min
        self.gamma = gamma
        self.memory = ReplayBuffer(capacity=10000)
        self.model = self._build_model()

    def act(self, state):
        if np.random.rand() <= self.epsilon:
            return np.random.randint(self.action_size)
        q_values = self.model.predict(state)
        return np.argmax(q_values[0])

    def replay(self, batch_size: int = 32):
        minibatch = self.memory.sample(batch_size)
        for state, action, reward, next_state, done in minibatch:
            target = reward
            if not done:
                target = reward + self.gamma * np.amax(self.model.predict(next_state)[0])
            target_f = self.model.predict(state)
            target_f[0][action] = target
            self.model.fit(state, target_f, epochs=1, verbose=0)
```

**适用场景**：动态仓位优化、交易执行优化、组合权重调整

**来源**：ArXiv 2403.12180 "Advanced Statistical Arbitrage with Reinforcement Learning"；ScienceDirect 2025 "Deep learning for algorithmic trading: A systematic review"

### 7.4 标签定义方法

| 标签类型 | 定义方法 | 适用场景 |
|---------|---------|---------|
| **回归标签** | T+N 日收益率 | 趋势跟踪 |
| **分类标签** | 涨跌二分类（>阈值=1, else=0）| 机器学习分类 |
| **排序标签** | 未来收益排名百分位 | 多空组合 |
| **信号标签** | 买入/持有/卖出 | 强化学习 |

---

## 八、LLM 与大模型量化策略

### 8.1 LLM 在量化中的应用方向

| 应用方向 | 具体任务 | 技术方法 |
|---------|---------|---------|
| **因子挖掘** | 从文本/研报中自动提取另类因子 | NLP + 微调 LLM |
| **情感分析** | 新闻/社交媒体情感打分 | 微调 BERT/ChatGPT |
| **策略生成** | 自动生成交易策略代码 | Code LLM + 强化学习 |
| **多 Agent 交易** | 多个 LLM Agent 协作决策 | Multi-Agent System |
| **自然语言查询** | 用自然语言查询市场数据 | RAG + LLM |

### 8.2 多 Agent 框架（TradingAgents）

**TradingAgents-CN** 是一个基于多智能体大语言模型的开源金融交易决策框架：

```
┌─────────────────────────────────────────┐
│  LLM Router（路由 Agent）                │
│  - 理解用户意图                          │
│  - 分发任务到专业 Agent                   │
└──────────┬──────────────────────────────┘
           │
    ┌──────┴──────┐
    ▼             ▼
┌────────┐   ┌──────────┐
│ 研究   │   │ 风控     │
│ Agent  │   │ Agent    │
└───┬────┘   └────┬─────┘
    │             │
    ▼             ▼
┌────────┐   ┌──────────┐
│ 执行   │   │ 监控     │
│ Agent  │   │ Agent    │
└────────┘   └──────────┘
```

**来源**：laosu.tech 2025 "TradingAgents-CN"；ArXiv 2409.06289 "Automate Strategy Finding with LLM"

### 8.3 文本因子构建

```python
def build_sentiment_factor(news_texts: list, model_name: str = "chinese-sentiment"):
    """
    从新闻文本构建情感因子
    - 使用微调 BERT 模型进行情感打分
    - 结合发布时间加权（近远期权重衰减）
    """
    from transformers import pipeline

    classifier = pipeline("sentiment-analysis", model=model_name)

    scores = []
    weights = []

    for i, text in enumerate(news_texts):
        score = classifier(text)[0]
        # 转换为 [-1, 1] 范围
        sentiment = score['score'] if score['label'] == 'POSITIVE' else -score['score']
        scores.append(sentiment)
        weights.append(1 / (i + 1))  # 近期权重高

    # 加权平均
    weighted_score = np.average(scores, weights=weights)
    return weighted_score
```

### 8.4 策略自动发现框架

```python
def llm_strategy_discovery(market_data: dict, constraints: dict) -> list:
    """
    基于 LLM 的策略自动发现
    三阶段框架：
    1. 想法生成（LLM 根据市场特征提出策略方向）
    2. 初步回测（快速验证想法有效性）
    3. 风险感知评估（综合评估夏普比、最大回撤）
    """
    prompt = f"""
    Given the following market data characteristics:
    - Volatility: {market_data['volatility']}
    - Trend strength: {market_data['trend_strength']}
    - Market regime: {market_data['regime']}

    Generate 5 quantitative trading strategy ideas that would work well
    in this market environment. For each strategy provide:
    1. Strategy name and type
    2. Key indicators/parameters
    3. Expected behavior in current regime
    4. Risk considerations
    """
    # 使用 LLM 生成策略
    response = llm.generate(prompt)
    # 解析并返回策略列表
    return parse_strategies(response)
```

**来源**：ArXiv 2409.06289 "Automate Strategy Finding with LLM in Quant Investment" (2025)

---

## 九、高频交易与市场微观结构

### 9.1 市场微观结构基础

| 概念 | 说明 |
|------|------|
| **限价订单簿 (LOB)** | 所有未成交限价订单的集合，按价格排序 |
| **最佳买价 (Bid)** | 买方愿意接受的最高价格 |
| **最佳卖价 (Ask)** | 卖方愿意接受的最低价格 |
| **买卖价差 (Bid-Ask Spread)** | Ask - Bid，流动性成本 |
| **市场深度** | 各价格档位的挂单量 |
| **冲击成本** | 大单成交对价格的即时影响 |
| **延迟** | 订单到达交易所的时间 |

### 9.2 订单簿预测

```python
def predict_mid_price_change(order_book: dict, model: nn.Module,
                               window: int = 20):
    """
    基于深度学习的订单簿价格预测
    使用 LSTM 对订单流不平衡进行建模

    Order Book 特征：
    - 订单流不平衡 (OFI) = BidVol - AskVol（各档位加权）
    - 成交量累积
    - 订单簿深度变化
    - 订单到达率
    """
    # 构建 OFI 特征
    ofi_features = []
    for level in range(window):
        bid_vol = order_book['bids'][level]['volume']
        ask_vol = order_book['asks'][level]['volume']
        ofi = bid_vol - ask_vol
        ofi_features.append(ofi)

    # 滚动计算 OFI 累积量
    cumulative_ofi = np.cumsum(ofi_features)

    # 预测价格方向（上涨/下跌/持平）
    prediction = model.predict(cumulative_ofi.reshape(1, -1, 1))
    return prediction
```

**来源**：ArXiv 2403.09267 "Deep Limit Order Book Forecasting" (2024)

### 9.3 算法执行策略

#### 9.3.1 VWAP（成交量加权平均价格）

```python
def vwap_execution(target_shares: int, expected_volume: pd.Series,
                    prices: pd.Series, alpha: float = 0.5):
    """
    VWAP 执行算法
    目标：以接近当天市场 VWAP 的价格完成交易

    参数：
    - target_shares: 目标交易量
    - expected_volume: 分时预期成交量
    - prices: 分时价格
    - alpha:  aggressiveness (0=完全被动, 1=完全主动)
    """
    # 计算分时 VWAP 份额
    volume_share = expected_volume / expected_volume.sum()

    # 基础 VWAP 量
    base_quantity = volume_share * target_shares

    # 根据 alpha 调整（alpha 大 → 早点成交）
    t = np.arange(len(prices)) / len(prices)  # 时间进度 0→1
    urgency = t ** (2 * alpha - 1)  # alpha > 0.5 越晚越急迫

    schedule = base_quantity * (1 + urgency)

    # 生成执行信号
    execution_prices = prices * (1 + 0.0001)  # 假设小幅滑点
    notional = (schedule * execution_prices).sum()

    return schedule, notional
```

#### 9.3.2 TWAP（时间加权平均价格）

```python
def twap_execution(target_shares: int, num_periods: int):
    """
    TWAP 执行算法
    将交易量均匀分配到每个时间段
    """
    shares_per_period = target_shares / num_periods
    return np.full(num_periods, shares_per_period)
```

#### 9.3.3 IS（Implementation Shortfall）

```python
def implementation_shortfall(target_shares: int, prices: pd.Series,
                              volatility: float, urgency: float = 0.5):
    """
    Implementation Shortfall 策略
    在冲击成本和等待风险之间寻找最优执行路径

    urgency: 0(不急) → 1(非常急)
    - urgency 高 → 快速执行，接受更高冲击成本
    - urgency 低 → 慢慢执行，承受更多时序风险
    """
    # IS 优化问题的解析解
    # 最优执行比例随时间指数衰减
    T = len(prices)
    t = np.arange(T) / T

    decay_rate = 2 * urgency  # urgency 越高，衰减越快
    execution_fraction = (1 - np.exp(-decay_rate * (1 - t))) / (1 - np.exp(-decay_rate))

    # 归一化
    execution_fraction = execution_fraction / execution_fraction.sum()
    schedule = target_shares * execution_fraction

    return schedule
```

### 9.4 高频策略类型

| 策略类型 | 频率 | 收益来源 | 风险 |
|---------|------|---------|------|
| **做市商** | 微秒-毫秒 | 买卖价差 | 逆向选择、存货 |
| **统计套利** | 秒-分钟 | 价格偏离回归 | 流动性枯竭 |
| **盘口交易** | 毫秒 | 订单簿不平衡 | 延迟风险 |
| **事件驱动** | 秒-分钟 | 信息到达后反应 | 方向性风险 |

**来源**：Oxford Market Microstructure Lecture Notes 2024；CMU Market Microstructure Course

---

## 十、期权与波动率策略

### 10.1 波动率曲面

| 维度 | 说明 |
|------|------|
| **Strike（行权价）** | 平值期权（ATM）波动率最低，价外/价内期权波动率偏高（波动率微笑） |
| **期限（Expiry）** | 短期期权波动率变化更剧烈（期限结构） |
| **波动率曲面** | 波动率随 Strike 和 Expiry 变化的三维曲面 |

### 10.2 波动率交易策略

#### 10.2.1 Vega 对冲策略

```python
def vega_hedge(option_portfolio: dict, current_iv: float, predicted_iv: float):
    """
    计算期权组合的 Vega 并进行对冲
    - 当预测波动率上升 → 持有正 Vega 头寸（买入期权）
    - 当预测波动率下降 → 持有负 Vega 头寸（卖出期权）
    """
    total_vega = 0
    for position in option_portfolio:
        # Black-Scholes Vega
        from scipy.stats import norm
        S, K, T, r = position['S'], position['K'], position['T'], position['r']
        d1 = (np.log(S/K) + (r + 0.5*current_iv**2)*T) / (current_iv*np.sqrt(T))

        vega = S * norm.pdf(d1) * np.sqrt(T) * 0.01  # 标准化的 Vega（每1%波动率变化）
        total_vega += position['size'] * vega

    # 预测的波动率变化（以百分比表示）
    iv_change = (predicted_iv - current_iv) / current_iv

    # 预期盈亏
    expected_pnl = total_vega * iv_change * 100

    return expected_pnl, total_vega
```

#### 10.2.2 波动率均值回归策略

```python
def vol_mean_reversion(iv_surface: pd.DataFrame, hv_20d: pd.Series,
                        entry_threshold: float = 0.2):
    """
    隐含波动率 vs 历史波动率的均值回归策略
    - IV > HV + 阈值 → 波动率被高估 → 卖出期权（做空波动率）
    - IV < HV - 阈值 → 波动率被低估 → 买入期权（做多波动率）
    """
    signals = pd.Series(0, index=iv_surface.index)

    for date in iv_surface.index:
        atm_iv = iv_surface.loc[date, 'ATM_IV']  # 平值期权隐含波动率
        hv = hv_20d.loc[date]                     # 20日历史波动率

        iv_hv_ratio = atm_iv / hv - 1

        if iv_hv_ratio > entry_threshold:
            signals.loc[date] = -1  # 隐含波动率高估 → 卖空波动率
        elif iv_hv_ratio < -entry_threshold:
            signals.loc[date] = 1   # 隐含波动率低估 → 买入波动率

    return signals
```

### 10.3 波动率曲面预测（深度学习）

```python
def predict_volatility_surface(iv_data: np.ndarray, model_type: str = "transformer"):
    """
    基于 Transformer 的波动率曲面预测
    输入：历史的波动率曲面（strike × expiry × time）
    输出：预测的未来波动率曲面
    """
    if model_type == "transformer":
        # 使用 Transformer 编码器捕捉曲面内的时间依赖
        model = TransformerModel(input_size=iv_data.shape[1])
    elif model_type == "lstm":
        model = LSTMModel(input_size=iv_data.shape[1], hidden_size=64,
                          num_layers=2, output_size=iv_data.shape[1])

    predicted_iv = model.predict(iv_data)
    return predicted_iv
```

**来源**：ArXiv 2509.05911 "Deep Learning Option Pricing with Market Implied Volatility"；Wiley 2025 "Option Implied Volatility and Trading Strategies Based on Neural Networks"

---

## 十一、加密货币量化策略

### 11.1 加密货币市场特征

| 特征 | 说明 | 量化含义 |
|------|------|---------|
| 7×24 小时交易 | 无休市 | 可持续运行策略 |
| 高波动 | BTC 日波动率可达 5-10% | 趋势/套利机会多 |
| 交易所分散 | 全球 300+ 交易所 | 跨所套利空间 |
| 监管差异 | 各地区规则不同 | 事件驱动机会 |
| DEX/DeFi | 去中心化交易所 | 无需 KYC 的套利 |

### 11.2 跨交易所套利

```python
def cross_exchange_arbitrage(tickers: dict, withdrawal_fee: dict,
                               min_spread: float = 0.005):
    """
    三角/跨交易所套利
    - 交易所 A 价格 < 交易所 B 价格 → 跨所价差策略
    - 扣除提币手续费后仍有收益则执行
    """
    results = []

    for exchange_pair, (price_a, price_b) in tickers.items():
        ex_a, ex_b = exchange_pair

        gross_spread = (price_b - price_a) / price_a

        # 净收益（扣除手续费）
        net_spread = gross_spread - withdrawal_fee[ex_a] - withdrawal_fee[ex_b]

        if net_spread > min_spread:
            results.append({
                'exchange_a': ex_a,
                'exchange_b': ex_b,
                'gross_spread': gross_spread,
                'net_spread': net_spread,
                'action': f'Buy {ex_a} @ {price_a}, Sell {ex_b} @ {price_b}',
                'signal': 1 if price_a < price_b else -1
            })

    return pd.DataFrame(results)
```

### 11.3 加密货币统计套利

```python
def crypto_stat_arb(prices: pd.DataFrame, lookback: int = 30,
                    z_entry: float = 2.0, z_exit: float = 0.5):
    """
    加密货币统计套利（均值回归）
    - 利用币种间协整关系
    - 典型配对：BTC/ETH, BTC/SOL, ETH/SOL
    """
    # 计算对数价格差（spread）
    spread = np.log(prices.iloc[:, 0]) - np.log(prices.iloc[:, 1])

    mean = spread.rolling(lookback).mean()
    std = spread.rolling(lookback).std()
    z = (spread - mean) / std

    signals = pd.Series(0, index=spread.index)
    signals[z < -z_entry] = 1    # spread 过低 → 买入币种1，卖出币种2
    signals[z > z_entry] = -1     # spread 过高 → 卖出币种1，买入币种2
    signals[z.abs() < z_exit] = 0  # 回归，平仓

    return signals
```

### 11.4 DeFi 套利策略

| 策略类型 | 说明 | 典型收益 |
|---------|------|---------|
| **三角套利** | 同一交易所内 A→B→C→A 循环交易 | 0.1-0.5% 每轮 |
| **跨DEX套利** | DEX A 价格 < DEX B 价格，低买高卖 | 0.5-2% |
| **Flash Loan** | 无抵押借贷 + 套利 + 还款，单笔完成 | 取决于价差 |
| **流动性挖矿** | 提供流动性赚取交易手续费+奖励 | 年化 10-100%+ |

**来源**：ScienceDirect 2024 "Arbitrage opportunities and efficiency tests in crypto derivatives"；CoinAPI 2024 "Crypto Arbitrage Strategy: 3 Core Statistical Approaches"

---

## 十二、风险管理框架

### 12.1 风险指标体系

| 指标 | 公式 | 含义 | 控制目标 |
|------|------|------|---------|
| **VaR (Value at Risk)** | P(Loss > VaR) = α | 一定置信度下的最大损失 | VaR < 2% 日度 |
| **CVaR / ES** | E[Loss \| Loss > VaR] | 超额损失的平均值 | CVaR < 3× VaR |
| **夏普比率 (Sharpe)** | (Rp - Rf) / σp | 风险调整后收益 | > 1.5 |
| **索提诺比率 (Sortino)** | (Rp - Rf) / σ_down | 仅考虑下行波动 | > 1.0 |
| **Calmar 比率** | 年化收益 / 最大回撤 | 回撤调整后收益 | > 1.0 |
| **最大回撤 (Max Drawdown)** | max(HWM - P)/HWM | 历史最大跌幅 | < 20% |
| **日间波动率** | σ_daily | 日收益标准差 | < 2% |
| **持仓集中度** | max(wi) | 最大单资产权重 | < 10% |

### 12.2 风险预算模型

```python
def risk_parity(allocation: np.ndarray, covariance: np.ndarray,
                 target_vol: float = 0.10):
    """
    风险平价（Risk Parity）算法
    每个资产对组合总风险的贡献相等

    原理：wi * (Σw)_i / w'Σw = 1/n
    """
    inv_variance = 1 / np.diag(covariance)
    raw_weights = inv_variance / inv_variance.sum()

    # 调整至目标波动率
    portfolio_vol = np.sqrt(raw_weights @ covariance @ raw_weights)
    scaled_weights = raw_weights * (target_vol / portfolio_vol)

    return scaled_weights / scaled_weights.sum()
```

### 12.3 仓位规模管理

```python
def calculate_position_size(account_balance: float, entry_price: float,
                            stop_loss_pct: float, risk_per_trade: float = 0.02):
    """
    基于固定风险比例的仓位计算

    公式：Position Size = (Account * Risk%) / Stop Loss Amount

    参数：
    - account_balance: 账户余额
    - entry_price: 入场价格
    - stop_loss_pct: 止损比例（%）
    - risk_per_trade: 每笔交易风险比例（默认 2%）
    """
    risk_amount = account_balance * risk_per_trade
    stop_loss_amount = entry_price * stop_loss_pct

    # 合约/股数
    position_size = risk_amount / stop_loss_amount

    return {
        'position_size': position_size,
        'risk_amount': risk_amount,
        'max_loss': position_size * stop_loss_amount,
        'notional_value': position_size * entry_price
    }
```

### 12.4 风险控制矩阵

| 风险类型 | 监控指标 | 预警阈值 | 处理措施 |
|---------|---------|---------|---------|
| **市场风险** | VaR、波动率 | VaR > 2% | 减仓、平掉高风险头寸 |
| **流动性风险** | 买卖价差、日成交量 | 价差 > 1% | 降低仓位、分散流动性 |
| **杠杆风险** | 杠杆倍数、保证金率 | 保证金 < 20% | 自动减仓、追加保证金 |
| **集中度风险** | 单资产权重 | max_w > 15% | 再平衡、降低集中度 |
| **尾部风险** | CVaR、最大回撤 | DD > 15% | 启用尾部对冲（期权） |

---

## 十三、回测方法论

### 13.1 回测流程

```
历史数据 → 数据清洗 → 策略逻辑实现 → 信号生成 → 模拟执行
    ↓                                            ↓
结果分析 ←←←←←←←←←←←←←←←←←←←←← 绩效指标计算（收益/回撤/夏普）
```

### 13.2 常见偏差与解决方案

| 偏差类型 | 描述 | 解决方案 |
|---------|------|---------|
| **前视偏差** | 使用了未来数据 | 严格使用上一时刻信息 |
| **生存者偏差** | 只用当前存在的数据 | 使用完整历史（含退市） |
| **时机偏差** | 信号发出但无法成交 | 加入滑点和延迟 |
| **数据窥视偏差** | 过度调参导致虚假过拟合 | Walk-forward、独立样本外测试 |
| **流动性偏差** | 大资金无法以回测价格成交 | 量价结合、滑点建模 |

### 13.3 Walk-Forward 分析

```python
def walk_forward_analysis(prices: pd.Series, params: dict,
                           train_window: int = 252, test_window: int = 63,
                           rebalance_freq: int = 21):
    """
    Walk-Forward 分析（滚动窗口回测）
    - 训练窗口（in-sample）：优化参数
    - 测试窗口（out-of-sample）：评估泛化能力

    参数：
    - train_window: 训练窗口（天数）
    - test_window: 测试窗口（天数）
    - rebalance_freq: 再平衡频率
    """
    results = []

    total_len = len(prices)
    n_windows = (total_len - train_window) // test_window

    for i in range(n_windows):
        train_end = train_window + i * test_window
        test_start = train_end
        test_end = min(test_start + test_window, total_len)

        # 训练数据
        train_data = prices.iloc[train_end - train_window:train_end]

        # 在训练集上优化参数（简化示例：固定参数）
        optimal_params = params  # 实际应用中在训练集上寻优

        # 在测试集上评估
        test_data = prices.iloc[test_start:test_end]
        signals = apply_strategy(test_data, optimal_params)
        returns = signals.shift(1) * test_data.pct_change()

        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        max_dd = (returns.cumsum() - returns.cumsum().cummax()).min()

        results.append({
            'train_start': train_end - train_window,
            'train_end': train_end,
            'test_start': test_start,
            'test_end': test_end,
            'sharpe': sharpe,
            'max_drawdown': max_dd,
            'params': optimal_params
        })

    return pd.DataFrame(results)
```

### 13.4 过拟合检测

| 方法 | 说明 | 判定标准 |
|------|------|---------|
| **Walk-Forward** | 滚动训练/测试窗口 | 测试集 Sharpe 显著低于训练集则过拟合 |
| **N 折交叉验证** | 时序 N 折 | 各折结果一致性高 |
| **保外样本测试** | 用完全独立的数据验证 | 性能大幅下降则过拟合 |
| **最小 Description Length** | 模型复杂度惩罚 | 参数量大且性能无显著提升则过拟合 |
| **仿真随机策略** | 将策略与随机信号对比 | 策略无显著优势则无效 |

### 13.5 交易成本建模

```python
def realistic_backtest(signals: pd.Series, prices: pd.Series,
                       commission_pct: float = 0.0003,   # 手续费 0.03%
                       slippage_bps: float = 5,          # 滑点 5 个基点
                       stamp_tax: float = 0.001):        # 印花税（卖出 0.1%）
    """
    带交易成本的回测

    成本组成：
    - 手续费：双边收取（买入+卖出）
    - 滑点：成交价与信号价差
    - 印花税：仅卖出时收取（A 股）
    - 冲击成本：大单对市场的冲击
    """
    trades = signals.diff().fillna(0)
    trade_mask = trades != 0

    # 手续费
    commission = trade_mask.abs() * prices * commission_pct * 2

    # 滑点（按信号方向）
    slippage = trade_mask.abs() * prices * (slippage_bps / 10000)

    # 印花税（仅卖出）
    stamp = (trades < 0) * prices * stamp_tax

    # 总成本
    total_cost = commission + slippage + stamp
    returns = signals.shift(1) * prices.pct_change() - total_cost / prices

    return returns, total_cost
```

---

## 十四、组合优化与执行

### 14.1 组合优化方法对比

| 方法 | 目标 | 优点 | 缺点 |
|------|------|------|------|
| **等权配置** | 无 | 简单、稳定 | 不考虑风险/收益 |
| **均值-方差** | 最大化夏普 | 现代金融理论基础 | 对估计误差敏感 |
| **风险平价** | 风险贡献相等 | 风险均衡 | 需要杠杆固定收益 |
| **最大多元化** | 最大化分散化 | 降低组合波动 | 计算复杂 |
| **Black-Litterman** | 结合主观观点 | 克服均值方差估计问题 | 依赖先验分布 |

### 14.2 Black-Litterman 模型

```python
def black_litterman(market_cap_weights: np.ndarray, equilibrium_returns: np.ndarray,
                     views: dict, view_confidence: float = 0.5,
                     tau: float = 0.1, cov_matrix: np.ndarray = None):
    """
    Black-Litterman 资产配置模型
    - 将市场均衡收益与投资者主观观点结合
    - 输出后验预期收益 → 用于组合优化
    """
    n = len(market_cap_weights)

    # 均衡超额收益
    Pi = equilibrium_returns  # 市场超额收益

    # 观点矩阵 P（哪个资产涉及哪个观点）
    # 简化：假设每个资产一个观点
    P = np.eye(n)

    # 观点收益向量
    Q = np.array([views.get(i, Pi[i]) for i in range(n)])

    # 观点不确定性
    Omega = np.diag(np.diag(P @ (tau * cov_matrix) @ P.T))

    # BL 后验收益
    M = np.linalg.inv(np.linalg.inv(tau * cov_matrix) + P.T @ np.linalg.inv(Omega) @ P)
    post_returns = M @ (np.linalg.inv(tau * cov_matrix) @ Pi + P.T @ np.linalg.inv(Omega) @ Q)

    # 结合置信度
    final_returns = (1 - view_confidence) * Pi + view_confidence * post_returns

    return final_returns
```

### 14.3 执行算法对比

| 算法 | 目标 | 适用场景 |
|------|------|---------|
| **VWAP** | 贴近当日平均成交价 | 大宗交易、被动执行 |
| **TWAP** | 均匀时间分布 | 缺乏流动性资产 |
| **IS (Implementation Shortfall)** | 最小化冲击成本+时序风险 | 紧急执行 |
| **POV (Percent of Volume)** | 跟随市场成交量比例 | 保持市场参与度 |
| **MOC (Market on Close)** | 收盘价成交 | 需收盘调仓的策略 |

---

## 十五、策略开发 Checklist

### 15.1 研究阶段

- [ ] 明确策略类型（趋势/套利/做市/多因子）
- [ ] 定义清晰的策略逻辑和参数
- [ ] 选定基准和数据频率
- [ ] 完成文献综述（确保非重复研究）

### 15.2 数据阶段

- [ ] 数据来源可靠（Wind/Bloomberg/聚宽等）
- [ ] 数据清洗（缺失值、异常值、复权处理）
- [ ] 避免前视偏差（信号使用当期前数据）
- [ ] 处理 IPO 禁售期、新股纳入等事件

### 15.3 回测阶段

- [ ] 加入交易成本（手续费+滑点+印花税）
- [ ] 加入流动性约束（成交量限制）
- [ ] Walk-Forward 验证泛化能力
- [ ] 对比随机策略基准
- [ ] 独立样本外测试（至少 20% 数据量）
- [ ] 考虑冲击成本（大于 1% 日均成交量时）

### 15.4 风险阶段

- [ ] 计算完整风险指标（Sharpe/Calar/MDD/VaR）
- [ ] 压力测试（2015股灾/2020新冠/2022加息等极端场景）
- [ ] 单一标的集中度 < 10-15%
- [ ] 单日 VaR < 账户 2%
- [ ] 最大回撤预警机制

### 15.5 实盘阶段

- [ ] 纸盘（Paper Trading）验证 1-3 个月
- [ ] 实时监控交易执行质量
- [ ] 记录每日策略表现 vs 回测差异
- [ ] 建立异常报警机制
- [ ] 定期（季度）复盘策略有效性

---

## 附录：策略收益来源分解

| 收益来源 | 策略类型 | 可持续性 |
|---------|---------|---------|
| 市场 Beta（系统性风险）| 指数增强、因子暴露 | 中等 |
| Alpha（选股超额收益）| 多因子、机器学习 | 取决于市场效率 |
| 套利收益（价差回归）| 统计套利、配对交易 | 较高（竞争加剧中）|
| 流动性溢价 | 做市商、ETF套利 | 中等 |
| 趋势跟随 | CTA、动量策略 | 中等（依赖市场状态）|
| 波动率收益 | 期权波动率交易 | 中等 |

---

*文档整理完毕，共覆盖 **15 个章节**，涵盖量化交易全策略体系。*
*研究来源：arXiv、ScienceDirect、Springer Nature、MDPI、GitHub 及各量化机构公开研究。*
