"""
对手盘热度仪表盘 — 扫描非AI板块，观察资金轮动方向

输出：
  1. 各非AI板块各自热度/涨跌幅
  2. 资金信号（领涨板块、连板龙头、流入流出对比）
  3. AI vs 非AI 资金跷跷板判断
"""
from __future__ import annotations
import json, os, time, sys
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.data.akshare_client import TencentClient, StockQuote

__all__ = ['CounterSectorDashboard', 'CounterSectorResult', 'run_counter_sector']


# ─── 非AI板块标的池 ───────────────────────────────────
COUNTER_UNIVERSE = {
    '白电/家电': [
        'sz000333', 'sh600690', 'sz002032', 'sh603486',
    ],
    '白酒/食品消费': [
        'sh600519', 'sz000858', 'sh600887', 'sz000568',
        'sh603288', 'sh600809', 'sz002304',
    ],
    '新能源/光伏': [
        'sz300750', 'sz002594', 'sh601012', 'sh600438',
        'sz300274', 'sz300763',
    ],
    '医药/医疗': [
        'sh600276', 'sz300760', 'sh603259', 'sz300122',
        'sz300015', 'sh688180',
    ],
    '银行/金融': [
        'sh601398', 'sh601939', 'sh601288', 'sh600036',
        'sh601166', 'sh601318',
    ],
    '养殖/农业': [
        'sz002714', 'sz300498', 'sz000876', 'sh600598',
        'sz002311',
    ],
    '煤炭/有色': [
        'sh601088', 'sh601899', 'sh601225', 'sz000831',
        'sh600188',
    ],
    '房地产': [
        'sz000002', 'sh600048', 'sz001979', 'sh600383',
    ],
}


@dataclass
class CounterSector:
    """非AI板块热度"""
    name: str
    avg_change: float       
    up_count: int           
    total_count: int        
    up_ratio: float         
    limit_up_count: int     
    top_gainer: str = ""    
    top_gainer_chg: float = 0
    # 流通市值加权（估算）
    total_market_cap: float = 0  


@dataclass
class CounterResult:
    """对手盘结果"""
    timestamp: str
    sectors: List[CounterSector]
    best_sector: str          # 最热板块
    best_avg_chg: float
    worst_sector: str
    worst_avg_chg: float
    total_up: int
    total_cnt: int
    # AI对比
    ai_heat: float            # AI综合热度（外部传入）
    rotation_signal: str      # 轮动信号: AI主导/均衡/对手盘主导
    one_liner: str
    suggestion: str


class CounterSectorDashboard:

    def __init__(self, ai_heat: float = 0):
        self.client = TencentClient()
        self.ai_heat = ai_heat

    def run(self, ai_heat: float = 0) -> CounterResult:
        self.ai_heat = ai_heat
        t0 = time.time()

        all_codes = []
        for codes in COUNTER_UNIVERSE.values():
            all_codes.extend(codes)
        all_codes = list(set(all_codes))

        quotes = self.client._get_quotes(all_codes)
        quote_map = {q.code: q for q in quotes if q.price > 0}
        print(f"[对手盘] 行情获取 {len(quote_map)}/{len(all_codes)} 只, {time.time()-t0:.1f}s")

        sectors = []
        total_up = 0
        total_cnt = 0

        for sector_name, codes in COUNTER_UNIVERSE.items():
            sec = self._calc_sector(sector_name, codes, quote_map)
            sectors.append(sec)
            total_up += sec.up_count
            total_cnt += sec.total_count

        # 排序
        sectors.sort(key=lambda x: x.avg_change, reverse=True)

        best = sectors[0]
        worst = sectors[-1]

        # 轮动信号
        counter_avg = sum(s.avg_change for s in sectors) / len(sectors) if sectors else 0
        rotation, one_liner, suggestion = self._gen_signals(sectors, counter_avg)

        return CounterResult(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M'),
            sectors=sectors,
            best_sector=best.name,
            best_avg_chg=best.avg_change,
            worst_sector=worst.name,
            worst_avg_chg=worst.avg_change,
            total_up=total_up,
            total_cnt=total_cnt,
            ai_heat=self.ai_heat,
            rotation_signal=rotation,
            one_liner=one_liner,
            suggestion=suggestion,
        )

    def _calc_sector(self, name: str, codes: List[str], quote_map: Dict) -> CounterSector:
        changes = []
        up_count = 0
        limit_up = 0
        top_name = ""
        top_chg = -999

        for code in codes:
            lookup = code[2:] if (code.startswith('sh') or code.startswith('sz')) else code
            q = quote_map.get(lookup) or quote_map.get(code)
            if q is None:
                continue
            chg = q.change_pct
            changes.append(chg)
            if chg > 0:
                up_count += 1
            if chg >= 10:
                limit_up += 1
            if chg > top_chg:
                top_chg = chg
                top_name = q.name

        total = len(changes)
        avg_chg = sum(changes) / total if total > 0 else 0
        up_ratio = up_count / total if total > 0 else 0

        return CounterSector(
            name=name,
            avg_change=round(avg_chg, 2),
            up_count=up_count,
            total_count=total,
            up_ratio=round(up_ratio, 2),
            limit_up_count=limit_up,
            top_gainer=top_name,
            top_gainer_chg=top_chg,
        )

    def _gen_signals(self, sectors: List[CounterSector], counter_avg: float) -> Tuple[str, str, str]:
        """生成轮动信号"""

        # 找最热和最冷板块
        best = sectors[0]
        worst = sectors[-1]

        # 判断资金方向
        if self.ai_heat > 60 and counter_avg < 0:
            rotation = "🤖 AI吸金"
            one_liner = f"AI板块持续火热({self.ai_heat:.0f}/100)，非AI普遍承压。{best.name}勉强支撑{best.avg_change:+.1f}%，{worst.name}下跌{worst.avg_change:+.1f}%。资金集中在AI方向。"
            suggestion = "AI强势期，非AI板块暂不参与。关注AI回调后的高低切换机会。"
        elif self.ai_heat < 30 and counter_avg > 0.5:
            rotation = "🔄 轮动至非AI"
            one_liner = f"AI降温({self.ai_heat:.0f}/100)，资金转向非AI。{best.name}领涨{best.avg_change:+.1f}%，{best.up_count}/{best.total_count}只上涨。跷跷板效应明显。"
            suggestion = f"关注领涨板块{best.name}，如{best.top_gainer}等龙头。AI退潮期宜防守，配置高股息+消费。"
        elif self.ai_heat > 50 and counter_avg > 0:
            rotation = "🌐 普涨格局"
            one_liner = f"AI({self.ai_heat:.0f}/100)+非AI({counter_avg:+.1f}%)齐涨。{best.name}领涨{best.avg_change:+.1f}%，市场情绪好。"
            suggestion = "全面牛市特征，AI可追趋势、非AI可埋伏低位补涨。注意仓位不要过重。"
        else:
            rotation = "🥶 全面低迷"
            one_liner = f"AI({self.ai_heat:.0f}/100)+非AI({counter_avg:+.1f}%)双双走弱。{worst.name}领跌{worst.avg_change:+.1f}%。市场情绪冰点。"
            suggestion = "防御为主，关注高股息银行板块做避风港，等待市场回暖信号。"

        return rotation, one_liner, suggestion

    def format_report(self, result: CounterResult) -> str:
        lines = [
            "━" * 28,
            f"🏢 对手盘热度 | {result.timestamp}",
            f"   {result.rotation_signal}",
            f"   全板块: {result.total_up}/{result.total_cnt}只上涨",
            f"   最强: {result.best_sector} {result.best_avg_chg:+.1f}%",
            f"   最弱: {result.worst_sector} {result.worst_avg_chg:+.1f}%",
            "━" * 28,
        ]
        for s in result.sectors:
            emoji = '🟢' if s.avg_change > 1 else '🟡' if s.avg_change > -0.5 else '🔴'
            lines.append(
                f"  {emoji} {s.name:10s}  {s.avg_change:+5.1f}%  "
                f"涨{s.up_count}/{s.total_count}  "
                f"领涨:{s.top_gainer}({s.top_gainer_chg:+.1f}%)"
            )
        lines.append("")
        lines.append(f"  📝 {result.one_liner}")
        lines.append(f"  💡 {result.suggestion}")
        lines.append("━" * 28)
        return '\n'.join(lines)


def run_counter_sector(ai_heat: float = 0) -> CounterResult:
    dash = CounterSectorDashboard(ai_heat)
    return dash.run(ai_heat)


if __name__ == '__main__':
    dash = CounterSectorDashboard()
    result = dash.run()
    print(dash.format_report(result))
