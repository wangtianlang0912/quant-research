"""
每日追踪复盘脚本

每天自动追踪已推送股票的表现，分析是否符合预期
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# 路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from src.alerts.push_tracker import (
    get_active_pushes,
    update_push_status,
    record_tracking,
    analyze_performance,
    get_review_summary
)
from src.data.akshare_client import TencentClient


def fetch_current_price(code: str) -> Optional[float]:
    """获取股票当前价格"""
    client = TencentClient()
    try:
        # 转换代码格式: 600010 -> sh600010, 002049 -> sz002049
        if code.startswith("6"):
            full_code = f"sh{code}"
        elif code.startswith("0") or code.startswith("3"):
            full_code = f"sz{code}"
        else:
            full_code = code

        quotes = client._get_quotes([full_code])
        if quotes:
            return quotes[0].price
    except Exception as e:
        logger.error(f"获取价格失败 {code}: {e}")
    return None


def daily_tracking() -> Dict:
    """
    每日追踪

    Returns:
        追踪结果字典
    """
    logger.info(f"开始每日追踪 {datetime.now()}")

    # 获取过去7天活跃推送
    active_pushes = get_active_pushes(days=7)

    if not active_pushes:
        logger.info("无待追踪推送")
        return {"tracked": 0, "alerts": []}

    alerts = []
    tracked = 0

    for push in active_pushes:
        code = push["code"]
        current_price = fetch_current_price(code)

        if current_price is None:
            logger.warning(f"无法获取 {code} 价格，跳过")
            continue

        # 分析表现
        analysis = analyze_performance(push, current_price)

        # 记录追踪数据
        record_tracking(
            push_id=push["push_id"],
            code=code,
            current_price=current_price,
            high_price=current_price,  # TODO: 获取当日最高
            low_price=current_price,   # TODO: 获取当日最低
            return_pct=analysis["return_pct"],
            notes=analysis.get("exit_reason", "")
        )

        # 更新推送状态
        update_push_status(push["push_id"], {
            "status": analysis["status"],
            "max_return": analysis["max_return"],
            "min_return": analysis["min_return"],
            "tracking_days": analysis["tracking_days"],
            "final_return": analysis["return_pct"] if analysis["status"] in ["hit_stop", "hit_profit", "expired"] else None,
            "exit_reason": analysis.get("exit_reason")
        })

        tracked += 1

        # 判断是否需要推送告警
        if analysis["meets_expectation"] is False:
            alerts.append({
                "code": code,
                "name": push["name"],
                "push_date": push["push_date"],
                "entry_price": push["entry_price"],
                "current_price": current_price,
                "return_pct": analysis["return_pct"],
                "status": analysis["status"],
                "reason": analysis.get("exit_reason", "表现不佳"),
                "push_id": push["push_id"]
            })

    logger.info(f"追踪完成: {tracked} 只股票, {len(alerts)} 个告警")

    return {
        "tracked": tracked,
        "alerts": alerts,
        "date": datetime.now().strftime("%Y-%m-%d")
    }


def format_alert_message(alerts: List[Dict]) -> str:
    """格式化告警消息"""
    if not alerts:
        return ""

    lines = ["⚠️ 选股复盘 - 不符合预期\n"]

    for a in alerts:
        lines.append(f"📌 {a['code']} {a['name']}")
        lines.append(f"   推荐日期: {a['push_date']}")
        lines.append(f"   入场价: {a['entry_price']:.2f}")
        lines.append(f"   当前价: {a['current_price']:.2f}")
        lines.append(f"   收益: {a['return_pct']:+.2f}%")
        lines.append(f"   状态: {a['status']}")
        lines.append(f"   原因: {a['reason']}")
        lines.append("")

    # 分析总结
    lines.append("---")
    lines.append("📊 本周统计")

    summary = get_review_summary()
    lines.append(f"胜率: {summary['win_rate']:.1f}%")
    lines.append(f"平均收益: {summary['avg_return']:+.2f}%")
    lines.append(f"触发止损: {summary['hit_stop']} 次")
    lines.append(f"触发止盈: {summary['hit_profit']} 次")

    return '\n'.join(lines)


def format_daily_report() -> str:
    """格式化每日追踪报告"""
    summary = get_review_summary()

    lines = ["📊 每日追踪报告\n"]
    lines.append(f"日期: {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append("---")
    lines.append("📈 统计数据")
    lines.append(f"总推送: {summary['total']}")
    lines.append(f"触发止盈: {summary['hit_profit']}")
    lines.append(f"触发止损: {summary['hit_stop']}")
    lines.append(f"待追踪: {summary['pending']}")
    lines.append(f"胜率: {summary['win_rate']:.1f}%")
    lines.append(f"平均收益: {summary['avg_return']:+.2f}%")
    lines.append("")

    # 显示最近推送状态
    if summary['recent_pushes']:
        lines.append("---")
        lines.append("📋 最近推送")
        for p in summary['recent_pushes'][-5:]:
            status_emoji = "✅" if p['status'] == 'hit_profit' else "❌" if p['status'] == 'hit_stop' else "⏳"
            return_str = f"{p.get('final_return', 0):+.2f}%" if p.get('final_return') else "追踪中"
            lines.append(f"{status_emoji} {p['code']} {p['name']} - {return_str}")

    return '\n'.join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='每日追踪复盘')
    parser.add_argument('--report', action='store_true', help='只输出报告，不追踪')
    parser.add_argument('--alerts-only', action='store_true', help='只输出告警')
    args = parser.parse_args()

    if args.report:
        print(format_daily_report())
        return

    # 执行追踪
    result = daily_tracking()

    if args.alerts_only and result["alerts"]:
        print(format_alert_message(result["alerts"]))
    elif not args.alerts_only:
        print(format_daily_report())
        if result["alerts"]:
            print("\n" + format_alert_message(result["alerts"]))


if __name__ == "__main__":
    main()