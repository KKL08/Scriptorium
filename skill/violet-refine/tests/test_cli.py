import pytest

from violet_refine import cli
from violet_refine.llm import FakeLLMClient

REVIEW_JSON = (
    '{"summary": "ok", "findings": [{"dimension": "AI 腔", "risk": "低", "scope": "全文", "description": "x", "suggestion": "y"}]}'
)


@pytest.fixture
def fake_env(monkeypatch, tmp_path):
    """隔离配置与凭证：固定 provider、提供 env key、注入 fake client。"""
    config = tmp_path / "config.toml"
    config.write_text('provider = "deepseek"\nmodel = "deepseek/deepseek-v4-pro"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    def install(responses):
        client = FakeLLMClient(responses)
        monkeypatch.setattr(cli, "HttpLLMClient", lambda: client)
        return client

    return install


def test_run_requires_workflow_and_mode(capsys):
    with pytest.raises(SystemExit):
        cli.main(["run", "--mode", "refine"])
    with pytest.raises(SystemExit):
        cli.main(["run", "--workflow", "direct"])


def test_run_direct_text_output(fake_env, capsys, tmp_path):
    fake_env(["润色后的文本"])
    source = tmp_path / "input.md"
    source.write_text("原始文本", encoding="utf-8")
    exit_code = cli.main(
        ["run", "--workflow", "direct", "--mode", "refine", "--brief", "b", "--file", str(source)]
    )
    assert exit_code == 0
    assert "润色后的文本" in capsys.readouterr().out


def test_run_direct_diff_output(fake_env, capsys, tmp_path):
    fake_env(["第一行\n第二行改了\n"])
    source = tmp_path / "input.md"
    source.write_text("第一行\n第二行\n", encoding="utf-8")
    exit_code = cli.main(
        ["run", "--workflow", "direct", "--mode", "refine", "--file", str(source), "--format", "diff"]
    )
    assert exit_code == 0
    assert "+第二行改了" in capsys.readouterr().out


def test_run_review_renders_report(fake_env, capsys, tmp_path):
    client = fake_env([REVIEW_JSON])
    source = tmp_path / "input.md"
    source.write_text("文本", encoding="utf-8")
    exit_code = cli.main(
        ["run", "--workflow", "review", "--mode", "refine", "--brief", "README", "--file", str(source)]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "审阅报告" in out
    assert "mode: refine" in out
    assert "brief: README" in out
    assert len(client.calls) == 1
    assert "findings" in client.calls[0]["messages"][0]["content"]


def test_run_review_retries_once_on_bad_schema(fake_env, capsys, tmp_path):
    client = fake_env(["不是 JSON", REVIEW_JSON])
    source = tmp_path / "input.md"
    source.write_text("文本", encoding="utf-8")
    exit_code = cli.main(["run", "--workflow", "review", "--mode", "refine", "--file", str(source)])
    assert exit_code == 0
    assert len(client.calls) == 2


def test_run_review_dumps_raw_after_second_schema_failure(fake_env, capsys, tmp_path):
    fake_env(["坏的 1", "坏的 2"])
    source = tmp_path / "input.md"
    source.write_text("文本", encoding="utf-8")
    exit_code = cli.main(["run", "--workflow", "review", "--mode", "refine", "--file", str(source)])
    captured = capsys.readouterr()
    assert exit_code == 4
    assert "坏的 2" in captured.out
    assert "不符合报告结构" in captured.err


def test_run_missing_key_gives_product_message(fake_env, monkeypatch, capsys, tmp_path):
    fake_env([])
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(cli, "KeyringStore", lambda: __import__("violet_refine.auth", fromlist=["InMemoryKeyStore"]).InMemoryKeyStore())
    source = tmp_path / "input.md"
    source.write_text("文本", encoding="utf-8")
    exit_code = cli.main(["run", "--workflow", "direct", "--mode", "refine", "--file", str(source)])
    assert exit_code == 1
    assert "本地 API Key 还没配置好" in capsys.readouterr().err


def test_run_deepseek_enables_thinking_and_official_max_tokens(fake_env, tmp_path):
    client = fake_env(["改后文本"])
    source = tmp_path / "input.md"
    source.write_text("原文", encoding="utf-8")
    exit_code = cli.main(["run", "--workflow", "direct", "--mode", "refine", "--file", str(source)])
    assert exit_code == 0
    call = client.calls[0]
    assert call["max_tokens"] == 384_000
    assert call["thinking"] == {"type": "enabled"}
    assert call["reasoning_effort"] == "high"


def test_run_rewrite_uses_max_reasoning_effort(fake_env, tmp_path):
    client = fake_env(["改后文本"])
    source = tmp_path / "input.md"
    source.write_text("原文", encoding="utf-8")
    exit_code = cli.main(["run", "--workflow", "direct", "--mode", "rewrite", "--file", str(source)])
    assert exit_code == 0
    assert client.calls[0]["reasoning_effort"] == "max"


def test_build_request_options_deepseek_pro_rewrite():
    opts = cli.build_request_options("deepseek", "deepseek/deepseek-v4-pro", "rewrite")
    assert opts["reasoning_effort"] == "max"
    assert opts["thinking"] == {"type": "enabled"}
    assert opts["max_tokens"] == 384_000


def test_build_request_options_deepseek_pro_refine():
    opts = cli.build_request_options("deepseek", "deepseek/deepseek-v4-pro", "refine")
    assert opts["reasoning_effort"] == "high"


def test_build_request_options_deepseek_flash_is_high_for_all_modes():
    for mode in ("rewrite", "refine"):
        opts = cli.build_request_options("deepseek", "deepseek/deepseek-flash", mode)
        assert opts["reasoning_effort"] == "high"
        assert opts["thinking"] == {"type": "enabled"}
        assert opts["max_tokens"] == 384_000


def test_build_request_options_retired_flash_alias_keeps_metadata():
    # --model 传旧串或落盘 config 还是旧串：别名归一后元数据不丢
    for mode in ("rewrite", "refine"):
        opts = cli.build_request_options("deepseek", "deepseek/deepseek-v4-flash", mode)
        assert opts["reasoning_effort"] == "high"
        assert opts["thinking"] == {"type": "enabled"}
        assert opts["max_tokens"] == 384_000


def test_run_model_override_with_retired_flash_string(fake_env, tmp_path):
    client = fake_env(["改后文本"])
    source = tmp_path / "input.md"
    source.write_text("原文", encoding="utf-8")
    exit_code = cli.main(
        [
            "run", "--workflow", "direct", "--mode", "refine",
            "--file", str(source), "--model", "deepseek/deepseek-v4-flash",
        ]
    )
    assert exit_code == 0
    call = client.calls[0]
    # 退役旧串按别名改发现行模型，不依赖服务端转发
    assert call["model"] == "deepseek/deepseek-flash"
    assert call["max_tokens"] == 384_000
    assert call["reasoning_effort"] == "high"


def test_build_request_options_google_4_argon():
    opts = cli.build_request_options("google", "gemini/gemini-4-argon", "rewrite")
    assert opts == {"max_tokens": 131_072, "reasoning_effort": "medium", "timeout": 1200}


def test_build_request_options_google_38_flash_medium():
    opts = cli.build_request_options("google", "gemini/gemini-3.8-flash", "rewrite")
    assert opts == {"reasoning_effort": "medium"}


def test_build_request_options_unknown_provider_returns_empty():
    assert cli.build_request_options("anthropic", "anthropic/claude-fable-5", "rewrite") == {}


def test_run_google_config_passes_medium_effort_without_extras(monkeypatch, tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('provider = "google"\nmodel = "gemini/gemini-3.8-flash"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    client = FakeLLMClient(["改后文本"])
    monkeypatch.setattr(cli, "HttpLLMClient", lambda: client)
    source = tmp_path / "input.md"
    source.write_text("原文", encoding="utf-8")
    exit_code = cli.main(["run", "--workflow", "direct", "--mode", "refine", "--file", str(source)])
    assert exit_code == 0
    call = client.calls[0]
    assert call["model"] == "gemini/gemini-3.8-flash"
    assert call["reasoning_effort"] == "medium"
    assert call["thinking"] is None


def test_run_retired_gemini_37_config_sends_38(monkeypatch, tmp_path):
    # 3.7 下线后旧串会 404：已落盘的旧配置要按别名改发现行模型
    config = tmp_path / "config.toml"
    config.write_text('provider = "google"\nmodel = "gemini/gemini-3.7-flash"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_CONFIG_PATH", config)
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    client = FakeLLMClient(["改后文本"])
    monkeypatch.setattr(cli, "HttpLLMClient", lambda: client)
    source = tmp_path / "input.md"
    source.write_text("原文", encoding="utf-8")
    exit_code = cli.main(["run", "--workflow", "direct", "--mode", "refine", "--file", str(source)])
    assert exit_code == 0
    assert client.calls[0]["model"] == "gemini/gemini-3.8-flash"


def test_auth_status_reports_ready(fake_env, capsys):
    fake_env([])
    exit_code = cli.main(["auth"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "deepseek" in out
    assert "已配置" in out


def test_auth_status_reports_missing_key(fake_env, monkeypatch, capsys):
    fake_env([])
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(cli, "KeyringStore", lambda: __import__("violet_refine.auth", fromlist=["InMemoryKeyStore"]).InMemoryKeyStore())
    exit_code = cli.main(["auth"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "还没配置好" in out
