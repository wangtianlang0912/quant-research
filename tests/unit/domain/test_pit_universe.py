"""PIT 股票池领域服务测试（T02.5 / M-15 / M-20 / M-21 / M-22）。

验收基准直接来自架构文档实测样本（§9.4 T02.5 / 附录 B.2）。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from quant_v2.domain.services.pit_universe import (
    DAILY_SAMPLE_WINDOW_DAYS,
    PIT_EARLIEST_DATE,
    NameChangeKind,
    classify_name_change,
    diff_snapshots,
    event_fill_dates,
    parse_is_st,
    sample_dates,
)

pytestmark = pytest.mark.unit


# ============================================================
# M-15 常量
# ============================================================
def test_最早快照日_上交所开市首日() -> None:
    """M-15：query_all_stock 最早可用 1990-12-19（实测），不是 1990-01-01。"""
    assert date(1990, 12, 19) == PIT_EARLIEST_DATE


# ============================================================
# M-20：ST 正则解析
# ============================================================
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("*ST宏盛", True),  # 戴帽
        ("ST郎科", True),
        ("S*ST生化", True),  # 历史形态：含 ST 子串
        ("SST华新", True),
        ("平安银行", False),
        ("浦发银行", False),
        ("退市海润", False),  # ★ 退 ≠ ST：名称突变分类里退是白名单 token，但 is_st 只看 ST
    ],
)
def test_ST解析(name: str, expected: bool) -> None:
    """M-20：无独立 ST 字段，只能从 code_name 正则解析（2005-01-04 基准 137 只）。"""
    assert parse_is_st(name) is expected


# ============================================================
# M-21：名称突变分类
# ============================================================
@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("宏盛", "ST宏盛", NameChangeKind.ST),  # 戴帽
        ("ST宏盛", "*ST宏盛", NameChangeKind.ST),  # ST → *ST
        ("*ST宏盛", "ST宏盛", NameChangeKind.ST),  # *ST → ST
        ("ST宏盛", "宏盛", NameChangeKind.ST),  # 脱帽
        ("*ST海润", "退市海润", NameChangeKind.ST),  # 退市整理期
        # 无变化：剥 token 后相等（真实 diff 不会到达，分类器单独兜住）
        ("平安银行", "平安银行", NameChangeKind.ST),
        ("平安银行", "某某科技", NameChangeKind.MATERIAL),  # 重组更名
        ("ST郎科", "某某科技", NameChangeKind.MATERIAL),  # 既摘帽又改名 → 实质
    ],
)
def test_名称突变分类(old: str, new: str, expected: NameChangeKind) -> None:
    """M-21 白名单：差异仅涉及 ST/*ST/退 token → INFO；否则 → P0。"""
    assert classify_name_change(old, new) is expected


# ============================================================
# 相邻快照 diff
# ============================================================
def test_快照diff_名称变化检出() -> None:
    """只看两日都在市的标的；单边缺席（上市/退市）不算名称突变。"""
    prev = [("600000.SH", "浦发银行"), ("000001.SZ", "平安银行"), ("600069.SH", "银鸽投资")]
    curr = [
        ("600000.SH", "浦发银行"),
        ("000001.SZ", "平安银行"),  # 不变
        ("600069.SH", "*ST银鸽投资"),  # 戴帽（基名不变，仅 ST token 增删）
        ("600485.SH", "中昌数据"),  # 新上市（单边缺席，不算）
    ]
    changes = diff_snapshots(prev, curr, as_of=date(2007, 12, 28))
    assert len(changes) == 1
    assert changes[0].symbol == "600069.SH"
    assert changes[0].kind is NameChangeKind.ST
    assert changes[0].old_name == "银鸽投资"
    assert changes[0].new_name == "*ST银鸽投资"
    assert changes[0].as_of == date(2007, 12, 28)


def test_快照diff_实质性突变检出() -> None:
    prev = [("600087.SH", "南京水运")]
    curr = [("600087.SH", "长航油运")]
    changes = diff_snapshots(prev, curr, as_of=date(2008, 6, 30))
    assert len(changes) == 1
    assert changes[0].kind is NameChangeKind.MATERIAL


def test_快照diff_无变化返回空() -> None:
    prev = [("600000.SH", "浦发银行")]
    curr = [("600000.SH", "浦发银行")]
    assert diff_snapshots(prev, curr, as_of=date(2024, 1, 2)) == []


# ============================================================
# M-22：采样计划
# ============================================================
def _weekdays(start: date, end: date) -> list[date]:
    """模拟交易日序列：区间内每个工作日（足够测试采样数学）。"""
    return [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    ]


def test_采样计划_近窗口逐日_更早按周() -> None:
    """auto：end 前 730 天逐日 + 更早每 5 个交易日 1 个。"""
    start = date(2005, 1, 3)
    end = date(2026, 9, 4)
    days = _weekdays(start, end)
    plan = sample_dates(days, start=start, end=end)

    window_start = end - timedelta(days=DAILY_SAMPLE_WINDOW_DAYS)
    recent = [d for d in days if d >= window_start]
    older = [d for d in days if d < window_start]

    assert len(plan) == len(set(plan))  # 去重后无重复
    # 近窗口全部采到
    assert all(d in set(plan) for d in recent)
    # 更早段只有约 1/5
    older_sampled = [d for d in plan if d < window_start]
    assert older_sampled == older[::5]
    # 总量级：约 500（recent）+ 900（weekly）≈ 1400（M-22 预估）
    assert 1000 < len(plan) < 2000


def test_采样计划_区间截断到日历覆盖() -> None:
    """start 早于日历起点：不炸，按日历实际覆盖算。"""
    days = _weekdays(date(2010, 1, 4), date(2010, 12, 31))
    plan = sample_dates(days, start=date(2005, 1, 3), end=date(2010, 12, 31))
    assert plan  # 有采样
    assert all(date(2010, 1, 4) <= d <= date(2010, 12, 31) for d in plan)


def test_采样计划_start晚于end_报错() -> None:
    with pytest.raises(ValueError, match="不得晚于"):
        sample_dates([], start=date(2024, 1, 2), end=date(2024, 1, 1))


# ============================================================
# M-22：事件日补齐
# ============================================================
def test_事件补齐_成员集合变化_补中间日() -> None:
    """周采样间池成员变了 → 补抓两采样日之间的全部交易日。"""
    prev_date = date(2024, 1, 8)
    curr_date = date(2024, 1, 15)
    days = _weekdays(date(2024, 1, 1), date(2024, 1, 31))
    fill = event_fill_dates(
        prev_date,
        curr_date,
        days,
        previous_symbols=["600000.SH"],
        current_symbols=["600000.SH", "301999.SZ"],  # 新上市
    )
    assert fill == [d for d in days if prev_date < d < curr_date]


def test_事件补齐_成员无变化_不补() -> None:
    prev_date = date(2024, 1, 8)
    curr_date = date(2024, 1, 15)
    days = _weekdays(date(2024, 1, 1), date(2024, 1, 31))
    fill = event_fill_dates(
        prev_date,
        curr_date,
        days,
        previous_symbols=["600000.SH", "000001.SZ"],
        current_symbols=["000001.SZ", "600000.SH"],  # 集合相等（顺序无关）
    )
    assert fill == []


def test_事件补齐_名称变化不触发() -> None:
    """ST 切换不改池成员集合（M-25 已量化接受），不补抓。"""
    prev_date = date(2024, 1, 8)
    curr_date = date(2024, 1, 15)
    days = _weekdays(date(2024, 1, 1), date(2024, 1, 31))
    fill = event_fill_dates(
        prev_date,
        curr_date,
        days,
        previous_symbols=["600000.SH"],
        current_symbols=["600000.SH"],  # 成员没变
    )
    assert fill == []


def test_事件补齐_相邻同日_返回空() -> None:
    days = _weekdays(date(2024, 1, 1), date(2024, 1, 31))
    assert (
        event_fill_dates(
            date(2024, 1, 8),
            date(2024, 1, 8),
            days,
            previous_symbols=["600000.SH"],
            current_symbols=["000001.SZ"],
        )
        == []
    )
