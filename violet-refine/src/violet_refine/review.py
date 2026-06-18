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
class ReviewReport:
    summary: str
    mode: str
    brief: str
    findings: list[ReviewFinding]

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
        if not isinstance(findings, list) or not findings:
            raise ValueError("Review report needs at least one finding.")
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
        for index, finding in enumerate(self.findings, start=1):
            lines.append(
                f"{index}. [{finding.dimension}]（{finding.scope}，risk: {finding.risk}）"
            )
            lines.append(f"   {finding.description}")
            lines.append(f"   建议：{finding.suggestion}")
        return "\n".join(lines)
