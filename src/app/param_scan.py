"""参数扫描：Grid Search 找最优参数组合。"""
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, Any, List
from itertools import product


@dataclass
class ScanResult:
    symbol: str
    strategy: str
    params: Dict[str, Any]
    total_return: float
    annualized: float
    max_drawdown: float
    sharpe: float

    def score(self) -> float:
        return self.sharpe * 0.6 + self.annualized * 10 * 0.4


def _run_one(symbol: str, strategy: str, params: dict) -> ScanResult:
    if strategy == "trend_following":
        extra = f"--short-window {params['short_window']} --long-window {params['long_window']}"
    else:
        extra = (f"--lookback-window {params['lookback_window']} "
                 f"--entry-zscore {params['entry_zscore']} --exit-zscore {params['exit_zscore']}")

    cmd = f"python3 -m src.app.cli backtest --data-path data --symbol {symbol} --strategy-name {strategy} {extra}"
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                          cwd="/Users/leihen/.qclaw/workspace/quant-research")
    for line in (out.stdout + out.stderr).splitlines():
        if line.startswith("run_id="):
            parts = dict(p.split("=", 1) for p in line.split() if "=" in p)
            return ScanResult(
                symbol=symbol, strategy=strategy, params=params,
                total_return=float(parts.get("total_return", 0)) * 100,
                annualized=float(parts.get("annualized_return", 0)) * 100,
                max_drawdown=float(parts.get("max_drawdown", 0)) * 100,
                sharpe=float(parts.get("sharpe_ratio", 0)),
            )
    return None


def scan_tf(symbol: str) -> List[ScanResult]:
    results = []
    for sw, lw in product([5, 10, 15, 20, 30], [20, 40, 60, 90, 120]):
        if sw >= lw:
            continue
        r = _run_one(symbol, "trend_following", {"short_window": sw, "long_window": lw})
        if r:
            results.append(r)
            print(f"  TF sw={sw} lw={lw} -> ret={r.total_return:+.2f}% sharpe={r.sharpe:.2f}", flush=True)
    return results


def scan_mr(symbol: str) -> List[ScanResult]:
    results = []
    for lb, ez, xz in product([10, 15, 20, 30, 40], [0.5, 0.75, 1.0, 1.5], [0.2, 0.3, 0.5]):
        if xz >= ez:
            continue
        r = _run_one(symbol, "mean_reversion", {"lookback_window": lb, "entry_zscore": ez, "exit_zscore": xz})
        if r:
            results.append(r)
            print(f"  MR lb={lb} ez={ez} xz={xz} -> ret={r.total_return:+.2f}% sharpe={r.sharpe:.2f}", flush=True)
    return results


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "00700.HK"
    print(f"=== 扫描 {symbol} ===")
    tf = scan_tf(symbol)
    mr = scan_mr(symbol)
    all_r = sorted(tf + mr, key=lambda x: x.score(), reverse=True)
    print(f"\n{'='*80}")
    print(f"  {symbol} TOP 10 综合评分")
    print(f"{'='*80}")
    print(f"{'#':>3} {'策略':16s} {'参数':35s} {'总收益':>8s} {'年化':>7s} {'回撤':>7s} {'Sharpe':>6s} {'评分':>6s}")
    print("-"*80)
    for i, r in enumerate(all_r[:10], 1):
        pstr = " ".join(f"{k}={v}" for k, v in r.params.items())
        print(f"{i:>3} {r.strategy:16s} {pstr:<35s} {r.total_return:>+7.2f}% {r.annualized:>+6.2f}% {r.max_drawdown:>7.2f}% {r.sharpe:>6.2f} {r.score():>6.3f}")
