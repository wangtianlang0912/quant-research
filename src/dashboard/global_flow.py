"""
全球资金流向仪表盘 — 归一化走势图 + 交叉预警

7 大市场指数归一化到同一基准(起点=100):
  A股(上证) / 港股(恒生) / 日经225 / 韩国KOSPI / 新加坡STI / 标普500 / 纳斯达克

交叉检测: 任意两条线在过去N天内发生穿越 → 资金跨市场流动信号
"""
from __future__ import annotations
import json, os, urllib.request, time, sys
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

__all__ = ['GlobalFlowDashboard', 'CrossSignal', 'FlowResult', 'run_global_flow']


# ─── 指数定义 ────────────────────────────────────────
INDICES = {
    '上证综指': {'symbol': '000001.SS', 'region': 'A股', 'color': '#ef4444', 'label': '[SH]'},
    '深证成指': {'symbol': '399001.SZ', 'region': 'A股', 'color': '#dc2626', 'label': '[SZ]'},
    '恒生指数': {'symbol': '^HSI',    'region': '港股', 'color': '#f59e0b', 'label': '[HK]'},
    '日经225':  {'symbol': '^N225',   'region': '日股', 'color': '#8b5cf6', 'label': '[JP]'},
    'KOSPI':    {'symbol': '^KS11',   'region': '韩股', 'color': '#10b981', 'label': '[KR]'},
    '新加坡STI': {'symbol': '^STI',   'region': '新加坡', 'color': '#06b6d4', 'label': '[SG]'},
    '标普500':  {'symbol': '^GSPC',   'region': '美股', 'color': '#3b82f6', 'label': '[US]'},
    '纳斯达克':  {'symbol': '^IXIC',   'region': '美股', 'color': '#6366f1', 'label': '[NA]'},
    '黄金':      {'symbol': 'GC=F',   'region': '商品', 'color': '#fbbf24', 'label': '[GOLD]', 'linewidth': 2.5, 'linestyle': 'dashdot'},
}

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'cache')
CHART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'reports', 'charts')
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(CHART_DIR, exist_ok=True)


@dataclass
class CrossSignal:
    """交叉信号"""
    date: str
    line_a: str  # 上穿的那根线
    line_b: str  # 被穿的线
    direction: str  # 'up' (A上穿B) or 'down' (A下穿B)
    significance: str  # 'major' (跨市场) or 'minor' (同市场)
    desc: str


@dataclass
class FlowResult:
    """资金流向结果"""
    timestamp: str
    chart_path: str
    signals_7d: List[CrossSignal]   # 近7天交叉
    signals_30d: List[CrossSignal]  # 近30天交叉
    summary: str                    # 一句话总结
    alert: str                      # 预警信息（有交叉才非空）
    latest_values: Dict[str, float] # 各指数最新值
    cross_count_7d: int
    cross_count_30d: int


class GlobalFlowDashboard:
    """全球资金流向仪表盘"""

    def __init__(self):
        self._data = {}  # name -> {dates, norm_vals}

    def fetch_all(self) -> Dict[str, dict]:
        """拉取全部指数数据，缓存到本地"""
        cache_file = os.path.join(CACHE_DIR, 'global_indices.json')
        
        # 检查缓存（当天有效）
        today = datetime.now().strftime('%Y-%m-%d')
        if os.path.exists(cache_file):
            try:
                with open(cache_file) as f:
                    cached = json.load(f)
                if cached.get('date') == today:
                    return cached
            except Exception:
                pass

        result = {'date': today, 'indices': {}}
        for name, cfg in INDICES.items():
            try:
                from urllib.parse import quote
                symbol_encoded = quote(cfg['symbol'], safe='')
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol_encoded}?range=6mo&interval=1d"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                resp = urllib.request.urlopen(req, timeout=10)
                data = json.loads(resp.read())
                r = data['chart']['result'][0]
                ts = r['timestamp']
                quotes = r['indicators']['quote'][0]
                closes = [q for q in quotes['close'] if q is not None]
                dates = [datetime.fromtimestamp(ts[i]).strftime('%Y-%m-%d') 
                        for i in range(len(ts)) if quotes['close'][i] is not None]
                # Trim to same length
                n = min(len(closes), len(dates))
                result['indices'][name] = {
                    'dates': dates[-n:],
                    'closes': closes[-n:],
                }
            except Exception as e:
                print(f'  ⚠️ {name} fetch failed: {e}')
            time.sleep(0.3)

        with open(cache_file, 'w') as f:
            json.dump(result, f)
        return result

    def normalize(self, raw_data: dict) -> Dict[str, dict]:
        """将所有指数归一化到起点=100，并对齐日期"""
        # 找到共有日期范围
        all_dates = set()
        for name, data in raw_data['indices'].items():
            all_dates.update(data['dates'])
        common_dates = sorted(all_dates)

        # 取中间某段（跳过开头数据不齐的问题）
        min_len = min(len(data['dates']) for data in raw_data['indices'].values())
        # 对齐到最短指数长度的最后 N 天
        use_dates = common_dates[-min_len:]

        normalized = {}
        for name, data in raw_data['indices'].items():
            # 建立 date->close 映射
            date_map = dict(zip(data['dates'], data['closes']))
            vals = []
            valid_dates = []
            for d in use_dates:
                if d in date_map:
                    vals.append(date_map[d])
                    valid_dates.append(d)
            if not vals:
                continue
            base = vals[0]
            if base == 0:
                continue
            norm_vals = [v / base * 100 for v in vals]
            normalized[name] = {
                'dates': valid_dates,
                'norm_vals': norm_vals,
                'latest': vals[-1],
                'change_pct': (vals[-1] / vals[0] - 1) * 100,
            }

        return normalized

    def detect_crossovers(self, normalized: Dict[str, dict], lookback_days: int) -> List[CrossSignal]:
        """检测近N天内的交叉信号"""
        names = list(normalized.keys())
        signals = []

        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a = names[i]
                b = names[j]
                a_vals = normalized[a]['norm_vals']
                b_vals = normalized[b]['norm_vals']
                a_dates = normalized[a]['dates']
                b_dates = normalized[b]['dates']

                # 对齐
                common_dates = sorted(set(a_dates) & set(b_dates))
                a_map = dict(zip(a_dates, a_vals))
                b_map = dict(zip(b_dates, b_vals))
                a_aligned = [a_map[d] for d in common_dates]
                b_aligned = [b_map[d] for d in common_dates]

                if len(a_aligned) < lookback_days + 2:
                    continue

                # 只看最近N天
                recent_a = a_aligned[-lookback_days - 1:]
                recent_b = b_aligned[-lookback_days - 1:]
                recent_dates = common_dates[-lookback_days - 1:]

                for k in range(1, len(recent_a)):
                    prev_diff = recent_a[k-1] - recent_b[k-1]
                    curr_diff = recent_a[k] - recent_b[k]

                    if prev_diff == 0:
                        continue

                    if prev_diff < 0 and curr_diff > 0:
                        # A 上穿 B
                        significance = 'major' if INDICES[a]['region'] != INDICES[b]['region'] else 'minor'
                        desc = f"{a} 上穿 {b} → 资金从 {INDICES[b]['region']} 流向 {INDICES[a]['region']}"
                        signals.append(CrossSignal(
                            date=recent_dates[k],
                            line_a=a, line_b=b,
                            direction='up',
                            significance=significance,
                            desc=desc,
                        ))
                    elif prev_diff > 0 and curr_diff < 0:
                        # A 下穿 B
                        significance = 'major' if INDICES[a]['region'] != INDICES[b]['region'] else 'minor'
                        desc = f"{a} 下穿 {b} → 资金从 {INDICES[a]['region']} 流向 {INDICES[b]['region']}"
                        signals.append(CrossSignal(
                            date=recent_dates[k],
                            line_a=a, line_b=b,
                            direction='down',
                            significance=significance,
                            desc=desc,
                        ))

        return signals

    def generate_chart(self, normalized: Dict[str, dict], signals_7d: List[CrossSignal]) -> str:
        """生成归一化走势图"""
        plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'Arial Unicode MS', 'SimHei']
        plt.rcParams['axes.unicode_minus'] = False

        fig, ax = plt.subplots(figsize=(14, 7))
        fig.patch.set_facecolor('#1a1d27')
        ax.set_facecolor('#1a1d27')

        all_dates = []
        for name, data in normalized.items():
            cfg = INDICES[name]
            dates = [datetime.strptime(d, '%Y-%m-%d') for d in data['dates']]
            lw = cfg.get('linewidth', 1.8)
            ls = cfg.get('linestyle', 'solid')
            alpha = 1.0 if name == '黄金' else 0.85
            ax.plot(dates, data['norm_vals'], color=cfg['color'], 
                    linewidth=lw, linestyle=ls, label=f"{cfg['label']} {name}", alpha=alpha)
            all_dates.extend(dates)

        # 标注交叉点
        signal_dates_set = set()
        for s in signals_7d:
            if s.date not in signal_dates_set and s.significance == 'major':
                signal_dates_set.add(s.date)
                # 找这个日期对应的 y 值
                for name, data in normalized.items():
                    if s.date in data['dates']:
                        idx = data['dates'].index(s.date)
                        y = data['norm_vals'][idx]
                        ax.annotate('X', xy=(datetime.strptime(s.date, '%Y-%m-%d'), y),
                                    fontsize=12, ha='center', va='center',
                                    color='#facc15', fontweight='bold',
                                    bbox=dict(boxstyle='circle,pad=0.2', facecolor='#ef4444', 
                                             edgecolor='none', alpha=0.85))
                        break

        # 基准线
        if all_dates:
            ax.axhline(y=100, color='#64748b', linestyle='--', linewidth=0.8, alpha=0.5)

        # 格式
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        plt.xticks(rotation=45, color='#94a3b8', fontsize=9)
        plt.yticks(color='#94a3b8', fontsize=9)
        ax.tick_params(colors='#94a3b8')
        ax.grid(True, alpha=0.15, color='#64748b')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#2a2d3e')
        ax.spines['bottom'].set_color('#2a2d3e')

        ax.set_title('全球资金流向 | 归一化走势 (起点=100)', 
                     color='#e2e8f0', fontsize=14, fontweight='bold', pad=15)
        ax.set_ylabel('归一化值 (100 = 基线)', color='#94a3b8', fontsize=10)

        leg = ax.legend(loc='upper left', fontsize=8, framealpha=0.8,
                       facecolor='#21253a', edgecolor='#2a2d3e',
                       labelcolor='#e2e8f0', ncol=2)
        leg.get_frame().set_linewidth(0.5)

        plt.tight_layout()

        today = datetime.now().strftime('%Y-%m-%d')
        path = os.path.join(CHART_DIR, f'global_flow_{today}.png')
        plt.savefig(path, dpi=150, facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close()
        return path

    def run(self) -> FlowResult:
        """执行完整分析"""
        print('[全球资金流] 拉取指数数据...')
        raw = self.fetch_all()
        normalized = self.normalize(raw)

        # 交叉检测
        signals_30d = self.detect_crossovers(normalized, 30)
        signals_7d = self.detect_crossovers(normalized, 7)

        # 生成图表
        chart_path = self.generate_chart(normalized, signals_7d)

        # 总结
        major_crosses = [s for s in signals_7d if s.significance == 'major']
        latest_vals = {name: round(data['change_pct'], 1) 
                      for name, data in normalized.items()}

        if major_crosses:
            summary = f"⚠️ 近7天发生 {len(major_crosses)} 次跨市场交叉，资金正在流动！"
            alert = '\n'.join([f"• {s.desc} ({s.date})" for s in major_crosses])
        elif signals_7d:
            summary = f"近7天发生 {len(signals_7d)} 次同市场交叉，无重大跨市场信号。"
            alert = f"同市场内轮动，不触发预警。"
        else:
            summary = "近7天无交叉信号，资金流向稳定。"
            alert = ""

        print(f'[全球资金流] 完成: 7d交叉{len(signals_7d)}次, 30d交叉{len(signals_30d)}次')

        return FlowResult(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M'),
            chart_path=chart_path,
            signals_7d=signals_7d,
            signals_30d=signals_30d,
            summary=summary,
            alert=alert,
            latest_values=latest_vals,
            cross_count_7d=len(signals_7d),
            cross_count_30d=len(signals_30d),
        )

    def format_brief(self, r: FlowResult) -> str:
        """微信推送简洁版"""
        lines = [
            f"🌏 全球资金流向 | {datetime.now().strftime('%m/%d')}",
            f"{r.summary}",
        ]
        if r.alert:
            lines.append(r.alert)
        # 各市场涨跌
        lines.append("")
        lines.append("📊 各市场相对涨跌（基准化）:")
        sorted_vals = sorted(r.latest_values.items(), key=lambda x: x[1], reverse=True)
        for name, chg in sorted_vals:
            cfg = INDICES[name]
            arrow = '🟢' if chg > 0 else '🔴'
            lines.append(f"  {cfg['label']} {name:8s} {chg:+6.1f}%")
        lines.append("")
        lines.append(f"💡 近30天共 {r.cross_count_30d} 次交叉")
        return '\n'.join(lines)


def run_global_flow() -> FlowResult:
    dash = GlobalFlowDashboard()
    return dash.run()


if __name__ == '__main__':
    dash = GlobalFlowDashboard()
    r = dash.run()
    print(dash.format_brief(r))
    print(f"\n📈 图表: {r.chart_path}")
