"""
亚太主要指数 90日走势对比 — 折线图
数据源: A股=腾讯K线, 日韩=本地缓存插值, 港股=腾讯行情(仅页脚)
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.data.akshare_client import TencentClient

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_FILE = os.path.join(BASE, 'data', 'cache', 'asia_indices.json')

A_INDICES = {
    'sh000001': {'label': '上证指数', 'color': '#E60012', 'lw': 2.0, 'ls': '-'},
    'sz399001': {'label': '深证成指', 'color': '#00B050', 'lw': 1.6, 'ls': '-'},
    'sz399006': {'label': '创业板指', 'color': '#FF6600', 'lw': 1.6, 'ls': '-'},
    'sh000688': {'label': '科创50',   'color': '#7030A0', 'lw': 1.6, 'ls': '--'},
}

JP_KR = {
    'nikkei225': {'label': '日经225',   'color': '#D62728', 'lw': 1.6, 'ls': '-.'},
    'kospi':     {'label': '韩国KOSPI', 'color': '#1F77B4', 'lw': 1.8, 'ls': ':'},
    'sti':       {'label': '新加坡STI', 'color': '#2CA02C', 'lw': 1.4, 'ls': '--'},
}

HK_INDICES = ['hkHSI', 'hkHSCEI', 'hkHSTECH']


def _load_jp_kr() -> dict:
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}


def _interpolate_values(history: dict, base: date, ndays: int) -> tuple:
    """返回 (date字符串列表, 值列表), 线性插值补全稀疏点"""
    pts = [(date.fromisoformat(ds), v) for ds, v in history.items()
           if (base - date.fromisoformat(ds)).days <= ndays]
    pts.sort()
    if not pts:
        return [], []

    full = [pts[0][0] + timedelta(days=i)
            for i in range((base - pts[0][0]).days + 1)]
    full = [d for d in full if d.weekday() < 5]
    if not full:
        return [], []

    vals, pi = [], 0
    for d in full:
        while pi + 1 < len(pts) and pts[pi + 1][0] <= d:
            pi += 1
        if pi + 1 < len(pts):
            p0, p1 = pts[pi], pts[pi + 1]
            gap = (p1[0] - p0[0]).days
            vals.append(p0[1] + ((p1[1] - p0[1]) * (d - p0[0]).days / gap) if gap else p0[1])
        else:
            vals.append(pts[pi][1])

    return [d.strftime('%m-%d') for d in full], vals


class AsiaMarketChart:
    def __init__(self, lookback_days: int = 90):
        self.lookback = lookback_days
        self.client = TencentClient()

    def generate(self, output_path: str = None) -> str:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties, fontManager

        for f in ['/System/Library/Fonts/STHeiti Medium.ttc', '/System/Library/Fonts/PingFang.ttc']:
            if os.path.exists(f):
                fontManager.addfont(f)
        plt.rcParams['font.family'] = 'Heiti TC'
        plt.rcParams['axes.unicode_minus'] = False

        fp_title = FontProperties(size=13, weight='bold')
        fp_legend = FontProperties(size=7.5)
        fp_tick = FontProperties(size=6.5)
        fp_footer = FontProperties(size=7)

        fig, ax = plt.subplots(figsize=(18, 7.5))
        today = date.today()
        n_days = self.lookback

        # ── 1. A股 — K线归一化 ──
        for code, cfg in A_INDICES.items():
            try:
                kls = self.client.get_kline(code, days=n_days)
                if not kls or len(kls) < 5:
                    continue
                closes = [k.close for k in kls]
                base = closes[0]
                if base <= 0:
                    continue
                norm = [c / base * 100 for c in closes]
                x = list(range(len(norm)))
                ax.plot(x, norm, color=cfg['color'], linewidth=cfg['lw'],
                        linestyle=cfg['ls'], label=cfg['label'], alpha=0.85)
                # 末端标注
                ax.annotate(f"{cfg['label']} {norm[-1]:.0f}",
                           xy=(x[-1], norm[-1]), fontsize=6, color=cfg['color'],
                           alpha=0.75, xytext=(4, 0), textcoords='offset points',
                           fontproperties=fp_tick)
            except:
                pass

        # ── 2. 日韩 — 缓存插值归一化 ──
        cache = _load_jp_kr()
        for key, cfg in JP_KR.items():
            data = cache.get(key, {})
            history = dict(data.get('history', {}))
            if not history:
                continue
            history[today.isoformat()] = data.get('current', 0)
            _, vals = _interpolate_values(history, today, n_days)
            if len(vals) < 3:
                continue
            base = vals[0] if vals[0] > 0 else 1
            norm = [v / base * 100 for v in vals]
            x = list(range(len(norm)))
            ax.plot(x, norm, color=cfg['color'], linewidth=cfg['lw'],
                    linestyle=cfg['ls'], label=cfg['label'], alpha=0.55)
            ax.annotate(f"{cfg['label']} {norm[-1]:.0f}",
                       xy=(x[-1], norm[-1]), fontsize=6, color=cfg['color'],
                       alpha=0.65, xytext=(4, 0), textcoords='offset points',
                       fontproperties=fp_tick)

        # ── 3. X轴标签 (只标月初 + 关键点) ──
        tick_positions = [0, 20, 40, 60]
        tick_labels = [f'D-{n_days}', f'D-{n_days-20}', f'D-{n_days-40}', f'D-{n_days-60}']
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, fontproperties=fp_tick)

        # ── 4. 港股页脚 ──
        hk_notes = []
        try:
            hk_q = self.client._get_quotes(HK_INDICES)
            hk_map = {'hkHSI': '恒生', 'hkHSCEI': '国企', 'hkHSTECH': '恒生科技'}
            for q in hk_q:
                hk_notes.append(f"{hk_map.get(q.code, q.code)} {q.change_pct:+.1f}%")
        except:
            pass

        # ── 5. 收尾 ──
        ax.axhline(y=100, color='gray', linestyle='--', alpha=0.25, linewidth=0.7)
        ax.set_title('亚太主要指数 90日走势对比 (归一化, 基准=100)', fontproperties=fp_title)
        ax.set_ylabel('归一化', fontproperties=fp_tick)
        ax.grid(True, alpha=0.12)
        ax.legend(loc='upper left', prop=fp_legend, framealpha=0.85, ncol=3)

        footer = []
        if hk_notes:
            footer.append('港股今日: ' + ' | '.join(hk_notes))
        footer.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 小Q量化')
        fig.text(0.5, 0.005, '  ·  '.join(footer),
                ha='center', fontsize=7, color='#888888', fontproperties=fp_footer)

        plt.tight_layout(rect=[0, 0.05, 1, 0.95])

        if output_path is None:
            out_dir = os.path.join(BASE, 'reports', 'charts')
            os.makedirs(out_dir, exist_ok=True)
            output_path = os.path.join(out_dir,
                                       f'asia_market_{datetime.now().strftime("%Y-%m-%d")}.png')
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"✅ 图表: {output_path}")
        return output_path


def generate_chart(lookback: int = 90, output_path: str = None) -> str:
    return AsiaMarketChart(lookback_days=lookback).generate(output_path)


if __name__ == '__main__':
    generate_chart()
