"""每日选股推送 - 支持 Factor/因子模式 + Breakout/突破模式 + Sarah CFA 分析"""
from __future__ import annotations
import json, os
from datetime import datetime
from typing import List, Optional
from dataclasses import asdict

from src.scanners.factor_scanner import FactorScanner, ScanResult, ScanConfig
from src.scanners.breakout_scanner import BreakoutScanner, BreakoutCandidate
from src.alerts.push_tracker import record_push
from src.agents.sarah_analysis import SarahAnalyst, StockProfile

import logging
logger = logging.getLogger(__name__)


class DailyPicker:
    """每日选股 — 多模式"""
    
    def __init__(self, config: Optional[ScanConfig] = None, mode: str = "factor"):
        self.mode = mode
        self.scanner = FactorScanner(config)
        self.breakout_scanner = BreakoutScanner()
        self.sarah = SarahAnalyst()
    
    def run(self) -> List[ScanResult]:
        logger.info(f"每日选股开始 {datetime.now()}")
        results = self.scanner.scan()
        if results:
            self._print(results)
            self._save(results)
        else:
            print("今日未找到符合条件的股票")
        return results
    
    def _print(self, results: List[ScanResult]) -> None:
        print("\n" + "=" * 60)
        print(f"📊 每日选股 ({datetime.now().strftime('%Y-%m-%d')})")
        print("=" * 60)
        for i, r in enumerate(results[:5], 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f" {i}."
            print(f"\n{emoji} {r.code} {r.name}")
            print(f"   💰 {r.price:.2f} ({r.change_pct:+.2f}%)")
            print(f"   📈 得分 {r.score:.1f}")
            print(f"   🎯 入场{r.suggested_entry:.2f} 止损{r.stop_loss:.2f} 止盈{r.take_profit:.2f}")
            print(f"   📝 {' | '.join(r.reasons[:3])}")
        print("\n" + "=" * 60)
    
    def _save(self, results: List[ScanResult]) -> None:
        os.makedirs("reports/scan", exist_ok=True)
        date = datetime.now().strftime('%Y-%m-%d')
        fp = f"reports/scan/daily_pick_{date}.json"
        data = {
            "date": date,
            "timestamp": datetime.now().isoformat(),
            "count": len(results),
            "picks": [asdict(r) for r in results]
        }
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存: {fp}")
        
        # 记录推送（用于后续追踪复盘）
        for r in results[:2]:  # 只记录实际推送的前2只
            try:
                record_push(
                    code=r.code,
                    name=r.name,
                    price=r.price,
                    change_pct=r.change_pct,
                    entry_price=r.suggested_entry,
                    stop_loss=r.stop_loss,
                    take_profit=r.take_profit,
                    reason=" | ".join(r.reasons[:2]),
                    score=r.score
                )
                logger.info(f"已记录推送: {r.code} {r.name}")
            except Exception as e:
                logger.error(f"记录推送失败: {e}")
    
    def format_message(self, results: List[ScanResult], top_n: int = 2) -> str:
        """简洁版推送消息"""
        if not results:
            return "今日未找到符合条件的候选股"
        
        date = datetime.now().strftime('%m月%d日')
        picks = results[:top_n]
        lines = [f"📊 {date} 每日选股\n"]
        for i, r in enumerate(picks, 1):
            e = "🥇" if i == 1 else "🥈"
            lines.append(f"{e} {r.code} {r.name}")
            lines.append(f"   💰 {r.price:.2f} ({r.change_pct:+.2f}%)")
            lines.append(f"   🎯 入场{r.suggested_entry:.2f} 止损{r.stop_loss:.2f} 止盈{r.take_profit:.2f}")
            lines.append(f"   📝 {' | '.join(r.reasons[:2])}")
            lines.append("")
        lines.append("⚠️ 仅供参考，不构成投资建议")
        return '\n'.join(lines)
    
    def format_sarah_report(self, result: ScanResult) -> str:
        """
        Sarah CFA 分析报告 - 单只股票详细分析
        
        用于每天单独推送一只票的深度分析
        """
        # 构建 StockProfile
        profile = StockProfile(
            code=result.code,
            name=result.name,
            market=result.market,
            price=result.price,
            change_pct=result.change_pct,
            pe=result.factors.get('PE', 0) if hasattr(result, 'factors') else 0,
            # 从 factors 中提取更多数据（如果有）
            score=result.score,
            entry=result.suggested_entry,
            stop_loss=result.stop_loss,
            take_profit=result.take_profit,
            rsi=result.rsi if hasattr(result, 'rsi') else 50,
            macd_signal=result.macd_signal if hasattr(result, 'macd_signal') else "",
            reasons=result.reasons,
            risks=self._infer_risks(result)
        )
        
        return self.sarah.format_message(profile, detailed=True)
    
    def format_sarah_brief(self, result: ScanResult) -> str:
        """
        Sarah 简要版 - 用于每日选股概览
        
        保留核心信息，更简洁
        """
        profile = StockProfile(
            code=result.code,
            name=result.name,
            market=result.market,
            price=result.price,
            change_pct=result.change_pct,
            score=result.score,
            entry=result.suggested_entry,
            stop_loss=result.stop_loss,
            take_profit=result.take_profit,
            reasons=result.reasons[:2],
        )
        
        report = self.sarah.analyze(profile)
        # 只保留关键部分
        lines = [
            report['header'],
            "━" * 16,
            report['overview'],
            report['fundamentals'],
            report['verdict'],
            report['footer']
        ]
        return '\n'.join(lines)
    
    def _infer_risks(self, result: ScanResult) -> List[str]:
        """根据数据推断风险点"""
        risks = []
        
        # PE 过高
        pe = result.factors.get('PE', 0) if hasattr(result, 'factors') else 0
        if pe > 50:
            risks.append("估值偏高，注意回调风险")
        
        # RSI 超买
        rsi = result.rsi if hasattr(result, 'rsi') else 50
        if rsi > 70:
            risks.append(f"RSI={rsi:.0f}超买区域")
        
        # 涨幅过大
        if result.change_pct > 5:
            risks.append("短期涨幅较大，追高需谨慎")
        
        # 默认风险提示
        if not risks:
            risks.append("市场波动风险")
        
        return risks


    def run_low_volume(self) -> List:
        """执行 低量价值发现 扫描"""
        from src.scanners.low_volume_scanner import LowVolumeScanner, LowVolumeConfig, format_results
        logger.info(f"低量价值扫描开始 {datetime.now()}")
        config = LowVolumeConfig(top_n=5)
        scanner = LowVolumeScanner(config)
        results = scanner.scan()
        if results:
            self._print_low_volume(results)
            self._save_low_volume(results)
        else:
            print("今日未找到符合条件的低量蓄势品种")
        return results

    def _print_low_volume(self, results: List) -> None:
        from src.scanners.low_volume_scanner import format_results
        print(format_results(results))

    def _save_low_volume(self, results: List) -> None:
        os.makedirs("reports/low_volume", exist_ok=True)
        date = datetime.now().strftime('%Y-%m-%d')
        fp = f"reports/low_volume/daily_{date}.json"
        data = {
            "date": date,
            "timestamp": datetime.now().isoformat(),
            "strategy": "low_volume_value",
            "count": len(results),
            "picks": [{
                "code": r.code, "name": r.name, "score": r.score,
                "price": r.price, "pe": r.pe, "pb": r.pb,
                "volume_ratio": r.volume_ratio, "sideways_days": r.sideways_days,
                "drawdown_pct": r.drawdown_pct, "reasons": r.reasons,
                "suggested_entry": r.suggested_entry,
                "stop_loss": r.stop_loss, "take_profit": r.take_profit,
            } for r in results]
        }
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存低量扫描: {fp}")

        # 记录推送（用于追踪）
        for r in results[:2]:
            try:
                record_push(
                    code=r.code, name=r.name, price=r.price,
                    change_pct=r.change_pct, entry_price=r.suggested_entry,
                    stop_loss=r.stop_loss, take_profit=r.take_profit,
                    reason=f"低量价值 | 得分{r.score:.0f} | {'; '.join(r.reasons[:2])}",
                    score=r.score
                )
            except Exception as e:
                logger.error(f"记录推送失败: {e}")

    def run_breakout(self) -> List[BreakoutCandidate]:
        """执行 Breakout 模式扫描"""
        logger.info(f"Breakout 扫描开始 {datetime.now()}")
        candidates = self.breakout_scanner.run()
        if candidates:
            self._print_breakout(candidates)
            self._save_breakout(candidates)
        else:
            print("今日未找到符合条件的突破股")
        return candidates
    
    def _print_breakout(self, candidates: List[BreakoutCandidate]) -> None:
        print("\n" + "=" * 60)
        print(f"📊 突破选股 ({datetime.now().strftime('%Y-%m-%d')})")
        print("=" * 60)
        for i, c in enumerate(candidates, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f" {i}."
            print(f"\n{emoji} {c.code} {c.name}")
            print(f"   💰 {c.price:.2f} ({c.change_pct:+.1f}%)")
            print(f"   📈 得分 {c.score}/28 | 动量 {c.momentum_score:+.1%}")
            print(f"   🎯 入场 {c.entry_price:.2f} | 量比 {c.volume_ratio:.1f}x")
            print(f"   🏭 {c.industry}")
            print(f"   📝 {' | '.join(c.reasons[:3])}")
        print("\n" + "=" * 60)
    
    def _save_breakout(self, candidates: List[BreakoutCandidate]) -> None:
        os.makedirs("reports/breakout", exist_ok=True)
        date = datetime.now().strftime('%Y-%m-%d')
        fp = f"reports/breakout/daily_pick_{date}.json"
        data = {
            "date": date,
            "timestamp": datetime.now().isoformat(),
            "strategy": "breakout",
            "score_min": self.breakout_scanner.score_min,
            "count": len(candidates),
            "picks": [{
                "code": c.code, "name": c.name, "score": c.score,
                "entry_price": c.entry_price, "price": c.price,
                "volume_ratio": c.volume_ratio, "industry": c.industry,
                "momentum": c.momentum_score, "reasons": c.reasons,
            } for c in candidates]
        }
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"已保存: {fp}")
        
        # 记录推送
        for c in candidates[:2]:
            try:
                record_push(
                    code=c.code, name=c.name, price=c.price,
                    change_pct=c.change_pct, entry_price=c.entry_price,
                    stop_loss=c.entry_price * 0.94,
                    take_profit=c.entry_price * 1.15,
                    reason=f"突破得分{c.score}", score=c.score
                )
            except Exception as e:
                logger.error(f"记录推送失败: {e}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description='每日选股')
    parser.add_argument('--top', type=int, default=10)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--mode', type=str, default='factor', choices=['factor', 'breakout', 'low'],
                        help='选股模式: factor/breakout/low(低量价值发现)')
    parser.add_argument('--sarah', action='store_true', help='生成 Sarah CFA 分析报告')
    parser.add_argument('--sarah-brief', action='store_true', help='生成 Sarah 简要报告')
    args = parser.parse_args()
    
    if args.mode == 'breakout':
        picker = DailyPicker(mode='breakout')
        results = picker.run_breakout()
        if args.json:
            print(json.dumps([vars(c) for c in results], ensure_ascii=False, indent=2, default=str))
        return
    
    if args.mode == 'low':
        picker = DailyPicker()
        results = picker.run_low_volume()
        if args.json:
            print(json.dumps([{
                'code': r.code, 'name': r.name, 'score': r.score,
                'price': r.price, 'pe': r.pe, 'volume_ratio': r.volume_ratio,
                'sideways_days': r.sideways_days, 'reasons': r.reasons,
            } for r in results], ensure_ascii=False, indent=2))
        elif results:
            from src.scanners.low_volume_scanner import format_results
            print(format_results(results))
        else:
            print("今日未找到符合条件的低量蓄势品种")
        return
    
    config = ScanConfig(top_n=args.top)
    picker = DailyPicker(config)
    results = picker.run()
    
    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    elif args.sarah and results:
        print(picker.format_sarah_report(results[0]))
    elif args.sarah_brief and results:
        for r in results[:2]:
            print(picker.format_sarah_brief(r))
            print("\n")
    else:
        print(picker.format_message(results))


if __name__ == '__main__':
    main()
