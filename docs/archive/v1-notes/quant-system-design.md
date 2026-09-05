# 量化交易系统设计方案

> **设计日期**：2026-04-23
> **设计原则**：模块化、可扩展、可回测、实盘可用
> **目标**：构建一套覆盖研究→回测→风控→执行全流程的量化系统

---

## 一、系统架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE LAYER                      │
│     Web 控制台 │ API 接口 │ 监控面板 │ 告警通知（企微/邮件）     │
└─────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATION LAYER                         │
│     策略调度器 │ 仓位管理器 │ 订单路由器 │ 风险引擎（实时）      │
└─────────────────────────────────────────────────────────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   DATA LAYER     │    │  STRATEGY LAYER  │    │  EXECUTION LAYER │
│                  │    │                  │    │                  │
│  市场数据接入    │    │  多策略引擎      │    │  订单执行网关    │
│  另类数据处理    │    │  信号生成模块    │    │  券商柜台API     │
│  数据清洗/存储   │    │  因子计算引擎    │    │  成交回报处理    │
│  实时/历史数据   │    │  市场环境识别    │    │  滑点/成交分析   │
└──────────────────┘    └──────────────────┘    └──────────────────┘
                                  │
                        ┌──────────────────┐
                        │  RISK LAYER       │
                        │                   │
                        │  VaR / CVaR 计算  │
                        │  仓位校验/限频   │
                        │  回撤监控/熔断   │
                        │  合规检查         │
                        └──────────────────┘
```

---

## 二、核心模块设计

### 2.1 数据层（Data Layer）

**职责**：统一管理所有数据源，提供高质量数据给上层模块。

#### 数据源分类

| 类型 | 数据源 | 频率 | 用途 |
|------|--------|------|------|
| **行情数据** | 券商/交易所直连 / 同花顺 / Wind | Tick / K线 | 策略信号、执行 |
| **基本面数据** | 财报、宏观指标、分析师预期 | 日频/季频 | 多因子Alpha |
| **另类数据** | 新闻、研报、社交媒体、卫星 | 实时/日频 | LLM因子、情绪 |
| **期货数据** | 商品期货、股指期货、国债期货 | Tick/日线 | CTA、套利 |
| **期权数据** | IV曲面、希腊字母、标的资产 | Tick | 波动率策略 |

#### 数据管理关键设计

```python
# 数据层核心抽象
class DataSource(ABC):
    """统一数据源接口"""
    @abstractmethod
    def get_realtime(self, symbol: str) -> Tick:
        """获取实时行情"""
        pass

    @abstractmethod
    def get_historical(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """获取历史数据"""
        pass

    @abstractmethod
    def get_fundamental(self, symbol: str, report_date: date) -> FundamentalData:
        """获取基本面数据"""
        pass


class DataRegistry:
    """数据注册中心：统一管理多数据源"""
    def register(self, source: DataSource, priority: int):
        """注册数据源，priority 决定优先级"""

    def get_price(self, symbol: str, timestamp: datetime) -> float:
        """获取价格，自动选择最优数据源"""

    def get_factor(self, symbol: str, factor_name: str) -> float:
        """获取预计算因子"""
```

#### 数据清洗规范

| 规则 | 处理方式 |
|------|---------|
| **缺失值** | 前向填充（实时）/ 重采样对齐（历史）|
| **异常值** | 3σ 剔除 或 Winsorize 截尾 |
| **涨跌停** | 涨跌停日标记，策略层决定是否交易 |
| **停牌** | 剔除或用前一交易日收盘价 |
| **复权** | 后复权（回测用）/ 不复权（实盘参考）|

---

### 2.2 策略层（Strategy Layer）

#### 策略分类引擎

```
策略分类
├── A. 趋势类（趋势跟踪、CTA、动量）
├── B. 均值回归类（布林带回归、配对交易）
├── C. 套利类（统计套利、跨所套利、期现套利）
├── D. 多因子类（Alpha因子、风控因子）
├── E. 机器学习类（LSTM、Transformer、RL）
└── F. LLM/另类数据类（文本因子、情绪因子）
```

#### 策略基类设计

```python
class BaseStrategy(ABC):
    """所有策略的基类"""

    def __init__(self, config: StrategyConfig):
        self.name = config.name
        self.symbols = config.symbols
        self.params = config.params
        self.state = {}  # 策略状态（持仓、成本等）
        self.is_backtesting = False

    @abstractmethod
    def on_bar(self, bar: Bar) -> List[Signal]:
        """K线/Bar 数据驱动信号生成"""
        pass

    @abstractmethod
    def on_tick(self, tick: Tick) -> List[Signal]:
        """Tick 驱动信号生成（高频策略）"""
        pass

    def on_trade(self, trade: Trade) -> None:
        """成交回报回调"""
        pass

    def get_position(self, symbol: str) -> Position:
        """查询当前持仓"""
        pass

    def get_equity_curve(self) -> pd.Series:
        """获取权益曲线（用于风控和分析）"""
        pass


class StrategyEngine:
    """策略引擎：管理多策略并行"""

    def register(self, strategy: BaseStrategy):
        """注册策略"""

    def generate_signals(self, market_data: MarketData) -> List[Signal]:
        """并行运行所有策略，收集信号"""

    def filter_signals(self, signals: List[Signal]) -> List[Signal]:
        """信号过滤：去重、优先级、信号合并"""
```

#### 信号结构设计

```python
@dataclass
class Signal:
    symbol: str              # 标的代码
    direction: Direction     # LONG / SHORT / CLOSE
    strength: float          # 信号强度 0.0 ~ 1.0
    entry_price: float      # 建议入场价
    stop_loss: float         # 止损价（可选）
    take_profit: float      # 止盈价（可选）
    strategy_name: str       # 来源策略
    timestamp: datetime      # 信号时间戳
    metadata: dict           # 扩展数据（因子值、置信度等）


class SignalFilter:
    """信号过滤器链"""

    def __init__(self):
        self.filters = [
            LiquidityFilter(),      # 流动性过滤
            TrendFilter(),          # 大盘趋势过滤
            VolatilityFilter(),     # 波动率过滤
            TimeFilter(),           # 时段过滤
            SignalDeduplicator(),   # 去重（同一标的同策略信号合并）
        ]

    def process(self, signals: List[Signal]) -> List[Signal]:
        for f in self.filters:
            signals = f.apply(signals)
        return signals
```

---

### 2.3 风控层（Risk Layer）

**风控是量化系统的生命线，所有交易必须经过风控引擎。**

#### 风控规则体系

```
风控引擎（逐笔检查）
├── 事前风控（信号 → 订单 前）
│   ├── VaR 检验：预估损失 > 阈值 → 拒绝
│   ├── 仓位限制：单标的仓位 > 上限 → 拒绝
│   ├── 净敞口限制：多头/空头暴露 > 上限 → 拒绝
│   ├── 相关性限制：同向持仓相关性 > 阈值 → 拒绝
│   ├── 涨跌停检验：涨跌停标的 → 拒绝开仓
│   └── 交易时段限制：集合竞价/收盘前X分钟 → 限制开仓
│
├── 事中风控（持仓监控）
│   ├── 实时 VaR / 最大回撤监控
│   ├── 止损线触发 → 强平
│   ├── 波动率暴涨预警 → 减仓
│   └── 流动性枯竭预警 → 减仓
│
└── 事后风控（收盘后）
    ├── T+1 结算校验
    ├── 业绩归因分析
    └── 因子暴露分析
```

#### 风控核心计算

```python
class RiskEngine:
    """实时风控引擎"""

    def __init__(self, config: RiskConfig):
        self.max_var_pct = config.max_var_pct          # 最大 VaR 比例（如 2%）
        self.max_position_pct = config.max_position_pct # 单标的最大仓位（如 10%）
        self.max_drawdown_pct = config.max_drawdown_pct # 最大回撤（如 15%）
        self.max_leverage = config.max_leverage         # 最大杠杆（如 2.0）
        self.liquidation_cooldown = config.liquidation_cooldown  # 强平冷却期

    def pre_check(self, order: Order, portfolio: Portfolio) -> CheckResult:
        """
        订单事前风控检查
        """
        violations = []

        # 1. VaR 检验
        var_estimate = self.estimate_var(order, portfolio)
        if var_estimate > self.max_var_pct * portfolio.total_equity:
            violations.append(f"VaR 检验失败: 预估 {var_estimate:.2f} > 限额")

        # 2. 仓位限制
        new_position = portfolio.get_position(order.symbol) + order.quantity
        if abs(new_position) > self.max_position_pct * portfolio.total_equity / order.price:
            violations.append(f"仓位超限: {order.symbol}")

        # 3. 涨跌停检验
        if self.is_limit_up_or_down(order.symbol, order.direction):
            violations.append(f"涨跌停标的无法交易: {order.symbol}")

        # 4. 净敞口检验
        net_exposure = portfolio.net_exposure
        if net_exposure + order.direction * order.value > self.max_leverage * portfolio.total_equity:
            violations.append("杠杆超限")

        return CheckResult(passed=len(violations) == 0, violations=violations)

    def estimate_var(self, order: Order, portfolio: Portfolio) -> float:
        """
        简单 VaR 估算
        VaR = position_value * volatility * z_score
        """
        position_value = order.quantity * order.price
        volatility = self.get_historical_volatility(order.symbol)
        z_score = 1.65  # 95% 置信度
        return position_value * volatility * z_score

    def monitor_drawdown(self, portfolio: Portfolio):
        """
        实时回撤监控
        """
        current_drawdown = portfolio.current_drawdown
        if current_drawdown > self.max_drawdown_pct:
            self.trigger_liquidation(portfolio, reason="回撤超限")
        elif current_drawdown > self.max_drawdown_pct * 0.8:
            self.send_warning(f"回撤预警: {current_drawdown:.2%}")
```

#### 杠杆与仓位管理

```python
class PositionSizer:
    """仓位计算器"""

    @staticmethod
    def risk_parity(portfolio_value: float, atr: float,
                    risk_per_trade: float = 0.01) -> int:
        """
        风险平价仓位
        每笔交易承担等额风险（默认账户的 1%）
        仓位 = 账户金额 × 风险比例 / (ATR × 每点价值)
        """
        risk_amount = portfolio_value * risk_per_trade
        position_size = risk_amount / atr
        return int(position_size)

    @staticmethod
    def kelly_criterion(win_rate: float, avg_win: float,
                         avg_loss: float) -> float:
        """
        凯利公式：最优下注比例
        f = (bp - q) / b
        b: 赔率（平均盈利/平均亏损）
        p: 胜率
        q: 败率 (1-p)
        """
        b = avg_win / avg_loss if avg_loss != 0 else 1
        q = 1 - win_rate
        f = (b * win_rate - q) / b
        return max(0, min(f, 0.25))  # 上限 25%，避免过度杠杆

    @staticmethod
    def volatility_targeting(portfolio_value: float,
                              target_vol: float = 0.15,
                              historical_vol: float = 0.20) -> float:
        """
        波动率目标仓位
        目标波动率15%，当前波动率20% → 仓位 = 75%
        """
        return (target_vol / historical_vol) if historical_vol > 0 else 1.0
```

---

### 2.4 执行层（Execution Layer）

#### 订单管理

```python
class Order:
    """订单数据结构"""
    order_id: str
    symbol: str
    direction: Direction        # LONG / SHORT
    order_type: OrderType        # MARKET / LIMIT / STOP
    quantity: int
    price: float                 # 限价（MARKET时为0）
    status: OrderStatus          # PENDING / FILLED / CANCELLED / REJECTED
    filled_quantity: int
    avg_fill_price: float
    created_at: datetime
    filled_at: datetime
    strategy_name: str


class ExecutionRouter:
    """订单路由：决定订单发送到哪个通道"""

    def __init__(self, brokers: List[Broker]):
        self.brokers = brokers
        self.order_book = OrderBook()

    def route(self, order: Order) -> str:
        """
        路由逻辑
        1. 优先选择当前持仓最少/额度最充足的broker
        2. 流动性好的标的走最快通道
        3. 大单走拆单算法
        """
        broker = self.select_broker(order)
        broker.submit_order(order)
        return broker.id


class TWAPExecutor:
    """TWAP 执行器：大单拆成小单"""

    def __init__(self, order: Order, duration_minutes: int = 30):
        self.original_order = order
        self.duration = duration_minutes
        self.slice_count = duration_minutes  # 每分钟一个slice
        self.slice_quantity = order.quantity // self.slice_count

    def execute(self):
        """按固定时间间隔均匀下单"""
        slices = []
        for i in range(self.slice_count):
            slice_order = self.original_order.copy()
            slice_order.quantity = self.slice_quantity
            # 稍微随机一下时间和数量，避免被识别
            time.sleep(60 + random.uniform(-10, 10))
            slices.append(slice_order)
        return slices


class VWAPExecutor:
    """VWAP 执行器：模拟市场VWAP执行"""

    def __init__(self, order: Order, duration_minutes: int = 30):
        self.original_order = order
        self.duration = duration_minutes
        self.vwap_profile = self.load_vwap_profile(order.symbol)

    def execute(self):
        """
        根据历史VWAP分布分配下单量
        开盘/收盘成交量大 → 分配更多份额
        """
        slices = []
        for minute in range(self.duration):
            target_pct = self.vwap_profile[minute]
            slice_qty = int(self.original_order.quantity * target_pct)
            slices.append(self.create_slice_order(slice_qty))
        return slices
```

#### 成交回报处理

```python
class TradeCallback:
    """成交回调处理"""

    def on_fill(self, fill: Fill):
        """成交回报"""
        # 1. 更新持仓
        portfolio.update_position(fill)

        # 2. 更新策略状态
        strategy = strategy_engine.get_strategy(fill.strategy_name)
        strategy.on_trade(fill)

        # 3. 触发风控记录
        risk_engine.record_trade(fill)

        # 4. 发送通知（可选）
        if fill.value > NOTIFICATION_THRESHOLD:
            self.notify_user(fill)


class SlippageAnalyzer:
    """滑点分析"""

    def analyze(self, fills: List[Fill]) -> pd.DataFrame:
        """
        分析滑点情况
        """
        results = []
        for fill in fills:
            expected_price = fill.signal_price  # 当时信号价
            actual_price = fill.filled_price
            slippage = (actual_price - expected_price) / expected_price
            results.append({
                'symbol': fill.symbol,
                'direction': fill.direction,
                'signal_price': expected_price,
                'fill_price': actual_price,
                'slippage_bps': slippage * 10000,
                'slippage_cost': abs(fill.quantity * (actual_price - expected_price))
            })
        return pd.DataFrame(results)
```

---

### 2.5 市场环境识别（Regime Detection）

**这是系统最核心的决策模块之一**：判断当前市场适合哪类策略。

```python
class MarketRegimeDetector:
    """
    市场状态识别
    """

    REGIMES = {
        'TREND_UP': '趋势上涨',
        'TREND_DOWN': '趋势下跌',
        'MEAN_REVERTING': '均值回归',
        'HIGH_VOL': '高波动',
        'LOW_VOL': '低波动',
        'CRISIS': '危机'
    }

    def detect(self, market_data: MarketData) -> str:
        """
        综合多指标判断市场状态
        """

        # 1. 趋势强度（ADX）
        adx = self.calc_adx(market_data, period=14)

        # 2. 波动率水平（HV vs 历史均值）
        hv = self.calc_historical_vol(market_data, period=20)
        hv_zscore = (hv - hv.mean()) / hv.std()

        # 3. 协整/均值回归强度
        mean_reversion_strength = self.calc_halflife(market_data)

        # 4. 趋势方向
        sma_diff = market_data.sma(50) - market_data.sma(200)  # 金叉/死叉

        # 综合判断
        if adx < 20 and abs(hv_zscore) < 1:
            return self.REGIMES['LOW_VOL']
        elif adx > 30 and sma_diff > 0:
            return self.REGIMES['TREND_UP']
        elif adx > 30 and sma_diff < 0:
            return self.REGIMES['TREND_DOWN']
        elif hv_zscore > 2:
            return self.REGIMES['HIGH_VOL']
        elif mean_reversion_strength > 0.7 and adx < 25:
            return self.REGIMES['MEAN_REVERTING']
        else:
            return self.REGIMES['LOW_VOL']


class StrategySelector:
    """
    根据市场状态选择策略权重
    """

    REGIME_STRATEGY_WEIGHTS = {
        'TREND_UP': {'trend_following': 0.6, 'mean_reversion': 0.1,
                     'stat_arb': 0.2, 'risk_parity': 0.1},
        'TREND_DOWN': {'trend_following': 0.5, 'stat_arb': 0.3,
                       'mean_reversion': 0.0, 'risk_parity': 0.2},
        'MEAN_REVERTING': {'trend_following': 0.1, 'mean_reversion': 0.6,
                           'stat_arb': 0.2, 'risk_parity': 0.1},
        'HIGH_VOL': {'trend_following': 0.3, 'volatility': 0.4,
                     'stat_arb': 0.1, 'risk_parity': 0.2},
        'LOW_VOL': {'trend_following': 0.2, 'mean_reversion': 0.3,
                    'stat_arb': 0.3, 'risk_parity': 0.2},
        'CRISIS': {'trend_following': 0.2, 'stat_arb': 0.0,
                   'risk_parity': 0.6, 'cash': 0.2},
    }

    def select(self, regime: str) -> Dict[str, float]:
        return self.REGIME_STRATEGY_WEIGHTS.get(regime, self.REGIME_STRATEGY_WEIGHTS['LOW_VOL'])
```

---

### 2.6 组合优化器（Portfolio Optimizer）

```python
class PortfolioOptimizer:
    """
    组合优化器：多策略信号 → 最优仓位
    """

    def optimize(self, signals: List[Signal],
                 current_positions: Dict[str, float],
                 portfolio_value: float,
                 constraints: dict) -> Dict[str, Position]:
        """
        输入：多个策略产生的信号 + 当前持仓 + 账户权益
        输出：各标的的目标仓位

        约束条件：
        - 最大化预期收益 / 最小化风险
        - 仓位上下限
        - 单标的集中度限制
        - 风格暴露限制（ Barra 风险）
        """

        # 1. 合并信号（去重 + 强度加权）
        merged_signals = self.merge_signals(signals)

        # 2. 计算预期收益
        expected_returns = self.calc_expected_returns(merged_signals)

        # 3. 风险模型（简化协方差矩阵）
        cov_matrix = self.calc_cov_matrix(merged_signals)

        # 4. 优化求解（最大化夏普比率）
        weights = self.solve_max_sharpe(expected_returns, cov_matrix,
                                         constraints)

        # 5. 应用风控约束
        weights = self.apply_risk_constraints(weights, constraints)

        return self.weights_to_positions(weights, portfolio_value)


    def merge_signals(self, signals: List[Signal]) -> pd.DataFrame:
        """
        合并同一标的的多策略信号
        signal_strength 加权平均
        """
        df = pd.DataFrame([{
            'symbol': s.symbol,
            'direction': s.direction,
            'strength': s.strength,
            'strategy': s.strategy_name
        } for s in signals])

        return df.groupby('symbol').agg({
            'strength': lambda x: np.average(x, weights=range(1, len(x)+1)),
            'direction': lambda x: x.mode()[0] if len(x) > 0 else 0
        })


    def solve_max_sharpe(self, returns: np.array, cov: np.array,
                         constraints: dict) -> np.array:
        """
        最大化夏普比率的组合权重
        使用均值-方差优化（Markowitz）
        """
        from scipy.optimize import minimize

        n = len(returns)
        args = (returns, cov)

        def neg_sharpe(weights, returns, cov):
            port_return = np.dot(weights, returns)
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov, weights)))
            return -(port_return / port_vol)

        constraints = [
            {'type': 'eq', 'fun': lambda x: np.sum(x) - 1},  # 权重和=1
        ]
        bounds = tuple((0, 1) for _ in range(n))  # 做多

        result = minimize(neg_sharpe, n * [1./n], args=args,
                           method='SLSQP', bounds=bounds,
                           constraints=constraints)
        return result.x
```

---

### 2.7 回测引擎（Backtest Engine）

```python
class BacktestEngine:
    """
    高保真回测引擎
    """

    def __init__(self, config: BacktestConfig):
        self.initial_capital = config.initial_capital
        self.commission_rate = config.commission_rate
        self.slippage_rate = config.slippage_rate
        self.data_source = config.data_source

    def run(self, strategy: BaseStrategy,
            start_date: date, end_date: date,
            symbols: List[str]) -> BacktestResult:
        """
        逐日/逐笔回测
        """

        # 1. 加载历史数据
        bars = self.data_source.load_bars(symbols, start_date, end_date)

        # 2. 初始化组合
        portfolio = Portfolio(self.initial_capital)

        # 3. 逐日运行策略
        daily_results = []
        for date, daily_bars in bars.groupby(level=0):
            # 生成信号
            signals = strategy.generate_signals(daily_bars)

            # 信号过滤
            signals = self.signal_filter.process(signals)

            # 仓位优化
            target_positions = self.optimizer.optimize(
                signals, portfolio.positions, portfolio.total_equity, {}
            )

            # 生成订单（考虑滑点/手续费）
            orders = self.generate_orders(portfolio, target_positions)

            # 订单执行模拟（用收盘价 + 滑点）
            fills = self.simulate_execution(orders, daily_bars)

            # 更新持仓/权益
            portfolio.update(fills)

            # 风控检查
            self.risk_engine.check(portfolio)

            daily_results.append(portfolio.snapshot())

        return BacktestResult(daily_results)


class WalkForwardValidator:
    """
    Walk-Forward 验证：对抗过拟合
    """

    def run(self, strategy: BaseStrategy, full_data: pd.DataFrame,
            train_window: int = 252, test_window: int = 63):
        """
        滚动窗口验证
        - 用过去252天训练
        - 用未来63天测试
        - 滚动推进
        """
        results = []
        for start in range(0, len(full_data) - train_window - test_window,
                           test_window):
            train_data = full_data.iloc[start: start + train_window]
            test_data = full_data.iloc[start + train_window:
                                        start + train_window + test_window]

            # 训练阶段：优化参数
            optimized_params = self.optimize_params(strategy, train_data)

            # 测试阶段：用优化后的参数运行
            strategy.params = optimized_params
            test_result = BacktestEngine().run(strategy, test_data)
            results.append(test_result)

        return self.analyze_walk_forward_results(results)
```

---

### 2.8 LLM 集成模块（可选扩展）

```python
class LLMEvaluationAgent:
    """
    LLM 评估 Agent：利用大模型做策略审核和另类数据挖掘
    """

    def evaluate_strategy(self, strategy: BaseStrategy,
                          market_context: str) -> EvaluationResult:
        """
        让 LLM 评估策略在当前市场环境下是否合适
        """

        prompt = f"""
        当前市场环境：
        {market_context}

        策略信息：
        - 名称: {strategy.name}
        - 类型: {strategy.category}
        - 核心逻辑: {strategy.description}
        - 历史夏普: {strategy.sharpe_ratio}
        - 最大回撤: {strategy.max_drawdown}

        请评估：
        1. 当前市场环境是否适合此策略？
        2. 有哪些潜在风险需要关注？
        3. 建议的仓位比例？
        """

        response = llm.invoke(prompt)
        return EvaluationResult.parse(response)


class NewsSentimentExtractor:
    """
    新闻/研报情感因子提取
    """

    def extract(self, news_text: str) -> SentimentFactor:
        """
        用 LLM 提取情感因子
        """
        prompt = f"""
        请分析以下新闻/研报的情感倾向：

        {news_text[:2000]}

        返回JSON格式：
        {{
            "sentiment_score": -1.0 ~ 1.0,
            "confidence": 0.0 ~ 1.0,
            "key_topics": ["主题词1", "主题词2"],
            "impact_direction": "positive/negative/neutral",
            "affected_sectors": ["行业1", "行业2"]
        }}
        """
        result = llm.invoke_json(prompt)
        return SentimentFactor(**result)
```

---

## 三、技术架构选型

### 3.1 核心语言与框架

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| **核心语言** | Python 3.11+ | 生态最丰富 |
| **回测框架** | 自研（轻量）+ Backtrader | 高保真回测用自研 |
| **实盘框架** | 自研 Event-Driven 架构 | 避免通用框架性能问题 |
| **数据存储** | PostgreSQL（时序）+ Redis（缓存）+ S3（历史归档）| |
| **特征存储** | Feature Store（Feast/DVC）| 特征复用 |
| **ML 框架** | PyTorch + scikit-learn | 机器学习模型 |
| **因子计算** | Polars（高性能 DataFrame）| 替代 pandas |
| **实时计算** | asyncio + Redis Streams | 高并发 |
| **API 网关** | FastAPI | 策略管理/监控接口 |
| **任务调度** | Airflow / Prefect | 回测任务编排 |
| **容器化** | Docker + K8s | 策略隔离+弹性 |
| **监控告警** | Grafana + Prometheus + 企微机器人 | 实时监控 |

### 3.2 系统部署架构

```
┌─────────────────────────────────────────────────┐
│                   K8s Cluster                    │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Data     │  │ Strategy  │  │ Risk     │       │
│  │ Worker   │  │ Engine    │  │ Engine   │       │
│  │ (Pod)    │  │ (Pod)     │  │ (Pod)    │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │             │             │              │
│  ┌────┴─────────────┴─────────────┴────┐         │
│  │         Redis (消息队列/缓存)         │         │
│  └────────────────────────────────────┘         │
│                                                  │
│  ┌────────────────────────────────────────┐      │
│  │  PostgreSQL (组合/持仓/订单/日志)        │      │
│  └────────────────────────────────────────┘      │
└─────────────────────────────────────────────────┘

外接：
  ├── 券商柜台（恒生/金证/迅投）
  ├── 数据源（Wind/Tushare/交易所直连）
  └── 企微/邮件（告警通知）
```

---

## 四、策略开发工作流

```
Step 1: 想法生成
   │
   ├── 市场观察 → 观察到 X 现象
   ├── 文献研究 → 阅读 Papers / 研报
   └── 数据挖掘 → 因子IC分析
   │
   ▼
Step 2: 初步验证（快速回测）
   │ 工具：Jupyter + Pandas
   │ 数据：近2年日线数据
   │ 目的：验证逻辑是否有效
   │
   ▼
Step 3: 参数优化
   │ 工具：Optuna / GridSearch
   │ 方法：Walk-Forward（避免过拟合）
   │ 标准：夏普>0.5，回撤<15%
   │
   ▼
Step 4: 全量回测
   │ 工具：BacktestEngine
   │ 数据：2010-2025 全量（含手续费/滑点）
   │ 检验：多市场、多品种、多环境
   │
   ▼
Step 5: 样本外验证
   │ Walk-Forward 滚动验证
   │ 泛化能力检验
   │
   ▼
Step 6: 实盘模拟（Paper Trading）
   │ 时间：至少1个月
   │ 监控：滑点、成交率、信号延迟
   │
   ▼
Step 7: 小资金实盘
   │ 资金：额定规模的 5-10%
   │ 目的：验证真实成交/风控
   │
   ▼
Step 8: 全量上线
   │
   └── 持续监控：每日/每周/每月 review
```

---

## 五、策略选择决策树

```
输入：当前市场状态 + 可用资金 + 团队能力

市场状态判断
│
├─ ADX < 20（无趋势，震荡）
│   ├─ HV 低 → 低波动环境
│   │   └→ 优先：均值回归、统计套利、期权卖Vol
│   │
│   └─ HV 高 → 高波动震荡
│       └→ 优先：期权策略、波动率交易、短线套利
│
├─ ADX > 30 + 价格 > 均线（上涨趋势）
│   └→ 优先：趋势跟踪（CTA）、动量因子、买方ETF
│
├─ ADX > 30 + 价格 < 均线（下跌趋势）
│   ├─ 趋势明确 → 趋势跟踪（CTA空头）、空头策略
│   └─ 恐慌时刻 → 现金为王，少量做多波动率
│
└─ 危机时刻（VIX > 30 / 大幅跳空）
    └→ 优先：风险平价、期权保护、趋势跟踪（商品/黄金）
```

---

## 六、关键设计决策

| 决策点 | 选择 | 理由 |
|-------|------|------|
| **编程语言** | Python | 量化生态最成熟，ML/AI 支持最好 |
| **回测 vs 实盘** | 统一策略引擎 | 避免回测/实盘逻辑不一致（核心问题）|
| **执行频率** | 事件驱动（Event-Driven）| 优于定时轮询，更高效 |
| **数据频率** | Tick + K线双轨 | 高频用Tick，Alpha用K线/分钟线 |
| **风控位置** | 独立风控引擎，所有订单必经 | 不依赖策略自带的止损 |
| **信号合并** | 策略层之上独立组合优化器 | 多策略信号需要全局优化 |
| **市场状态** | 独立 Regime Detection 模块 | 自动切换策略权重 |
| **过拟合防御** | Walk-Forward + Out-of-Sample | 标准方法 |
| **可扩展性** | 插件化策略注册 | 新策略上线不影响现有系统 |
| **延迟要求** | 券商柜台 < 10ms | 手动柜台延迟可放宽 |

---

## 七、项目落地路线图

> **设计原则调整**：原路线图采用"瀑布式"开发，存在 API 联调滞后、监控告警缺位、纸盘验证不足等系统性风险。现调整为**敏捷端到端**开发模式：尽早打通全链路、尽早引入监控与风控、持续做数据质量保障。

| 阶段 | 时间 | 目标 | 关键交付物 |
|------|------|------|-----------|
| **Phase 1** | 第1-2月 | **敏捷端到端打通**：用最简策略（如双均线）完成"数据接入 → 简单回测 → 券商 API 联调 → 基础告警（企微/邮件）"全链路；建立数据清洗框架（作为贯穿全阶段的持续优化主线） | 端到端最小可用系统（MVP）；数据清洗基础框架；券商 API 沙箱联调通过；基础企微/邮件告警可触发 |
| **Phase 2** | 第3-5月 | **风控引擎 + 纸盘交易**：深化风控与异常处理，正式纸盘运行；引入**滑点模拟引擎与撮合延迟测试**；添加**数据一致性检查**（回测数据 vs 实时行情）；完善**错误日志告警与熔断（Kill Switch）机制** | 纸盘交易系统上线；滑点模拟引擎；数据一致性校验模块；异常掉线/错误日志自动告警；熔断开关 |
| **Phase 3** | 第6-8月 | **多策略 + 组合优化 + 小资金实盘**：扩展策略库，上线多策略并行与组合优化器（含 Walk-Forward 验证）；在完善监控告警体系下启动**小资金实盘交易** | 多策略框架；组合优化器；Walk-Forward 验证；小资金实盘上线（监控全覆盖）；监控面板 v1 |
| **Phase 4** | 第9-12月 | **ML/LLM + 全自动交易 + 扩大实盘**：引入深度学习/LLM 模块与 Regime Detection；高频执行优化；上线高级监控面板；扩大实盘规模与策略容量 | ML/LLM 信号模块；Regime Detection；高级监控面板；扩大实盘规模 |

### 路线图调整说明

| 原计划问题 | 调整方案 |
|-----------|---------|
| **API 联调推迟至第7月**（最高风险）| Phase 1 即打通券商 API 沙箱，尽早暴露接口限制与兼容性问题 |
| **监控告警排在实盘之后**（安全隐患）| 基础错误日志告警与熔断机制在 Phase 2 完成，Phase 3 实盘前必须就绪 |
| **数据清洗仅为 Phase 1 单次任务** | 数据清洗与校验作为跨阶段持续主线，Phase 2 增加回测与实时行情一致性检查 |
| **滑点分析推迟至实盘阶段** | Phase 2 纸盘阶段即引入滑点模拟引擎与撮合延迟测试，避免策略被实盘滑点直接证伪 |

---

*本方案基于《量化交易策略核心本质》文档设计，涵盖数据→策略→风控→执行全链路。*
