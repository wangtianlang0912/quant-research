"""每日选股推送"""
from __future__ import annotations
import json, os
from datetime import datetime
from typing import List, Optional
from dataclasses import asdict

from src.scanners.factor_scanner import FactorScanner, ScanResult, ScanConfig

import logging
logger = logging.getLogger(__name__)


class DailyPicker:
    """每日选股"""
    
    def __init__(self, config: Optional[ScanConfig] = None):
        self.scanner = FactorScanner(config)
    
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
    
    def format_message(self, results: List[ScanResult], top_n: int = 2) -> str:
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


def main():
    import argparse
    parser = argparse.ArgumentParser(description='每日选股')
    parser.add_argument('--top', type=int, default=10)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    
    config = ScanConfig(top_n=args.top)
    picker = DailyPicker(config)
    results = picker.run()
    
    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        print(picker.format_message(results))


if __name__ == '__main__':
    main()