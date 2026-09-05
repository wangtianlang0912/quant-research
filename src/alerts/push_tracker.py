"""
推送记录与追踪复盘系统

功能：
1. 记录每次推送的股票
2. 每日追踪已推送股票的表现
3. 复盘分析不符合预期的情况
"""

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from decimal import Decimal

# 路径配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUSH_LOG_FILE = os.path.join(BASE_DIR, "reports", "push_log.json")
TRACKING_FILE = os.path.join(BASE_DIR, "reports", "tracking.json")


def ensure_files():
    """确保记录文件存在"""
    os.makedirs(os.path.dirname(PUSH_LOG_FILE), exist_ok=True)

    if not os.path.exists(PUSH_LOG_FILE):
        with open(PUSH_LOG_FILE, "w") as f:
            json.dump({"pushes": []}, f, ensure_ascii=False, indent=2)

    if not os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE, "w") as f:
            json.dump({"trackings": []}, f, ensure_ascii=False, indent=2)


def record_push(
    code: str,
    name: str,
    price: float,
    change_pct: float,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    reason: str,
    score: float
) -> Dict:
    """
    记录一次推送

    Returns:
        推送记录字典
    """
    ensure_files()

    record = {
        "push_id": f"push_{uuid.uuid4().hex[:12]}",
        "push_date": datetime.now().strftime("%Y-%m-%d"),
        "push_time": datetime.now().strftime("%H:%M:%S"),
        "code": code,
        "name": name,
        "push_price": price,
        "change_pct": change_pct,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "reason": reason,
        "score": score,
        "status": "pending",  # pending / hit_stop / hit_profit / expired / tracking
        "tracking_days": 0,
        "max_return": 0.0,
        "min_return": 0.0,
        "final_return": None,
        "exit_reason": None
    }

    with open(PUSH_LOG_FILE, "r") as f:
        data = json.load(f)

    data["pushes"].append(record)

    with open(PUSH_LOG_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return record


def get_active_pushes(days: int = 7) -> List[Dict]:
    """
    获取过去 N 天内未结束的推送

    Args:
        days: 回看天数，默认 7 天

    Returns:
        活跃推送列表
    """
    ensure_files()

    with open(PUSH_LOG_FILE, "r") as f:
        data = json.load(f)

    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    active = [
        p for p in data["pushes"]
        if p["push_date"] >= cutoff_date and p["status"] in ["pending", "tracking"]
    ]

    return active


def update_push_status(push_id: str, updates: Dict):
    """更新推送状态"""
    ensure_files()

    with open(PUSH_LOG_FILE, "r") as f:
        data = json.load(f)

    for p in data["pushes"]:
        if p.get("push_id") == push_id:
            p.update(updates)
            break

    with open(PUSH_LOG_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record_tracking(
    push_id: str,
    code: str,
    current_price: float,
    high_price: float,
    low_price: float,
    return_pct: float,
    notes: str = ""
) -> Dict:
    """记录一次追踪数据"""
    ensure_files()

    record = {
        "track_id": f"track_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "push_id": push_id,
        "track_date": datetime.now().strftime("%Y-%m-%d"),
        "code": code,
        "current_price": current_price,
        "high_price": high_price,
        "low_price": low_price,
        "return_pct": return_pct,
        "notes": notes
    }

    with open(TRACKING_FILE, "r") as f:
        data = json.load(f)

    data["trackings"].append(record)

    with open(TRACKING_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return record


def analyze_performance(push: Dict, current_price: float) -> Dict:
    """
    分析推送表现

    Returns:
        分析结果字典
    """
    entry = push["entry_price"]
    stop_loss = push["stop_loss"]
    take_profit = push["take_profit"]

    return_pct = (current_price - entry) / entry * 100

    # 判断状态
    status = push["status"]
    exit_reason = None

    if current_price <= stop_loss:
        status = "hit_stop"
        exit_reason = f"触发止损 (现价 {current_price:.2f} <= 止损 {stop_loss:.2f})"
    elif current_price >= take_profit:
        status = "hit_profit"
        exit_reason = f"触发止盈 (现价 {current_price:.2f} >= 止盈 {take_profit:.2f})"

    # 计算最大回撤
    max_return = max(push.get("max_return", 0), return_pct)
    min_return = min(push.get("min_return", 0), return_pct)

    # 判断是否符合预期
    meets_expectation = None
    if status == "hit_profit":
        meets_expectation = True
    elif status == "hit_stop":
        meets_expectation = False
    elif push["tracking_days"] >= 5:  # 5天后还没触发
        meets_expectation = return_pct > 0  # 至少不亏

    return {
        "return_pct": return_pct,
        "status": status,
        "exit_reason": exit_reason,
        "max_return": max_return,
        "min_return": min_return,
        "meets_expectation": meets_expectation,
        "tracking_days": push.get("tracking_days", 0) + 1
    }


def get_review_summary() -> Dict:
    """
    获取复盘摘要

    Returns:
        复盘摘要字典
    """
    ensure_files()

    with open(PUSH_LOG_FILE, "r") as f:
        data = json.load(f)

    pushes = data["pushes"]

    # 统计
    total = len(pushes)
    hit_profit = len([p for p in pushes if p["status"] == "hit_profit"])
    hit_stop = len([p for p in pushes if p["status"] == "hit_stop"])
    pending = len([p for p in pushes if p["status"] in ["pending", "tracking"]])
    expired = len([p for p in pushes if p["status"] == "expired"])

    # 计算胜率
    finished = hit_profit + hit_stop
    win_rate = hit_profit / finished * 100 if finished > 0 else 0

    # 平均收益
    returns = [p.get("final_return", 0) for p in pushes if p.get("final_return") is not None]
    avg_return = sum(returns) / len(returns) if returns else 0

    return {
        "total": total,
        "hit_profit": hit_profit,
        "hit_stop": hit_stop,
        "pending": pending,
        "expired": expired,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "recent_pushes": pushes[-10:] if pushes else []
    }


if __name__ == "__main__":
    # 测试
    print("推送记录系统测试")
    print(f"记录文件: {PUSH_LOG_FILE}")
    print(f"追踪文件: {TRACKING_FILE}")

    # 查看当前状态
    summary = get_review_summary()
    print(f"\n当前统计:")
    print(f"  总推送: {summary['total']}")
    print(f"  触发止盈: {summary['hit_profit']}")
    print(f"  触发止损: {summary['hit_stop']}")
    print(f"  待追踪: {summary['pending']}")
    print(f"  胜率: {summary['win_rate']:.1f}%")
