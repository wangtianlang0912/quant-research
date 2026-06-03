#!/usr/bin/env python3
"""
每日选股推送脚本

用法:
    python push_daily.py --brief       # 简洁版推送 TOP 2
    python push_daily.py --sarah       # Sarah 详细分析，每只单独推送
    python push_daily.py --test        # 测试模式（不实际推送）
"""

import sys
import os
import json
import argparse
from datetime import datetime
from typing import List

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scanners.factor_scanner import FactorScanner, ScanResult, ScanConfig
from src.alerts.daily_picker import DailyPicker
from src.agents.sarah_analysis import SarahAnalyst, StockProfile


def push_to_wechat(message: str) -> bool:
    """
    推送消息到微信
    
    实际调用时需要配置 OpenClaw message 工具
    这里作为占位，实际推送由外部调用
    """
    print(f"[推送] {message[:50]}...")
    # 实际推送由调用方通过 message tool 完成
    return True


def run_brief_mode(picker: DailyPicker, results: List[ScanResult], top_n: int = 2) -> str:
    """
    简洁版模式：打包推送 TOP N
    
    返回格式化的消息
    """
    return picker.format_message(results, top_n)


def run_sarah_mode(picker: DailyPicker, results: List[ScanResult]) -> List[str]:
    """
    Sarah 模式：逐只推送详细分析
    
    返回消息列表，每只股票一条消息
    """
    messages = []
    for r in results[:2]:  # 只推送 TOP 2
        msg = picker.format_sarah_report(r)
        messages.append(msg)
    return messages


def main():
    parser = argparse.ArgumentParser(description='每日选股推送')
    parser.add_argument('--brief', action='store_true', help='简洁版推送')
    parser.add_argument('--sarah', action='store_true', help='Sarah 详细分析推送')
    parser.add_argument('--test', action='store_true', help='测试模式')
    parser.add_argument('--top', type=int, default=10, help='扫描数量')
    args = parser.parse_args()
    
    # 扫描
    config = ScanConfig(top_n=args.top)
    picker = DailyPicker(config)
    results = picker.run()
    
    if not results:
        msg = "今日未找到符合条件的候选股"
        print(msg)
        return
    
    if args.sarah:
        # Sarah 模式：每只单独推送
        messages = run_sarah_mode(picker, results)
        for i, msg in enumerate(messages, 1):
            print(f"\n{'='*40}")
            print(f"📊 第 {i} 只")
            print('='*40)
            print(msg)
            
            if not args.test:
                # 实际推送（由外部调用）
                push_to_wechat(msg)
    
    else:
        # 默认/简洁版：打包推送
        msg = run_brief_mode(picker, results)
        print(msg)
        
        if not args.test:
            push_to_wechat(msg)


if __name__ == '__main__':
    main()
