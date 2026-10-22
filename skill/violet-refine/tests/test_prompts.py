from violet_refine import prompts
from violet_refine.prompts import (
    VALID_MODES,
    build_messages,
    load_global_rules,
    load_mode_rules,
    load_strong_rules,
    validate_mode,
)

import pytest


def test_validate_mode_accepts_valid_and_rejects_unknown():
    assert validate_mode("refine") == "refine"
    with pytest.raises(ValueError, match="Unknown mode"):
        validate_mode("polish")


def test_load_mode_rules_returns_each_mode_section():
    for mode in VALID_MODES:
        rules = load_mode_rules(mode)
        assert len(rules) > 20
    assert "去 AI 腔" in load_mode_rules("refine")
    assert load_mode_rules("proofread") != load_mode_rules("rewrite")


def test_build_messages_fills_placeholders():
    messages = build_messages(
        workflow="review",
        mode="refine",
        text="这段文字需要润色。",
        brief="面向开发者的 README",
        rule_context="- 减少套话",
    )
    assert len(messages) == 2
    system = messages[0]["content"]
    assert "[[" not in system
    assert "本次 mode: refine" in system
    assert "面向开发者的 README" in system
    assert "- 减少套话" in system
    assert '"findings"' in system
    assert messages[1]["content"].endswith("这段文字需要润色。")


def test_build_messages_direct_defaults_empty_fields_to_none_marker():
    messages = build_messages(workflow="direct", mode="proofread", text="x")
    system = messages[0]["content"]
    assert "本次 brief: 无" in system
    assert "只输出处理后的完整文本" in system
    assert '"findings"' not in system


def test_load_global_rules_extracts_writing_fundamentals():
    rules = load_global_rules()
    assert "G01" in rules
    assert "G05" in rules
    assert "G06" in rules
    assert "G07" in rules
    assert "S01" not in rules
    assert "C01" not in rules


def test_load_strong_rules_extracts_only_layer_one():
    rules = load_strong_rules()
    assert "S01" in rules
    assert "S10" in rules
    assert "G01" not in rules
    assert "C01" not in rules


def test_build_messages_embeds_global_rules_for_all_modes():
    for mode in VALID_MODES:
        system = build_messages(workflow="direct", mode=mode, text="x")[0]["content"]
        assert "G01" in system
        assert "G05" in system
        assert "[[" not in system


def test_build_messages_embeds_strong_rules_for_refine_and_rewrite():
    for mode in ("refine", "rewrite"):
        system = build_messages(workflow="direct", mode=mode, text="x")[0]["content"]
        assert "S05 原文自然则不改" in system
        assert "[[" not in system


def test_build_messages_skips_strong_rules_for_proofread():
    system = build_messages(workflow="direct", mode="proofread", text="x")[0]["content"]
    assert "S05" not in system
    assert "[[" not in system


def test_load_strong_rules_fails_loudly_when_heading_missing(monkeypatch, tmp_path):
    (tmp_path / "anti-ai-rules.zh.md").write_text("# 别的文件\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "references_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="第一层"):
        load_strong_rules()


def test_load_global_rules_fails_loudly_when_heading_missing(monkeypatch, tmp_path):
    (tmp_path / "anti-ai-rules.zh.md").write_text("# 别的文件\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "references_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="写作全局规则"):
        load_global_rules()
