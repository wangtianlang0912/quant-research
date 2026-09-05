"""
板块资金轮动图 — AI vs 对手盘，同框归一化

一条折线看清：AI 涨的时候谁在跌（被抽血），AI 跌的时候谁在涨（承接）。
"""

from __future__ import annotations
import json, os, time, urllib.request
from urllib.parse import quote
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter


# ─── 板块定义 ───────────────────────────────────────
# AI 阵营 (暖色系)
AI_GROUP = {
    'AI人工智能': {'symbol': '159819.SZ', 'color': '#ef4444', 'lw': 2.2},
    '芯片半导体': {'symbol': '159995.SZ', 'color': '#f97316', 'lw': 1.8},
    '通信/CPO':  {'symbol': '515880.SS', 'color': '#eab308', 'lw': 1.8},
}

# 对手盘阵营 — 传统/防御/周期 (冷色系)
COUNTER_GROUP = {
    '银行金融':   {'symbol': '512800.SS', 'color': '#3b82f6', 'lw': 1.8},
    '医药生物':   {'symbol': '512010.SS', 'color': '#10b981', 'lw': 1.8},
    '消费必需':   {'symbol': '159928.SZ', 'color': '#8b5cf6', 'lw': 1.8},
    '煤炭周期':   {'symbol': '515220.SS', 'color': '#6b7280', 'lw': 1.5},
    '电力公用':   {'symbol': '159611.SZ', 'color': '#06b6d4', 'lw': 1.5},
}

ALL_SECTORS = {**AI_GROUP, **COUNTER_GROUP}

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(BASE, 'data', 'cache')
CHART_DIR = os.path.join(BASE, 'reports', 'charts')
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(CHART_DIR, exist_ok=True)


@dataclass
class RotationResult:
    timestamp: str
    chart_path: str
    latest_values: Dict[str, float]
    ai_avg: float
    counter_avg: float
    divergence: str  # 'AI强抽血' / '跷跷板' / '同步' / '防御强抽血'
    summary: str


# ─── 数据拉取 ───────────────────────────────────────
def fetch_all() -> Dict[str, dict]:
    """拉取全部板块 ETF 数据"""
    cache_file = os.path.join(CACHE_DIR, 'sector_rotation.json')
    today = datetime.now().strftime('%Y-%m-%d')

    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            if cached.get('date') == today:
                return cached
        except Exception:
            pass

    result = {'date': today, 'sectors': {}}
    for name, cfg in ALL_SECTORS.items():
        try:
            encoded = quote(cfg['symbol'], safe='')
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=6mo&interval=1d"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            r = data['chart']['result'][0]
            ts = r['timestamp']
            quotes = r['indicators']['quote'][0]
            closes = [q for q in quotes['close'] if q is not None]
            dates = [datetime.fromtimestamp(ts[i]).strftime('%Y-%m-%d')
                    for i in range(len(ts)) if quotes['close'][i] is not None]
            n = min(len(closes), len(dates))
            result['sectors'][name] = {'dates': dates[-n:], 'closes': closes[-n:]}
        except Exception as e:
            print(f'  ⚠️ {name} fetch failed: {e}')
        time.sleep(0.2)

    with open(cache_file, 'w') as f:
        json.dump(result, f)
    return result


def normalize(raw: Dict[str, dict]) -> Dict[str, dict]:
    """归一化到起点=100，对齐日期"""
    all_dates = set()
    for data in raw['sectors'].values():
        all_dates.update(data['dates'])
    common = sorted(all_dates)

    # 取最短板块长度的有效区间
    min_len = min(len(d['dates']) for d in raw['sectors'].values())
    use_dates = common[-min_len:]

    result = {}
    for name, data in raw['sectors'].items():
        date_map = dict(zip(data['dates'], data['closes']))
        vals, valid_dates = [], []
        for d in use_dates:
            if d in date_map:
                vals.append(date_map[d])
                valid_dates.append(d)
        if not vals or vals[0] == 0:
            continue
        norm = [v / vals[0] * 100 for v in vals]
        result[name] = {
            'dates': valid_dates,
            'norm_vals': norm,
            'change_pct': (vals[-1] / vals[0] - 1) * 100,
        }
    return result


def generate_chart(normalized: Dict[str, dict]) -> str:
    """生成图表"""
    plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'STHeiti', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False

    fig, ax = plt.subplots(figsize=(14, 7))

    # 收集所有日期
    all_dates = set()
    for data in normalized.values():
        all_dates.update(data['dates'])
    all_dates = sorted(all_dates)

    # 画 AI 阵营 (实线)
    for name, data in normalized.items():
        cfg = AI_GROUP.get(name) or COUNTER_GROUP.get(name)
        dates = [datetime.strptime(d, '%Y-%m-%d') for d in data['dates']]
        ls = 'solid' if name in AI_GROUP else 'dashed'
        lw = cfg['lw'] if cfg else 1.5
        alpha = 0.95 if name in AI_GROUP else 0.8
        ax.plot(dates, data['norm_vals'], color=cfg['color'],
                linewidth=lw, linestyle=ls, label=name, alpha=alpha)

    # 零线
    ax.axhline(y=100, color='#666', linewidth=0.5, linestyle='dotted', alpha=0.5)

    # 标注
    for name, data in normalized.items():
        dates = [datetime.strptime(d, '%Y-%m-%d') for d in data['dates']]
        cfg = AI_GROUP.get(name) or COUNTER_GROUP.get(name)
        ax.annotate(f'{name} {data["change_pct"]:+.1f}%',
                    xy=(dates[-1], data['norm_vals'][-1]),
                    xytext=(15, 0), textcoords='offset points',
                    fontsize=9, fontweight='bold' if name in AI_GROUP else 'normal',
                    color=cfg['color'], va='center')

    # 图例
    legend1 = [plt.Line2D([0], [0], color='#ef4444', lw=2, label='— AI/科技阵营')]
    legend2 = [plt.Line2D([0], [0], color='#3b82f6', lw=2, linestyle='--', label='- - 传统/防御阵营')]
    ax.legend(handles=legend1 + legend2, loc='upper left',
              fontsize=10, framealpha=0.8)

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.tick_params(axis='x', rotation=0, labelsize=9)
    ax.tick_params(axis='y', labelsize=9)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:.0f}'))

    ax.set_title(f'AI vs 对手盘 — 资金轮动 | {datetime.now().strftime("%Y-%m-%d")}',
                 fontsize=14, fontweight='bold')
    ax.set_xlabel('')
    ax.grid(True, alpha=0.2)

    plt.tight_layout()

    path = os.path.join(CHART_DIR, f'sector_rotation_{datetime.now().strftime("%Y-%m-%d")}.png')
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path


def run() -> RotationResult:
    print('[板块轮动] 拉取数据...')
    raw = fetch_all()
    normalized = normalize(raw)

    print(f'[板块轮动] {len(normalized)} 个板块就绪')

    chart_path = generate_chart(normalized)

    # 分析背离
    ai_changes = [normalized[n]['change_pct'] for n in AI_GROUP if n in normalized]
    counter_changes = [normalized[n]['change_pct'] for n in COUNTER_GROUP if n in normalized]
    ai_avg = sum(ai_changes) / len(ai_changes) if ai_changes else 0
    counter_avg = sum(counter_changes) / len(counter_changes) if counter_changes else 0

    gap = ai_avg - counter_avg
    if abs(gap) < 3:
        divergence = '同步波动 — 无明显板块轮动，全市场同涨同跌'
    elif gap > 10:
        divergence = '⚠️ AI强抽血 — 资金从传统板块大幅流向AI，注意过热风险'
    elif gap > 3:
        divergence = '🟡 偏向AI — AI跑赢传统，资金温和流入科技'
    elif gap < -10:
        divergence = '🛡️ 防御主导 — 资金逃离AI涌入防御，市场避险情绪浓'
    else:
        divergence = '🟠 偏向防御 — 传统板块跑赢AI，资金在轮出科技'

    latest_vals = {name: round(data['change_pct'], 1) for name, data in normalized.items()}
    summary = f'AI均{ai_avg:+.1f}% vs 防御均{counter_avg:+.1f}% → {divergence}'

    print(f'[板块轮动] {summary}')
    return RotationResult(
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M'),
        chart_path=chart_path,
        latest_values=latest_vals,
        ai_avg=round(ai_avg, 1),
        counter_avg=round(counter_avg, 1),
        divergence=divergence,
        summary=summary,
    )


def format_brief(r: RotationResult) -> str:
    lines = [
        f"🔄 板块轮动 | {datetime.now().strftime('%m/%d')}",
        f"",
        f"AI阵营: 人工智能 +{r.latest_values.get('AI人工智能', 0):.1f}%  芯片 +{r.latest_values.get('芯片半导体', 0):.1f}%  通信 +{r.latest_values.get('通信/CPO', 0):.1f}%",
        f"对手盘: 银行 +{r.latest_values.get('银行金融', 0):.1f}%  医药 +{r.latest_values.get('医药生物', 0):.1f}%  消费 +{r.latest_values.get('消费必需', 0):.1f}%",
        f"        煤炭 +{r.latest_values.get('煤炭周期', 0):.1f}%  电力 +{r.latest_values.get('电力公用', 0):.1f}%",
        f"",
        f"{r.divergence}",
    ]
    return '\n'.join(lines)


if __name__ == '__main__':
    r = run()
    print(format_brief(r))
    print(f'\nCHART: {r.chart_path}')
