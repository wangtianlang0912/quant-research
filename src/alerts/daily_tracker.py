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
    get_review_summary,
    ensure_files,
    PUSH_LOG_FILE
)
from src.data.akshare_client import TencentClient


def fetch_current_price(code: str) -> Optional[float]:
    """获取股票当前价格"""
    client = TencentClient()
    try:
        # 转换代码格式
        # A股: 600010 -> sh600010, 002049 -> sz002049
        # 港股: 02328 -> hk02328
        # 美股: crm.n -> usCRM, amd.oq -> usAMD
        code_lower = code.lower()
        
        if code_lower.startswith("6"):
            full_code = f"sh{code}"
        elif code_lower.startswith("0") or code_lower.startswith("3"):
            # 判断是港股还是A股
            # 港股代码通常是4-5位数字，如 02328, 00700
            # A股代码是6位，如 002049, 300750
            if len(code) == 4 or (len(code) == 5 and code.startswith("0")):
                full_code = f"hk{code.zfill(5)}"  # 港股补零到5位
            else:
                full_code = f"sz{code}"
        elif "." in code_lower:
            # 美股格式: crm.n, amd.oq -> usCRM, usAMD
            symbol = code.split(".")[0].upper()
            full_code = f"us{symbol}"
        elif code_lower.startswith("hk"):
            full_code = code_lower
        elif code_lower.startswith("us"):
            full_code = code_lower
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


def _strategy_summary(pushes: list) -> dict:
    """单策略统计"""
    hp = [p for p in pushes if p['status'] == 'hit_profit']
    hs = [p for p in pushes if p['status'] == 'hit_stop']
    pending = [p for p in pushes if p['status'] in ('pending', 'tracking')]
    finished = len(hp) + len(hs)
    wr = len(hp) / finished * 100 if finished else 0
    rets = [p.get('final_return', 0) for p in pushes if p.get('final_return') is not None]
    avg_ret = sum(rets) / len(rets) if rets else 0
    return {'total': len(pushes), 'hp': len(hp), 'hs': len(hs), 'pending': len(pending),
            'finished': finished, 'win_rate': wr, 'avg_return': avg_ret}


def _format_position_block(pushes: list, include_closed: bool = False) -> list:
    """格式化一批持仓为文本块"""
    lines = []
    active = [p for p in pushes if p['status'] in ('pending', 'tracking')]
    seen = set()
    for p in active:
        key = f"{p['code']}_{p['push_date']}"
        if key not in seen:
            seen.add(key)
            entry = p.get('entry_price', 0)
            sl = p.get('stop_loss', 0)
            tp = p.get('take_profit', 0)
            days = p.get('tracking_days', 0)
            max_r = p.get('max_return', 0)
            # 计算距止损距离
            dist_sl = (entry - sl) / entry * 100 if entry > 0 else 0
            warn = ' ⚠️' if max_r < -dist_sl * 0.5 else ''
            lines.append(f"⏳ {p['code']} {p['name']}{warn}")
            lines.append(f"   📅 {p.get('push_date','?')} | 第{days}天 | max {max_r:+.1f}%")
            lines.append(f"   入场{entry:.2f} 止损{sl:.2f}({-dist_sl:.0f}%) 止盈{tp:.2f}")

    if include_closed:
        closed = [p for p in pushes if p['status'] in ('hit_profit', 'hit_stop')]
        seen_c = set()
        for p in closed:
            key = f"{p['code']}_{p['push_date']}_{p['status']}"
            if key not in seen_c:
                seen_c.add(key)
                emoji = '✅' if p['status'] == 'hit_profit' else '❌'
                lines.append(f"{emoji} {p['code']} {p['name']} ({p.get('push_date','?')}) → {p.get('final_return',0):+.2f}%")
    return lines


def format_daily_report() -> str:
    """格式化每日追踪报告 - 按策略分开"""
    ensure_files()
    with open(PUSH_LOG_FILE, "r", encoding="utf-8") as f:
        all_pushes = json.load(f)["pushes"]

    factor = [p for p in all_pushes if p.get('strategy') == 'factor']
    breakout = [p for p in all_pushes if p.get('strategy') == 'breakout']
    fs = _strategy_summary(factor)
    bs = _strategy_summary(breakout)

    date_str = datetime.now().strftime('%Y-%m-%d')
    lines = [f"📊 每日追踪复盘 | {date_str}\n"]

    # ── Factor ──
    lines.append("### 🔹 多因子扫描")
    lines.append(f"总推送 {fs['total']} | ✅{fs['hp']}止盈 ❌{fs['hs']}止损 | 胜率 {fs['win_rate']:.1f}% | 均收益 {fs['avg_return']:+.2f}%")
    f_positions = _format_position_block(factor, include_closed=True)
    if f_positions:
        lines.extend(f_positions)
    else:
        lines.append("(无持仓)")

    # ── Breakout ──
    lines.append(f"\n### 🔹 突破形态 (Qullamaggie)")
    lines.append(f"总推送 {bs['total']} | ✅{bs['hp']}止盈 ❌{bs['hs']}止损 | 胜率 {bs['win_rate']:.1f}% | 均收益 {bs['avg_return']:+.2f}%")
    b_positions = _format_position_block(breakout, include_closed=True)
    if b_positions:
        lines.extend(b_positions)
    else:
        lines.append("(无持仓)")

    # ── 风险警告 ──
    all_active = [p for p in all_pushes if p['status'] in ('pending', 'tracking')]
    warnings = []
    for p in all_active:
        entry = p.get('entry_price', 0)
        sl = p.get('stop_loss', 0)
        if entry > 0 and sl > 0:
            dist = (entry - sl) / entry * 100
            if p.get('max_return', 0) < -dist * 0.5:
                warnings.append(f"⚠️ {p['code']} {p['name']} 回撤已过半({p['max_return']:+.1f}%)，距止损仅-{dist:.0f}%")
    if warnings:
        lines.append("\n---\n⚠️ 风险警告")
        lines.extend(warnings)

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