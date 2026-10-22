import pytest

from violet_refine.review import ReviewReport

VALID_JSON = """
{
  "summary": "整体可读，存在少量表达自然度和信息组织问题",
  "coverage": [
    {"dimension": "语言正确性", "note": "逐句查了错别字、标点和搭配，未发现问题"},
    {"dimension": "信息组织", "note": "对照 README 应有结构检查，发现简介与表格重复"}
  ],
  "findings": [
    {"dimension": "信息组织", "risk": "中", "scope": "全文",
     "description": "信息表格和简介段重复", "suggestion": "简介段只保留表格没覆盖的细节"},
    {"dimension": "表达自然度", "risk": "低", "scope": "第 1 段",
     "description": "开头有模板感", "suggestion": "删掉空泛开场"},
    {"dimension": "句子与节奏", "risk": "低", "scope": "全文",
     "description": "句式节奏均匀", "suggestion": "长短句交替"}
  ]
}
"""


def test_parse_fills_mode_and_brief_from_request():
    report = ReviewReport.parse(VALID_JSON, mode="refine", brief="README 润色")
    assert report.mode == "refine"
    assert report.brief == "README 润色"
    assert report.summary.startswith("整体可读")
    assert len(report.findings) == 3
    assert report.findings[0].dimension == "信息组织"
    assert report.findings[1].suggestion == "删掉空泛开场"


def test_parse_strips_code_fence():
    fenced = f"```json\n{VALID_JSON}\n```"
    report = ReviewReport.parse(fenced, mode="refine", brief="")
    assert report.findings


def test_parse_reads_coverage_notes():
    report = ReviewReport.parse(VALID_JSON, mode="refine", brief="")
    assert len(report.coverage) == 2
    assert report.coverage[0].dimension == "语言正确性"
    assert "未发现问题" in report.coverage[0].note


def test_parse_tolerates_missing_coverage():
    report = ReviewReport.parse(
        '{"summary": "x", "findings": [{"dimension": "语言正确性", "risk": "低",'
        ' "scope": "全文", "description": "d", "suggestion": "s"}]}',
        mode="refine",
        brief="",
    )
    assert report.coverage == []


def test_parse_allows_empty_findings_with_coverage():
    report = ReviewReport.parse(
        '{"summary": "干净", "findings": [],'
        ' "coverage": [{"dimension": "语言正确性", "note": "逐句查过，无问题"}]}',
        mode="refine",
        brief="",
    )
    assert report.findings == []
    assert "未发现需要报告的问题" in report.render()


def test_parse_rejects_empty_findings_without_coverage():
    with pytest.raises(ValueError):
        ReviewReport.parse(
            '{"summary": "x", "findings": []}', mode="refine", brief=""
        )


def test_parse_rejects_non_json():
    with pytest.raises(ValueError):
        ReviewReport.parse("这不是 JSON", mode="refine", brief="")


def test_render_includes_all_fields():
    report = ReviewReport.parse(VALID_JSON, mode="rewrite", brief="技术文档")
    rendered = report.render()
    assert "mode: rewrite" in rendered
    assert "[信息组织]" in rendered
    assert "[表达自然度]" in rendered
    assert "[句子与节奏]" in rendered
    assert "信息表格和简介段重复" in rendered
    assert "建议：" in rendered
    assert "排查覆盖：" in rendered
    assert "语言正确性：逐句查了错别字" in rendered
