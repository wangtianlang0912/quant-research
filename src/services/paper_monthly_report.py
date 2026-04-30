from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class MonthlyPerformanceRow:
    """表示单个月份的纸盘绩效汇总。"""

    month: str
    start_value: Decimal
    end_value: Decimal
    monthly_return: Decimal
    max_value: Decimal
    min_value: Decimal


@dataclass(frozen=True)
class PaperMonthlyPerformanceReport:
    """封装月度纸盘绩效报告。"""

    rows: list[MonthlyPerformanceRow]


class PaperMonthlyReportBuilder:
    """负责从纸盘净值日志构建月度绩效汇总。"""

    def build_from_equity_csv(self, equity_csv_path: str) -> PaperMonthlyPerformanceReport:
        """从净值日志CSV读取数据并按月份聚合。"""
        file_path = Path(equity_csv_path)
        monthly_values: dict[str, list[Decimal]] = defaultdict(list)
        with file_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                timestamp = row.get("timestamp", "")
                total_value = Decimal(row.get("total_value", "0"))
                month = timestamp[:7] if timestamp else "unknown"
                monthly_values[month].append(total_value)
        rows = [
            MonthlyPerformanceRow(
                month=month,
                start_value=values[0],
                end_value=values[-1],
                monthly_return=(values[-1] - values[0]) / values[0] if values[0] != 0 else Decimal("0"),
                max_value=max(values),
                min_value=min(values),
            )
            for month, values in sorted(monthly_values.items())
            if values
        ]
        return PaperMonthlyPerformanceReport(rows=rows)
