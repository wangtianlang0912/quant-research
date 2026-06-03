"""
Sarah CFA 分析师 - 机构级股票分析

功能：
1. 公司概览（业务模式、行业地位）
2. 关键财务数据（PE/PB/ROE/营收增速）
3. 技术面分析（RSI/MACD/均线）
4. 估值判断
5. 投资观点
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json
import urllib.request
import logging

logger = logging.getLogger(__name__)


@dataclass
class StockProfile:
    """股票档案"""
    code: str
    name: str
    market: str  # 'A', 'HK', 'US'
    price: float
    change_pct: float
    pe: float = 0.0
    pb: float = 0.0
    market_cap: float = 0.0  # 亿
    turnover_rate: float = 0.0
    amount: float = 0.0  # 成交额（亿）
    
    # 技术指标
    rsi: float = 50.0
    macd_signal: str = ""
    ma_status: str = ""  # "多头排列" / "空头排列" / "震荡"
    
    # 财务数据（可选）
    roe: float = 0.0
    revenue_growth: float = 0.0
    profit_margin: float = 0.0
    debt_ratio: float = 0.0
    
    # 分析结论
    score: float = 0.0
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reasons: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)


class SarahAnalyst:
    """
    Sarah, CFA - 机构级股票分析师
    
    分析框架：
    1. 基本面评估（PE/PB/ROE）
    2. 成长性评估（营收/利润增速）
    3. 技术面评估（RSI/MACD/MA）
    4. 估值判断
    5. 投资建议
    """
    
    # 行业PE中位数参考
    INDUSTRY_PE = {
        '银行': 6.0,
        '地产': 8.0,
        '保险': 12.0,
        '券商': 15.0,
        '消费': 25.0,
        '医药': 30.0,
        '科技': 35.0,
        '新能源': 40.0,
        '半导体': 50.0,
        'default': 20.0
    }
    
    # A股行业分类（简化版）
    STOCK_INDUSTRY = {
        'sh600000': '银行', 'sh600016': '银行', 'sh600036': '银行',
        'sh601166': '银行', 'sh601288': '银行', 'sh601328': '银行',
        'sh601398': '银行', 'sh601939': '银行', 'sh601988': '银行',
        'sh600030': '券商', 'sh601688': '券商', 'sz000166': '券商',
        'sh601318': '保险', 'hk02318': '保险', 'hk02628': '保险',
        'sh600519': '消费', 'sz000858': '消费', 'sz000568': '消费',
        'sh600276': '医药', 'sz300015': '医药', 'hk02269': '医药',
        'sh600900': '新能源', 'sz300750': '新能源',
        'sh600111': '半导体', 'sz002049': '半导体', 'sz002371': '半导体',
        'usNVDA': '半导体', 'usAMD': '半导体', 'usINTC': '半导体',
        'usAAPL': '科技', 'usMSFT': '科技', 'usGOOGL': '科技',
        'usAMZN': '科技', 'usMETA': '科技', 'usTSLA': '新能源',
        'hk00700': '科技', 'hk03690': '科技', 'hk01810': '科技',
    }
    
    def __init__(self):
        self.name = "Sarah"
        self.title = "CFA"
    
    def analyze(self, profile: StockProfile) -> Dict:
        """
        执行完整分析，返回结构化报告
        """
        report = {
            'header': self._header(profile),
            'overview': self._overview(profile),
            'fundamentals': self._fundamentals(profile),
            'technicals': self._technicals(profile),
            'valuation': self._valuation(profile),
            'verdict': self._verdict(profile),
            'footer': self._footer()
        }
        return report
    
    def format_message(self, profile: StockProfile, detailed: bool = True) -> str:
        """
        格式化为微信推送消息
        
        微信格式要求：
        - 无Markdown表格
        - 用emoji和符号美化
        - 换行清晰
        """
        report = self.analyze(profile)
        lines = []
        
        # 标题
        lines.append(report['header'])
        lines.append("━" * 20)
        
        # 公司概览
        lines.append(report['overview'])
        
        # 关键指标
        lines.append(report['fundamentals'])
        
        # 技术面
        if detailed:
            lines.append(report['technicals'])
        
        # 估值
        lines.append(report['valuation'])
        
        # 投资观点
        lines.append("━" * 20)
        lines.append(report['verdict'])
        
        # 免责声明
        lines.append(report['footer'])
        
        return '\n'.join(lines)
    
    def _header(self, p: StockProfile) -> str:
        """报告标题"""
        market_emoji = {'A': '🇨🇳', 'HK': '🇭🇰', 'US': '🇺🇸'}
        market_name = {'A': 'A股', 'HK': '港股', 'US': '美股'}
        return f"📋 Sarah's Analysis: {p.name}（{p.code}）\n{market_emoji.get(p.market, '📊')} {market_name.get(p.market, '')} | {datetime.now().strftime('%Y-%m-%d')}"
    
    def _overview(self, p: StockProfile) -> str:
        """公司概览"""
        industry = self._get_industry(p.code)
        lines = [
            f"🏢 行业: {industry}",
            f"💰 现价: {p.price:.2f} ({p.change_pct:+.2f}%)",
            f"📊 市值: {p.market_cap:.0f}亿" if p.market_cap > 0 else "",
            f"📈 成交额: {p.amount:.1f}亿" if p.amount > 0 else "",
        ]
        return '\n'.join([l for l in lines if l])
    
    def _fundamentals(self, p: StockProfile) -> str:
        """关键财务指标"""
        lines = ["\n📊 关键指标"]
        
        # PE/PB
        if p.pe > 0:
            pe_status = self._eval_pe(p)
            lines.append(f"• PE: {p.pe:.1f}倍 {pe_status}")
        if p.pb > 0:
            lines.append(f"• PB: {p.pb:.2f}倍")
        
        # ROE
        if p.roe > 0:
            roe_status = "✅" if p.roe > 15 else "⚠️" if p.roe > 10 else "❌"
            lines.append(f"• ROE: {p.roe:.1f}% {roe_status}")
        
        # 营收增速
        if p.revenue_growth != 0:
            growth_status = "📈" if p.revenue_growth > 10 else "📉" if p.revenue_growth < 0 else "➡️"
            lines.append(f"• 营收增速: {p.revenue_growth:+.1f}% {growth_status}")
        
        # 净利率
        if p.profit_margin > 0:
            lines.append(f"• 净利率: {p.profit_margin:.1f}%")
        
        # 负债率
        if p.debt_ratio > 0:
            debt_status = "⚠️" if p.debt_ratio > 60 else "✅"
            lines.append(f"• 资产负债率: {p.debt_ratio:.1f}% {debt_status}")
        
        if len(lines) == 1:
            lines.append("• 暂无详细财务数据")
        
        return '\n'.join(lines)
    
    def _technicals(self, p: StockProfile) -> str:
        """技术面分析"""
        lines = ["\n📐 技术面"]
        
        # RSI
        if 0 < p.rsi < 100:
            if p.rsi < 30:
                rsi_status = "🟢 超卖区域，存在反弹机会"
            elif p.rsi < 50:
                rsi_status = "🟡 相对低估"
            elif p.rsi < 70:
                rsi_status = "🟡 正常区间"
            else:
                rsi_status = "🔴 超买区域，注意回调风险"
            lines.append(f"• RSI(14): {p.rsi:.0f} {rsi_status}")
        
        # MACD
        if p.macd_signal:
            macd_emoji = "🟢" if p.macd_signal == "金叉" else "🔴"
            lines.append(f"• MACD: {macd_emoji} {p.macd_signal}")
        
        # 均线
        if p.ma_status:
            ma_emoji = "🟢" if "多头" in p.ma_status else "🔴" if "空头" in p.ma_status else "🟡"
            lines.append(f"• 均线: {ma_emoji} {p.ma_status}")
        
        if len(lines) == 1:
            lines.append("• 技术指标数据暂缺")
        
        return '\n'.join(lines)
    
    def _valuation(self, p: StockProfile) -> str:
        """估值判断"""
        lines = ["\n⚖️ 估值判断"]
        
        if p.pe <= 0:
            lines.append("• PE数据不可用，无法判断估值")
            return '\n'.join(lines)
        
        industry = self._get_industry(p.code)
        industry_pe = self.INDUSTRY_PE.get(industry, self.INDUSTRY_PE['default'])
        
        # 相对估值
        if p.pe < industry_pe * 0.7:
            valuation = "📉 低估"
            reason = f"低于行业均值{industry_pe:.0f}倍"
        elif p.pe < industry_pe * 1.3:
            valuation = "➡️ 合理"
            reason = f"接近行业均值{industry_pe:.0f}倍"
        else:
            valuation = "📈 高估"
            reason = f"高于行业均值{industry_pe:.0f}倍"
        
        lines.append(f"• {valuation}（{reason}）")
        
        # PEG（简化）
        if p.revenue_growth > 0:
            peg = p.pe / p.revenue_growth
            if peg < 1:
                lines.append(f"• PEG: {peg:.2f} 成长性估值合理")
            elif peg < 2:
                lines.append(f"• PEG: {peg:.2f} 估值偏高")
            else:
                lines.append(f"• PEG: {peg:.2f} 估值过高")
        
        return '\n'.join(lines)
    
    def _verdict(self, p: StockProfile) -> str:
        """投资观点"""
        lines = ["🎯 投资观点"]
        
        # 交易参数
        if p.entry > 0:
            lines.append(f"• 入场价: {p.entry:.2f}")
        if p.stop_loss > 0:
            lines.append(f"• 止损价: {p.stop_loss:.2f}")
        if p.take_profit > 0:
            lines.append(f"• 止盈价: {p.take_profit:.2f}")
        
        # 理由
        if p.reasons:
            lines.append("\n✅ 看好理由:")
            for r in p.reasons[:3]:
                lines.append(f"  • {r}")
        
        # 风险
        if p.risks:
            lines.append("\n⚠️ 风险提示:")
            for r in p.risks[:2]:
                lines.append(f"  • {r}")
        
        # 综合评分
        if p.score > 0:
            if p.score >= 70:
                rating = "🌟🌟🌟 强烈看好"
            elif p.score >= 50:
                rating = "🌟🌟 中性偏多"
            else:
                rating = "🌟 观望"
            lines.append(f"\n📊 综合评分: {p.score:.0f}分 {rating}")
        
        return '\n'.join(lines)
    
    def _footer(self) -> str:
        """免责声明"""
        return "\n—\n⚠️ 以上分析仅供参考，不构成投资建议。\n📊 Sarah, CFA | 投资级研究"
    
    def _get_industry(self, code: str) -> str:
        """获取行业分类"""
        return self.STOCK_INDUSTRY.get(code, '其他')
    
    def _eval_pe(self, p: StockProfile) -> str:
        """评估PE水平"""
        if p.pe <= 0:
            return ""
        
        industry = self._get_industry(p.code)
        industry_pe = self.INDUSTRY_PE.get(industry, self.INDUSTRY_PE['default'])
        
        if p.pe < industry_pe * 0.7:
            return "(低估)"
        elif p.pe < industry_pe * 1.3:
            return "(合理)"
        else:
            return "(偏高)"


def analyze_stock(
    code: str,
    name: str,
    market: str,
    price: float,
    change_pct: float,
    pe: float = 0,
    pb: float = 0,
    market_cap: float = 0,
    turnover_rate: float = 0,
    amount: float = 0,
    rsi: float = 50,
    macd_signal: str = "",
    ma_status: str = "",
    roe: float = 0,
    revenue_growth: float = 0,
    profit_margin: float = 0,
    debt_ratio: float = 0,
    score: float = 0,
    entry: float = 0,
    stop_loss: float = 0,
    take_profit: float = 0,
    reasons: List[str] = None,
    risks: List[str] = None,
) -> str:
    """
    便捷函数：分析单只股票并返回格式化报告
    """
    profile = StockProfile(
        code=code,
        name=name,
        market=market,
        price=price,
        change_pct=change_pct,
        pe=pe,
        pb=pb,
        market_cap=market_cap,
        turnover_rate=turnover_rate,
        amount=amount,
        rsi=rsi,
        macd_signal=macd_signal,
        ma_status=ma_status,
        roe=roe,
        revenue_growth=revenue_growth,
        profit_margin=profit_margin,
        debt_ratio=debt_ratio,
        score=score,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        reasons=reasons or [],
        risks=risks or []
    )
    
    analyst = SarahAnalyst()
    return analyst.format_message(profile)
