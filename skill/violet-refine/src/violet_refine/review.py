from __future__ import annotations

import json
import re
from dataclasses import dataclass

from violet_refine.prompts import validate_mode

_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\n(.*)\n```$", re.DOTALL)


@dataclass(frozen=True)
class ReviewFinding:
    dimension: str
    risk: str
    scope: str
    description: str
    suggestion: str


@dataclass(frozen=True)
class CoverageNote:
    dimension: str
    note: str


@dataclass(frozen=True)
class ReviewReport:
    summary: str
    mode: str
    brief: str
    findings: list[ReviewFinding]
    coverage: list[CoverageNote]

    @classmethod
    def parse(cls, raw: str, *, mode: str, brief: str) -> ReviewReport:
        stripped = raw.strip()
        fence_match = _CODE_FENCE.match(stripped)
        if fence_match:
            stripped = fence_match.group(1).strip()
        data = json.loads(stripped)
        if not isinstance(data, dict):
            raise ValueError("Review report must be a JSON object.")
        findings = data.get("findings")
        if not isinstance(findings, list):
            raise ValueError("Review report needs a findings list.")
        coverage = data.get("coverage")
        if not isinstance(coverage, list):
            coverage = []
        # findings 允许为空（干净文本零发现是合法结果），但空 findings 必须有 coverage 交代排查过程
        if not findings and not coverage:
            raise ValueError("Review report needs findings or coverage.")
        return cls(
            summary=str(data.get("summary", "")),
            mode=validate_mode(mode),
            brief=brief,
            findings=[
                ReviewFinding(
                    dimension=str(item.get("dimension", "")),
                    risk=str(item.get("risk", "未标注")),
                    scope=str(item.get("scope", "")),
                    description=str(item.get("description", "")),
                    suggestion=str(item.get("suggestion", "")),
                )
                for item in findings
            ],
            coverage=[
                CoverageNote(
                    dimension=str(item.get("dimension", "")),
                    note=str(item.get("note", "")),
                )
                for item in coverage
            ],
        )

    def render(self) -> str:
        lines = [
            "审阅报告",
            "",
            f"mode: {self.mode}",
            f"brief: {self.brief or '无'}",
            f"审阅摘要：{self.summary}",
            "",
        ]
        if not self.findings:
            lines.append("未发现需要报告的问题。")
        for index, finding in enumerate(self.findings, start=1):
            lines.append(
                f"{index}. [{finding.dimension}]（{finding.scope}，risk: {finding.risk}）"
            )
            lines.append(f"   {finding.description}")
            lines.append(f"   建议：{finding.suggestion}")
        if self.coverage:
            lines.append("")
            lines.append("排查覆盖：")
            for note in self.coverage:
                lines.append(f"- {note.dimension}：{note.note}")
        return "\n".join(lines)
