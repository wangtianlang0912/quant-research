from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.domain.models.run import RunContext, RunSummary


class BacktestReportWriter:
    """负责将回测摘要和运行上下文输出为可归档的报告文件。"""

    def write_json_report(self, output_dir: str, context: RunContext, summary: RunSummary) -> str:
        """将回测上下文与摘要写入JSON报告并返回文件路径。"""
        report_dir = Path(output_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{context.run_id.value}.json"
        payload = {
            "context": self._serialize(asdict(context)),
            "summary": self._serialize(asdict(summary)),
        }
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(report_path)

    def _serialize(self, value: Any) -> Any:
        """递归转换日期、时间和Decimal等对象，确保可安全写入JSON。"""
        if isinstance(value, dict):
            return {key: self._serialize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._serialize(item) for item in value]
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
            return self._serialize(value.value)
        if value.__class__.__name__ == "Decimal":
            return str(value)
        return value
