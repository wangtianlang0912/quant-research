"""
quant-research 可视化面板
FastAPI 后端 + Chart.js 前端

运行: python3.11 -m visualization.app
访问: http://localhost:8899
"""
from __future__ import annotations

import sys
import json
import os
import uuid
import subprocess
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parent
# Ensure PROJECT_ROOT is on sys.path for src.* imports
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DATA_DIR = PROJECT_ROOT / "data" / "1d"
REPORTS_DIR = PROJECT_ROOT / "reports"

app = FastAPI(title="Quant Research Dashboard", version="1.0.0")

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ─── 数据层 ────────────────────────────────────────────────────────────────

SYMBOL_NAMES = {
    # CSV (data/1d/)
    "000300.SH": "沪深300",
    "00700.HK": "腾讯控股",
    "1810.HK": "小米集团",
    "3690.HK": "美团",
    "600900.SS": "长江电力",
    "9988.HK": "阿里巴巴",
}

# JSON kline cache → symbol mapping (data/cache/klines_dashboard_*.json)
CACHE_SYMBOL_MAP = {
    # A股 AI标的
    'sh688256': ('688256.SS', '寒武纪'),
    'sh688981': ('688981.SS', '中芯国际'),
    'sh688041': ('688041.SS', '海光信息'),
    'sh688047': ('688047.SS', '龙芯中科'),
    'sh688525': ('688525.SS', '佰维存储'),
    'sz002049': ('002049.SZ', '紫光国微'),
    'sh603986': ('603986.SS', '兆易创新'),
    'sz300474': ('300474.SZ', '景嘉微'),
    'sh688008': ('688008.SS', '澜起科技'),
    'sz300308': ('300308.SZ', '中际旭创'),
    'sz300502': ('300502.SZ', '新易盛'),
    'sz300394': ('300394.SZ', '天孚通信'),
    'sz300548': ('300548.SZ', '长芯博创'),
    'sz300570': ('300570.SZ', '太辰光'),
    'sh688498': ('688498.SS', '源杰科技'),
    'sz300620': ('300620.SZ', '光库科技'),
    'sz002230': ('002230.SZ', '科大讯飞'),
    'sz300033': ('300033.SZ', '同花顺'),
    'sz300624': ('300624.SZ', '万兴科技'),
    'sh688111': ('688111.SS', '金山办公'),
    'sh688083': ('688083.SS', '中望软件'),
    'sh688095': ('688095.SS', '福昕软件'),
    'sz300663': ('300663.SZ', '科蓝软件'),
    'sz300377': ('300377.SZ', '赢时胜'),
    'sz300124': ('300124.SZ', '汇川技术'),
    'sz300024': ('300024.SZ', '机器人'),
    'sz002747': ('002747.SZ', '埃斯顿'),
    'sh688017': ('688017.SS', '绿的谐波'),
    'sz002527': ('002527.SZ', '新时达'),
    'sh603728': ('603728.SS', '鸣志电器'),
    'sz300660': ('300660.SZ', '江苏雷利'),
    'sz002916': ('002916.SZ', '深南电路'),
    'sh688385': ('688385.SS', '复旦微电'),
    'sh688126': ('688126.SS', '沪硅产业'),
    'sz300223': ('300223.SZ', '北京君正'),
    'sh688234': ('688234.SS', '天岳先进'),
    'sh603501': ('603501.SS', '豪威集团'),
    # 港股
    'hk00700': ('00700.HK', '腾讯控股'),
    'hk09988': ('09988.HK', '阿里巴巴'),
    'hk09888': ('09888.HK', '百度'),
    'hk09618': ('09618.HK', '京东'),
    'hk09866': ('09866.HK', '蔚来'),
    'hk01384': ('01384.HK', '滴普科技'),
    'hk06651': ('06651.HK', '五一视界'),
    'hk00068': ('00068.HK', '群核科技'),
    'hk03690': ('03690.HK', '美团'),
    'hk01810': ('01810.HK', '小米'),
    'hk01024': ('01024.HK', '快手'),
    'hk09999': ('09999.HK', '网易'),
    'hk02015': ('02015.HK', '理想汽车'),
    'hk09868': ('09868.HK', '小鹏汽车'),
    'hk01211': ('01211.HK', '比亚迪'),
    'hk09992': ('09992.HK', '泡泡玛特'),
    'hk09633': ('09633.HK', '农夫山泉'),
    'hk00285': ('00285.HK', '比亚迪电子'),
    'hk02382': ('02382.HK', '舜宇光学'),
    'hk02018': ('02018.HK', '瑞声科技'),
    'hk06969': ('06969.HK', '思摩尔国际'),
    'hk00175': ('00175.HK', '吉利汽车'),
    'hk02331': ('02331.HK', '李宁'),
    'hk06862': ('06862.HK', '海底捞'),
    'hk02020': ('02020.HK', '安踏体育'),
    'hk02688': ('02688.HK', '新奥能源'),
    'hk02319': ('02319.HK', '蒙牛乳业'),
    'hk02269': ('02269.HK', '药明生物'),
    'hk01801': ('01801.HK', '信达生物'),
    'hk06618': ('06618.HK', '京东健康'),
    'hk00005': ('00005.HK', '汇丰控股'),
    'hk00388': ('00388.HK', '港交所'),
    'hk01398': ('01398.HK', '工商银行'),
    'hk03988': ('03988.HK', '中国银行'),
    'hk02628': ('02628.HK', '中国人寿'),
    'hk02318': ('02318.HK', '中国平安'),
    'hk01299': ('01299.HK', '友邦保险'),
    'hk00016': ('00016.HK', '新鸿基地产'),
    'hk01113': ('01113.HK', '长实集团'),
    'hk01109': ('01109.HK', '华润置地'),
    'hk00941': ('00941.HK', '中国移动'),
    'hk00883': ('00883.HK', '中海油'),
    'hk00857': ('00857.HK', '中石油'),
    'hk00386': ('00386.HK', '中石化'),
    'hk00002': ('00002.HK', '中电控股'),
    'hk00003': ('00003.HK', '香港中华煤气'),
    'hk00006': ('00006.HK', '电能实业'),
    'hk00012': ('00012.HK', '恒基地产'),
    'hk00011': ('00011.HK', '恒生银行'),
    'hk02388': ('02388.HK', '中银香港'),
    'hk01177': ('01177.HK', '中国生物制药'),
    'hk01093': ('01093.HK', '石药集团'),
    'hk00762': ('00762.HK', '中国联通'),
    'hk00728': ('00728.HK', '中国电信'),
    'hk00960': ('00960.HK', '龙湖集团'),
    'hk01910': ('01910.HK', '新秀丽'),
    'hk01928': ('01928.HK', '金沙中国'),
    'hk02013': ('02013.HK', '微盟'),
    'hk02007': ('02007.HK', '碧桂园'),
    'hk00268': ('00268.HK', '金蝶国际'),
    'hk00267': ('00267.HK', '中信股份'),
    'hk06186': ('06186.HK', '中国飞鹤'),
    'hk01876': ('01876.HK', '百威亚太'),
    'hk00381': ('00381.HK', '侨雄国际'),
    'hk0016.HK': ('00016.HK', '新鸿基地产'),
}


def list_available_symbols() -> list[dict]:
    """扫描 data/ 目录 + cache JSON，返回所有可用标的。"""
    symbols = []
    seen = set()
    
    # 1. CSV 文件 (data/1d/)
    for csv_file in DATA_DIR.glob("*.csv"):
        symbol = csv_file.stem
        seen.add(symbol)
        stat = csv_file.stat()
        row_count = 0
        first_ts = last_ts = "?"
        try:
            with open(csv_file) as f:
                next(f)  # skip header
                first_line = f.readline().strip()
                if first_line:
                    first_ts = first_line.split(",")[0][:10]
                last_line = None
                for line in f:
                    last_line = line
                    row_count += 1
                if last_line:
                    last_ts = last_line.split(",")[0][:10]
        except Exception:
            pass
        name = SYMBOL_NAMES.get(symbol, symbol)
        market = _guess_market(symbol)
        symbols.append(_make_symbol_entry(symbol, name, market, row_count, first_ts, last_ts, stat.st_size))
    
    # 2. JSON cache (data/cache/klines_dashboard_*.json)
    cache_dir = PROJECT_ROOT / "data" / "cache"
    for json_file in cache_dir.glob("klines_dashboard_*.json"):
        raw_key = json_file.stem.replace("klines_dashboard_", "")  # e.g. hk00700, sh688256
        mapped = CACHE_SYMBOL_MAP.get(raw_key)
        if not mapped:
            continue
        display_symbol, display_name = mapped
        if display_symbol in seen:
            continue
        seen.add(display_symbol)
        
        # Read last bar for date
        row_count = 0
        first_ts = last_ts = "?"
        try:
            import json as _json
            with open(json_file) as f:
                bars = _json.load(f)
            row_count = len(bars)
            if bars:
                first_ts = datetime.fromtimestamp(bars[0]['t']).strftime('%Y-%m-%d')
                last_ts = datetime.fromtimestamp(bars[-1]['t']).strftime('%Y-%m-%d')
        except Exception:
            pass
        market = _guess_market(display_symbol)
        symbols.append(_make_symbol_entry(display_symbol, display_name, market, row_count, first_ts, last_ts, json_file.stat().st_size))
    
    return sorted(symbols, key=lambda x: x["symbol"])

def _guess_market(symbol: str) -> str:
    if symbol.upper().endswith('.HK'):
        return 'HK'
    return 'A'

def _make_symbol_entry(symbol: str, name: str, market: str, rows: int, start: str, end: str, size: int) -> dict:
    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "rows": rows,
        "start_date": start,
        "end_date": end,
        "file_size_kb": round(size / 1024, 1),
    }


def load_csv_timeseries(symbol: str, start: str = "", end: str = "") -> list[dict]:
    """加载 K 线时序数据，优先 CSV，fallback 到 JSON cache。"""
    # 1. Try CSV
    csv_path = DATA_DIR / f"{symbol}.csv"
    if csv_path.exists():
        return _load_csv(symbol, csv_path)
    
    # 2. Try JSON cache
    cache_dir = PROJECT_ROOT / "data" / "cache"
    # Reverse-lookup: find which cache key maps to this symbol
    for cache_key, (cache_symbol, _) in CACHE_SYMBOL_MAP.items():
        if cache_symbol == symbol:
            json_path = cache_dir / f"klines_dashboard_{cache_key}.json"
            if json_path.exists():
                return _load_json(json_path)
    return []

def _load_csv(symbol: str, csv_path) -> list[dict]:
    rows = []
    try:
        with open(csv_path) as f:
            next(f)  # skip header
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 5:
                    continue
                # Format: timestamp,open,high,low,close,volume,...
                rows.append({
                    "timestamp": parts[0],
                    "open": float(parts[1]),
                    "high": float(parts[2]),
                    "low": float(parts[3]),
                    "close": float(parts[4]),
                    "volume": float(parts[5]) if len(parts) > 5 else 0,
                })
    except Exception:
        pass
    return rows

def _load_json(json_path) -> list[dict]:
    rows = []
    try:
        import json as _json
        with open(json_path) as f:
            bars = _json.load(f)
        for b in bars:
            rows.append({
                "timestamp": datetime.fromtimestamp(b['t']).strftime('%Y-%m-%d %H:%M:%S'),
                "open": b['o'],
                "high": b['h'],
                "low": b['l'],
                "close": b['c'],
                "volume": b.get('v', 0),
            })
    except Exception:
        pass
    return rows


def load_equity_curve(run_id: str) -> list[dict]:
    """从报告文件中提取净值曲线。"""
    import csv
    # 尝试从 CSV 净值文件中读取
    eq_path = REPORTS_DIR / "equity" / f"{run_id}.csv"
    if eq_path.exists():
        rows = []
        with open(eq_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({"timestamp": row["timestamp"], "equity": float(row["equity"])})
        return rows
    return []


def list_backtest_reports() -> list[dict]:
    """列出所有回测报告，按时间倒序。"""
    reports = []
    backtest_dir = REPORTS_DIR / "backtest"
    if not backtest_dir.exists():
        return []
    for json_file in backtest_dir.glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
            ctx = data.get("context", {})
            summary = data.get("summary", {})
            reports.append({
                "run_id": ctx.get("run_id", {}).get("value", json_file.stem),
                "symbol": ctx.get("symbols", ["?"])[0],
                "strategy": ctx.get("strategy_id", {}).get("value", "?"),
                "frequency": ctx.get("frequency", "?"),
                "start_date": ctx.get("start_date", "?"),
                "end_date": ctx.get("end_date", "?"),
                "status": summary.get("status", "?"),
                "final_equity": _fmt(summary.get("final_equity")),
                "total_return": _fmt_pct(summary.get("total_return")),
                "annualized_return": _fmt_pct(summary.get("annualized_return")),
                "max_drawdown": _fmt_pct(summary.get("max_drawdown")),
                "sharpe_ratio": _fmt(summary.get("sharpe_ratio")),
                "created_at": ctx.get("created_at", "")[:19],
                "metadata": ctx.get("metadata", {}),
            })
        except Exception:
            pass
    return sorted(reports, key=lambda x: x["created_at"], reverse=True)


def load_report_detail(run_id: str) -> dict | None:
    """加载单个回测报告详情。"""
    for json_file in (REPORTS_DIR / "backtest").glob("*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
            if data.get("context", {}).get("run_id", {}).get("value") == run_id:
                return data
        except Exception:
            pass
    return None


def _fmt(v) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def _fmt_pct(v) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v) * 100:.2f}%"
    except Exception:
        return str(v)


# ─── 策略参数定义 ──────────────────────────────────────────────────────────

STRATEGY_PARAMS_SCHEMA = {
    "trend_following": [
        {"name": "short_window", "label": "短期均线", "type": "int", "default": 5, "min": 2, "max": 60},
        {"name": "long_window", "label": "长期均线", "type": "int", "default": 20, "min": 5, "max": 200},
    ],
    "mean_reversion": [
        {"name": "lookback_window", "label": "历史窗口", "type": "int", "default": 20, "min": 5, "max": 200},
        {"name": "entry_zscore", "label": "入场阈值", "type": "float", "default": 1.0, "min": 0.5, "max": 3.0, "step": 0.1},
        {"name": "exit_zscore", "label": "平仓阈值", "type": "float", "default": 0.3, "min": 0.1, "max": 1.5, "step": 0.05},
    ],
    "bollinger_bands": [
        {"name": "window", "label": "窗口期", "type": "int", "default": 20, "min": 5, "max": 100},
        {"name": "num_std", "label": "标准差倍数", "type": "float", "default": 2.0, "min": 1.5, "max": 3.0, "step": 0.25},
        {"name": "exit_threshold", "label": "平仓阈值", "type": "float", "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.1},
    ],
    "macd_rsi": [
        {"name": "macd_fast", "label": "MACD快线", "type": "int", "default": 12, "min": 5, "max": 20},
        {"name": "macd_slow", "label": "MACD慢线", "type": "int", "default": 26, "min": 20, "max": 50},
        {"name": "macd_signal", "label": "MACD信号线", "type": "int", "default": 9, "min": 5, "max": 20},
        {"name": "rsi_period", "label": "RSI周期", "type": "int", "default": 14, "min": 7, "max": 30},
        {"name": "rsi_overbought", "label": "RSI超买", "type": "float", "default": 70.0, "min": 60.0, "max": 85.0, "step": 2.0},
        {"name": "rsi_oversold", "label": "RSI超卖", "type": "float", "default": 30.0, "min": 15.0, "max": 40.0, "step": 2.0},
    ],
    "vwap": [
        {"name": "deviation_pct", "label": "偏离百分比(%)", "type": "float", "default": 1.0, "min": 0.1, "max": 5.0, "step": 0.1},
    ],
    "donchian_channel": [
        {"name": "channel_period", "label": "通道周期", "type": "int", "default": 20, "min": 10, "max": 100},
        {"name": "exit_period", "label": "退出周期", "type": "int", "default": 10, "min": 5, "max": 50},
    ],
}

RISK_PARAMS_SCHEMA = [
    {"name": "commission_rate", "label": "佣金率", "type": "float", "default": 0.0003, "min": 0.0, "max": 0.01, "step": 0.0001},
    {"name": "slippage_rate", "label": "滑点率", "type": "float", "default": 0.0005, "min": 0.0, "max": 0.01, "step": 0.0001},
    {"name": "max_drawdown_ratio", "label": "回撤熔断", "type": "float", "default": 0.15, "min": 0.01, "max": 0.5, "step": 0.01},
]

SCAN_GRID = {
    "trend_following": {
        "short_window": [3, 5, 10, 15],
        "long_window": [20, 30, 60, 90],
    },
    "mean_reversion": {
        "lookback_window": [10, 20, 30, 50],
        "entry_zscore": [0.8, 1.0, 1.5, 2.0],
    },
    "bollinger_bands": {
        "window": [10, 20, 30, 50],
        "num_std": [1.5, 2.0, 2.5, 3.0],
    },
    "macd_rsi": {
        "macd_fast": [8, 12, 16],
        "macd_slow": [20, 26, 34],
        "macd_signal": [7, 9, 12],
    },
    "vwap": {
        "deviation_pct": [0.5, 1.0, 2.0, 3.0],
    },
    "donchian_channel": {
        "channel_period": [10, 20, 40, 60],
        "exit_period": [5, 10, 20],
    },
}


# ─── API 路由 ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """加载主面板页面。"""
    with open(BASE_DIR / "templates" / "dashboard.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/symbols")
async def api_symbols():
    return JSONResponse(list_available_symbols())


@app.get("/api/timeseries/{symbol}")
async def api_timeseries(symbol: str, start: str = "", end: str = ""):
    data = load_csv_timeseries(symbol, start, end)
    return JSONResponse(data)


@app.get("/api/reports")
async def api_reports():
    return JSONResponse(list_backtest_reports())


@app.get("/api/report/{run_id}")
async def api_report(run_id: str):
    data = load_report_detail(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return JSONResponse(data)


@app.get("/api/strategies")
async def api_strategies():
    """返回可用策略列表及参数定义。"""
    return JSONResponse({
        "strategies": [
            {"id": "trend_following", "name": "趋势跟随 (MA Cross)", "params": STRATEGY_PARAMS_SCHEMA["trend_following"]},
            {"id": "mean_reversion", "name": "均值回归 (Z-Score)", "params": STRATEGY_PARAMS_SCHEMA["mean_reversion"]},
            {"id": "bollinger_bands", "name": "布林带 (Bollinger Bands)", "params": STRATEGY_PARAMS_SCHEMA["bollinger_bands"]},
            {"id": "macd_rsi", "name": "MACD+RSI", "params": STRATEGY_PARAMS_SCHEMA["macd_rsi"]},
            {"id": "vwap", "name": "VWAP 量权均价", "params": STRATEGY_PARAMS_SCHEMA["vwap"]},
            {"id": "donchian_channel", "name": "唐奇安通道 (Donchian)", "params": STRATEGY_PARAMS_SCHEMA["donchian_channel"]},
        ],
        "risk_params": RISK_PARAMS_SCHEMA,
        "scan_grid": SCAN_GRID,
    })


@app.post("/api/backtest")
async def api_run_backtest(request: Request):
    """
    执行参数化回测。
    Body: {
        "symbol": "000300.SH",
        "strategy": "trend_following",
        "params": {"short_window": 10, "long_window": 30},
        "risk_params": {"commission_rate": 0.0003}
    }
    """
    body = await request.json()
    symbol = body.get("symbol", "000300.SH")
    strategy = body.get("strategy", "trend_following")
    params = body.get("params", {})
    risk_params = body.get("risk_params", {})

    # 构建 CLI 参数
    cmd = [
        "python3", "-m", "src.app.cli", "backtest",
        "--data-path", str(DATA_DIR),
        "--symbol", symbol,
        "--strategy-name", strategy,
    ]
    for k, v in params.items():
        if v is not None:
            cmd.extend([f"--{k.replace('_', '-')}", str(v)])
    for k, v in risk_params.items():
        if v is not None:
            cmd.extend([f"--{k.replace('_', '-')}", str(v)])

    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    # 读取最新报告
    reports = list_backtest_reports()
    latest = reports[0] if reports else {}
    return JSONResponse({
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip()[:500],
        "report": latest,
    })


@app.post("/api/scan")
async def api_param_scan(request: Request):
    """
    执行参数扫描（批量回测）。
    Body: {
        "symbol": "000300.SH",
        "strategy": "trend_following",
        "grid": {
            "short_window": [3, 5, 10],
            "long_window": [20, 30, 60]
        }
    }
    """
    body = await request.json()
    symbol = body.get("symbol", "000300.SH")
    strategy = body.get("strategy", "trend_following")
    grid = body.get("grid", SCAN_GRID.get(strategy, {}))

    if not grid:
        raise HTTPException(status_code=400, detail="No scan grid provided")

    # 用 itertools.product 生成所有组合
    from itertools import product
    keys = list(grid.keys())
    combos = list(product(*[grid[k] for k in keys]))

    results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        # 调用 CLI
        cmd = [
            "python3", "-m", "src.app.cli", "backtest",
            "--data-path", str(DATA_DIR),
            "--symbol", symbol,
            "--strategy-name", strategy,
        ]
        for k, v in params.items():
            cmd.extend([f"--{k.replace('_', '-')}", str(v)])

        subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )

        reports = list_backtest_reports()
        if reports:
            results.append({**reports[0], "params": params})

    # 按总收益排序
    results.sort(key=lambda x: float(x.get("total_return", "0").replace("%", "").replace("N/A", "-1")), reverse=True)
    return JSONResponse({"results": results, "count": len(results)})


@app.get("/api/equity/{run_id}")
async def api_equity(run_id: str):
    """返回指定 run_id 的净值曲线数据。"""
    rows = load_equity_curve(run_id)
    if not rows:
        # 从报告中提取事件中的 equity 信息
        data = load_report_detail(run_id)
        if data and "equity_curve" in data.get("summary", {}):
            return JSONResponse(data["summary"]["equity_curve"])
        return JSONResponse([])
    return JSONResponse(rows)


@app.get("/api/picks")
async def api_picks(days: int = 90):
    """
    返回荐股日历：所有历史荐股 + 七日复盘收益。
    
    每条记录包含：
      - 荐股日期、股票代码、名称、价格、推荐理由、评分
      - 7日追踪：最高收益、最低收益、最终收益、状态
    """
    import csv
    PUSH_FILE = REPORTS_DIR / "push_log.json"
    TRACK_FILE = REPORTS_DIR / "tracking.json"

    pushes = []
    if PUSH_FILE.exists():
        with open(PUSH_FILE, encoding="utf-8") as f:
            pushes = json.load(f).get("pushes", [])

    # 读取追踪记录，按 push_id 聚合
    tracking_map: Dict[str, Dict] = {}
    if TRACK_FILE.exists():
        with open(TRACK_FILE, encoding="utf-8") as f:
            data = json.load(f)
            for t in data.get("trackings", []):
                pid = t.get("push_id", "")
                if pid not in tracking_map:
                    tracking_map[pid] = {
                        "returns": [],
                        "highs": [],
                        "lows": [],
                    }
                tracking_map[pid]["returns"].append(t.get("return_pct", 0))
                tracking_map[pid]["highs"].append(t.get("high_price", 0))
                tracking_map[pid]["lows"].append(t.get("low_price", 0))

    # 限制天数
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    picks = []
    for p in pushes:
        push_date = p.get("push_date", "")
        if push_date < cutoff:
            continue

        pid = p.get("push_id", "")
        tdata = tracking_map.get(pid, {})
        returns = tdata.get("returns", [])

        max_return = p.get("max_return", 0) or 0
        min_return = p.get("min_return", 0) or 0
        final_return = p.get("final_return")
        status = p.get("status", "pending")

        # 从追踪数据补充
        if returns:
            max_return = max(max_return, max(returns))
            min_return = min(min_return, min(returns))
            if final_return is None:
                final_return = returns[-1] if returns else None

        picks.append({
            "push_id": pid,
            "push_date": push_date,
            "push_time": p.get("push_time", ""),
            "code": p.get("code", ""),
            "name": p.get("name", ""),
            "push_price": p.get("push_price"),
            "entry_price": p.get("entry_price"),
            "stop_loss": p.get("stop_loss"),
            "take_profit": p.get("take_profit"),
            "reason": p.get("reason", ""),
            "score": p.get("score"),
            "max_return": round(max_return, 2),
            "min_return": round(min_return, 2),
            "final_return": round(final_return, 2) if final_return is not None else None,
            "status": status,
            "exit_reason": p.get("exit_reason"),
            "tracking_days": p.get("tracking_days", 0),
        })

    # 按日期倒序
    picks.sort(key=lambda x: x["push_date"], reverse=True)
    return JSONResponse({"picks": picks, "total": len(picks)})


# ─── AI热度 ───────────────────────────────────────────────────────────────

@app.get("/api/ai-heat")
async def api_ai_heat():
    """返回AI热度仪表盘数据（当天快照 + 自动存历史 + 趋势数据）。"""
    try:
        from src.dashboard.ai_heat import run_ai_heat
        result = run_ai_heat()

        # Store snapshot to history JSON
        history_path = PROJECT_ROOT / "data" / "ai_heat_history.json"
        history = []
        if history_path.exists():
            history = json.loads(history_path.read_text())
        today = datetime.now().strftime('%Y-%m-%d')
        # Avoid duplicate same-day entries
        if not history or history[-1].get('date') != today:
            entry = {
                'date': today,
                'overall_heat': result.overall_heat,
                'level': result.level,
                'total_up_count': result.total_up_count,
                'total_count': result.total_count,
                'limit_up_total': result.limit_up_total,
                'sectors': [{'name': s.name, 'avg_change': s.avg_change} for s in result.sectors],
            }
            history.append(entry)
            # Keep last 60 days
            history = history[-60:]
            history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2))

        return JSONResponse({
            "ok": True,
            "timestamp": result.timestamp,
            "overall_heat": result.overall_heat,
            "level": result.level,
            "total_up_count": result.total_up_count,
            "total_count": result.total_count,
            "limit_up_total": result.limit_up_total,
            "one_liner": result.one_liner,
            "suggestion": result.suggestion,
            "etf_fund_flow": result.etf_fund_flow,
            "sectors": [
                {
                    "name": s.name,
                    "avg_change": s.avg_change,
                    "up_count": s.up_count,
                    "total_count": s.total_count,
                    "up_ratio": s.up_ratio,
                    "limit_up_count": s.limit_up_count,
                    "top_gainer": s.top_gainer,
                    "top_gainer_chg": s.top_gainer_chg,
                }
                for s in result.sectors
            ],
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/ai-heat-history")
async def api_ai_heat_history():
    """返回AI热度历史趋势数据（最近60天）。"""
    try:
        history_path = PROJECT_ROOT / "data" / "ai_heat_history.json"
        if not history_path.exists():
            return JSONResponse({"ok": True, "history": []})
        history = json.loads(history_path.read_text())
        return JSONResponse({"ok": True, "history": history})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ─── 对手盘热度 ────────────────────────────────────────────────────────────

@app.get("/api/counter-sector")
async def api_counter_sector():
    """返回对手盘（非AI板块）热度数据，含AI热度做对比。"""
    try:
        # 先获取AI热度做对比
        ai_heat_val = 50  # 默认
        history_path = PROJECT_ROOT / "data" / "ai_heat_history.json"
        if history_path.exists():
            history = json.loads(history_path.read_text())
            if history:
                ai_heat_val = history[-1].get('overall_heat', 50)

        from src.dashboard.counter_sector import run_counter_sector
        result = run_counter_sector(ai_heat_val)

        return JSONResponse({
            "ok": True,
            "timestamp": result.timestamp,
            "rotation_signal": result.rotation_signal,
            "best_sector": result.best_sector,
            "best_avg_chg": result.best_avg_chg,
            "worst_sector": result.worst_sector,
            "worst_avg_chg": result.worst_avg_chg,
            "total_up": result.total_up,
            "total_cnt": result.total_cnt,
            "ai_heat": result.ai_heat,
            "one_liner": result.one_liner,
            "suggestion": result.suggestion,
            "sectors": [
                {
                    "name": s.name,
                    "avg_change": s.avg_change,
                    "up_count": s.up_count,
                    "total_count": s.total_count,
                    "up_ratio": s.up_ratio,
                    "limit_up_count": s.limit_up_count,
                    "top_gainer": s.top_gainer,
                    "top_gainer_chg": s.top_gainer_chg,
                }
                for s in result.sectors
            ],
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/asia-chart")
async def api_asia_chart():
    """生成亚太指数图表并返回图片路径。"""
    try:
        from src.dashboard.asia_chart import generate_chart
        path = generate_chart()
        return JSONResponse({"ok": True, "path": path})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ─── 启动入口 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8899, reload=False)
