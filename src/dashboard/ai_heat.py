"""
AI 热度仪表盘 — 每日扫描AI板块关键标的，量化市场热度

输出：
  1. AI综合热度评分 (0-100)
  2. 五大细分板块各自热度
  3. 资金信号（涨停数/量能/ETF流入）
  4. 一句话结论 + 策略建议
"""
from __future__ import annotations
import json, os, time, sys
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.data.akshare_client import TencentClient, StockQuote

__all__ = ['AIHeatDashboard', 'AIHeatResult', 'run_ai_heat']


# ─── AI板块标的池 ───────────────────────────────────
AI_UNIVERSE = {
    'AI芯片/算力': [
        'sh688256', 'sh688981', 'sh688041', 'sh688047', 'sh688525',
        'sz002049', 'sh603986', 'sz300474', 'sh688008',
    ],
    'CPO/光模块': [
        'sz300308', 'sz300502', 'sz300394', 'sz300548', 'sz300570',
        'sh688498', 'sz300620',
    ],
    'AI应用/软件': [
        'sz002230', 'sz300033', 'sz300624', 'sh688111',
        'sh688083', 'sh688095', 'sz300663', 'sz300377',
    ],
    'AI+机器人': [
        'sz300124', 'sz300024', 'sz002747', 'sh688017', 'sz002527',
        'sh603728', 'sz300660',
    ],
    '存储/半导体': [
        'sh688525', 'sz002916', 'sh688385', 'sh688126',
        'sz300223', 'sh688234', 'sh603501',
    ],
}


@dataclass
class SectorHeat:
    """板块热度"""
    name: str
    avg_change: float        # 平均涨跌幅%
    up_count: int            # 上涨家数
    total_count: int         # 总家数
    up_ratio: float          # 上涨比例
    limit_up_count: int      # 涨停/涨超10%家数
    avg_volume_ratio: float  # 平均量比(简化:成交额/20日均)
    top_gainer: str = ""     # 领涨股
    top_gainer_chg: float = 0


@dataclass 
class AIHeatResult:
    """AI热度结果"""
    timestamp: str
    overall_heat: float         # 综合热度 0-100
    level: str                  # 冰点/冷/温/热/沸腾
    sectors: List[SectorHeat]
    total_up_count: int
    total_count: int
    limit_up_total: int
    etf_fund_flow: str          # ETF资金流向简述
    one_liner: str              # 一句话
    suggestion: str             # 策略建议


class AIHeatDashboard:
    """AI热度仪表盘"""

    def __init__(self):
        self.client = TencentClient()

    def run(self) -> AIHeatResult:
        t0 = time.time()

        # 1. 拉取所有标的行情
        all_codes = []
        for codes in AI_UNIVERSE.values():
            all_codes.extend(codes)
        all_codes = list(set(all_codes))

        quotes = self.client._get_quotes(all_codes)
        # quote.code 无前缀(如"688256")，统一用无前缀key
        quote_map = {q.code: q for q in quotes if q.price > 0}
        print(f"[AI热度] 行情获取 {len(quote_map)}/{len(all_codes)} 只, {time.time()-t0:.1f}s")

        # 2. 逐板块计算
        sectors = []
        total_up = 0
        total_cnt = 0
        limit_up_total = 0

        for sector_name, codes in AI_UNIVERSE.items():
            sec = self._calc_sector(sector_name, codes, quote_map)
            sectors.append(sec)
            total_up += sec.up_count
            total_cnt += sec.total_count
            limit_up_total += sec.limit_up_count

        # 3. 计算综合热度
        overall = self._calc_overall(sectors, total_up, total_cnt, limit_up_total)

        # 4. 判定热度等级
        if overall >= 80:
            level = '🔥🔥 沸腾'
        elif overall >= 60:
            level = '🔥 热'
        elif overall >= 40:
            level = '🌡 温'
        elif overall >= 20:
            level = '❄️ 冷'
        else:
            level = '🧊 冰点'

        # 5. 生成结论和建议
        one_liner, suggestion = self._gen_conclusion(sectors, overall, level)

        return AIHeatResult(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M'),
            overall_heat=round(overall, 1),
            level=level,
            sectors=sectors,
            total_up_count=total_up,
            total_count=total_cnt,
            limit_up_total=limit_up_total,
            etf_fund_flow=self._get_etf_flow(),
            one_liner=one_liner,
            suggestion=suggestion,
        )

    def _calc_sector(self, name: str, codes: List[str], quote_map: Dict) -> SectorHeat:
        changes = []
        up_count = 0
        limit_up = 0
        top_name = ""
        top_chg = -999

        for code in codes:
            # 去掉sh/sz前缀匹配quote_map
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

        return SectorHeat(
            name=name,
            avg_change=round(avg_chg, 2),
            up_count=up_count,
            total_count=total,
            up_ratio=round(up_ratio, 2),
            limit_up_count=limit_up,
            avg_volume_ratio=0,  # K线数据太慢，暂跳过
            top_gainer=top_name,
            top_gainer_chg=top_chg,
        )

    def _calc_overall(self, sectors: List[SectorHeat], total_up: int,
                      total_cnt: int, limit_up_total: int) -> float:
        """综合热度 = 涨跌幅40% + 广度30% + 涨停数20% + 板块分化10%"""
        if total_cnt == 0:
            return 0

        # 平均涨跌幅 → 映射到0-40
        avg_chg = sum(s.avg_change for s in sectors) / len(sectors)
        chg_score = min(max(avg_chg / 10 * 40, 0), 40)  # 10%涨幅=满分40

        # 上涨广度 → 映射到0-30
        breadth = total_up / total_cnt
        breadth_score = breadth * 30

        # 涨停数 → 映射到0-20
        limit_score = min(limit_up_total / 5 * 20, 20)  # 5只涨停=满分20

        # 板块分化（标准差越小越好）
        chgs = [s.avg_change for s in sectors]
        if len(chgs) > 1:
            mean_chg = sum(chgs) / len(chgs)
            variance = sum((c - mean_chg) ** 2 for c in chgs) / len(chgs)
            std = variance ** 0.5
            diff_score = max(10 - std * 2, 0)
        else:
            diff_score = 10

        return chg_score + breadth_score + limit_score + diff_score

    def _gen_conclusion(self, sectors: List[SectorHeat], overall: float,
                        level: str) -> Tuple[str, str]:
        """生成一句话结论和策略建议"""

        # 找最强和最弱板块
        sorted_sec = sorted(sectors, key=lambda x: x.avg_change, reverse=True)
        best = sorted_sec[0]
        worst = sorted_sec[-1]

        if overall >= 60:
            one_liner = (f"AI板块全面升温({level})，{best.name}领涨{best.avg_change:+.1f}%，"
                        f"全板块{best.up_count}/{best.total_count}上涨。"
                        f"涨停{sum(s.limit_up_count for s in sectors)}只。")
        elif overall >= 30:
            one_liner = (f"AI板块分化({level})，{best.name}{best.avg_change:+.1f}% vs "
                        f"{worst.name}{worst.avg_change:+.1f}%，结构化行情。")
        else:
            one_liner = (f"AI板块低迷({level})，{worst.name}{worst.avg_change:+.1f}%领跌，"
                        f"仅{sum(s.up_count for s in sectors)}/{sum(s.total_count for s in sectors)}只上涨。")

        # 策略建议
        if overall >= 70:
            suggestion = "⚠️ 短期过热，不建议追高。等待回调至5日线再考虑AI应用层标的。"
        elif overall >= 45:
            suggestion = "AI温和回暖，可关注PE<50的应用层机会（如金山办公、万兴科技），避开300倍PE芯片。"
        elif overall >= 20:
            suggestion = "AI冷清，可在回调时小仓位布局低位应用/机器人标的，等待催化剂。"
        else:
            suggestion = "AI冰点，不宜参与。等热度回到30以上再关注。"

        return one_liner, suggestion

    def _get_etf_flow(self) -> str:
        """ETF资金流向（用web搜索获取，这里简化）"""
        # 实际可调用web_search，此处返回占位
        return "待web搜索补充"

    def format_report(self, result: AIHeatResult) -> str:
        """格式化输出"""
        lines = [
            "━" * 28,
            f"🤖 AI热度仪表盘 | {result.timestamp}",
            f"   综合热度: {result.overall_heat:.0f}/100  {result.level}",
            f"   全板块: {result.total_up_count}/{result.total_count}只上涨",
            f"   涨停/涨超10%: {result.limit_up_total}只",
            "━" * 28,
        ]

        # 板块明细
        for s in result.sectors:
            emoji = '🟢' if s.avg_change > 2 else '🟡' if s.avg_change > 0 else '🔴'
            lines.append(
                f"  {emoji} {s.name:10s}  {s.avg_change:+5.1f}%  "
                f"涨{s.up_count}/{s.total_count}  "
                f"{'🔥' if s.limit_up_count > 0 else ''} "
                f"领涨:{s.top_gainer}({s.top_gainer_chg:+.1f}%)"
            )

        lines.append("")
        lines.append(f"  📝 {result.one_liner}")
        lines.append(f"  💡 {result.suggestion}")
        lines.append("━" * 28)
        return '\n'.join(lines)

    def format_brief(self, result: AIHeatResult) -> str:
        """微信推送简洁版"""
        lines = [
            f"🤖 AI热度 {result.overall_heat:.0f}/100 {result.level}",
            f"{result.total_up_count}/{result.total_count}上涨 | 涨停{result.limit_up_total}只",
        ]
        for s in result.sectors:
            e = '🟢' if s.avg_change > 2 else '🟡' if s.avg_change > 0 else '🔴'
            lines.append(f"{e} {s.name} {s.avg_change:+.1f}% 领涨:{s.top_gainer}")
        lines.append(f"💡 {result.suggestion}")
        return '\n'.join(lines)


def run_ai_heat() -> AIHeatResult:
    """快速运行入口"""
    dash = AIHeatDashboard()
    return dash.run()


# ─── CLI ─────────────────────────────────────────────
if __name__ == '__main__':
    dash = AIHeatDashboard()
    result = dash.run()
    print(dash.format_report(result))
