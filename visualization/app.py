"""
quant-research 可视化面板
FastAPI 后端 + Chart.js 前端

运行: python3.11 -m visualization.app
访问: http://localhost:8899
"""
from __future__ import annotations

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
DATA_DIR = PROJECT_ROOT / "data" / "1d"
REPORTS_DIR = PROJECT_ROOT / "reports"

app = FastAPI(title="Quant Research Dashboard", version="1.0.0")

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ─── 数据层 ────────────────────────────────────────────────────────────────

def list_available_symbols() -> list[dict]:
    """扫描 data/ 目录，返回所有可用标的。"""
    symbols = []
    for csv_file in DATA_DIR.glob("*.csv"):
        symbol = csv_file.stem
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
        symbols.append({
            "symbol": symbol,
            "rows": row_count,
            "start_date": first_ts,
            "end_date": last_ts,
            "file_size_kb": round(stat.st_size / 1024, 1),
        })
    return sorted(symbols, key=lambda x: x["symbol"])


def load_csv_timeseries(symbol: str, start: str = "", end: str = "") -> list[dict]:
    """加载 K 线时序数据。"""
    csv_path = DATA_DIR / f"{symbol}.csv"
    if not csv_path.exists():
        return []
    rows = []
    with open(csv_path) as f:
        header = f.readline().strip().split(",")
    with open(csv_path) as f:
        next(f)
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 5:
                continue
            ts = parts[0][:19]
            if start and ts < start:
                continue
            if end and ts > end:
                continue
            try:
                rows.append({
                    "timestamp": ts,
                    "open": float(parts[1]),
                    "high": float(parts[2]),
                    "low": float(parts[3]),
                    "close": float(parts[4]),
                    "volume": float(parts[5]) if len(parts) > 5 else 0.0,
                })
            except ValueError:
                continue
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


# ─── 启动入口 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8899, reload=False)
