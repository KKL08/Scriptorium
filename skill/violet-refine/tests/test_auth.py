import pytest

from violet_refine.auth import (
    InMemoryKeyStore,
    MissingKeyError,
    PROVIDERS,
    ensure_api_key_usable,
    model_spec_for,
    resolve_key,
)


def test_providers_table_has_four_entries_with_env_names():
    assert set(PROVIDERS) == {"anthropic", "deepseek", "google", "openai-compatible"}
    assert PROVIDERS["anthropic"].env == "ANTHROPIC_API_KEY"
    assert PROVIDERS["deepseek"].env == "DEEPSEEK_API_KEY"
    assert PROVIDERS["google"].env == "GEMINI_API_KEY"
    assert PROVIDERS["openai-compatible"].env == "OPENAI_API_KEY"


def test_deepseek_provider_has_two_models():
    models = PROVIDERS["deepseek"].models
    assert [m.id for m in models] == [
        "deepseek/deepseek-v4-pro",
        "deepseek/deepseek-flash",
    ]
    assert PROVIDERS["deepseek"].default_model == "deepseek/deepseek-v4-pro"


def test_google_provider_has_gemini_flash():
    models = PROVIDERS["google"].models
    assert [m.id for m in models] == ["gemini/gemini-3.8-flash", "gemini/gemini-4-argon"]
    assert PROVIDERS["google"].default_model == "gemini/gemini-3.8-flash"


def test_model_spec_for_returns_reasoning_metadata():
    pro = model_spec_for("deepseek", "deepseek/deepseek-v4-pro")
    assert pro is not None
    assert pro.thinking is True
    assert pro.effort_by_mode == {"rewrite": "max"}
    assert pro.default_effort == "high"
    assert pro.max_output_tokens == 384_000

    flash = model_spec_for("deepseek", "deepseek/deepseek-flash")
    assert flash is not None
    assert flash.thinking is True
    assert flash.effort_by_mode == {}
    assert flash.default_effort == "high"
    assert flash.max_output_tokens == 384_000

    for gemini_id in ("gemini/gemini-3.8-flash", "gemini/gemini-4-argon"):
        gemini = model_spec_for("google", gemini_id)
        assert gemini is not None
        assert gemini.default_effort == "medium"
        assert gemini.thinking is False

    # Gemini 4：maxOutputTokens 是跨续写跳的总预算（思考 token 计入），非流式单跳 32K；
    # 官方建议单跳超时至少 20 分钟
    argon = model_spec_for("google", "gemini/gemini-4-argon")
    assert argon.max_output_tokens == 131_072
    assert argon.timeout_s == 1200


def test_gemini_budgets_fit_within_continuation_limit():
    # 预算要在续写上限内用得完：否则客户端会先撞跳数上限，把可完成的长文按截断丢弃
    from violet_refine.llm.client import MAX_CONTINUATIONS

    gemini_hop_tokens = 32_768  # 非流式 REST 单跳上限（实测）
    for spec in PROVIDERS["google"].models:
        budget = spec.max_output_tokens or 8192
        assert budget <= (MAX_CONTINUATIONS + 1) * gemini_hop_tokens, spec.id


def test_model_spec_for_maps_retired_flash_alias():
    # 旧串 deepseek-v4-flash 已下线并路由至 V4.1-Flash；两个入口（落盘 config、--model 覆盖）
    # 都走 model_spec_for，命中别名就得拿到 Flash 元数据
    spec = model_spec_for("deepseek", "deepseek/deepseek-v4-flash")
    assert spec is not None
    assert spec.id == "deepseek/deepseek-flash"
    assert spec.max_output_tokens == 384_000
    assert spec.default_effort == "high"


def test_model_spec_for_maps_retired_gemini_37_to_38():
    # Gemini 3.7 Flash 已宣布退役，官方替代为 3.8 Flash；已落盘的旧串要继续可用
    spec = model_spec_for("google", "gemini/gemini-3.7-flash")
    assert spec is not None
    assert spec.id == "gemini/gemini-3.8-flash"


def test_model_spec_for_unknown_returns_none():
    # openai-compatible 自填裸名不在目录里 → 归一化 opts 为空
    assert model_spec_for("openai-compatible", "gpt-4o") is None
    assert model_spec_for("deepseek", "deepseek/unknown-model") is None
    assert model_spec_for("anthropic", "anthropic/claude-fable-5") is None


def test_resolve_key_prefers_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    store = InMemoryKeyStore({"DEEPSEEK_API_KEY": "sk-store"})
    resolved = resolve_key("deepseek", store=store)
    assert resolved.value == "sk-env"
    assert resolved.source == "env"


def test_resolve_key_falls_back_to_store(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    store = InMemoryKeyStore({"DEEPSEEK_API_KEY": "sk-store"})
    resolved = resolve_key("deepseek", store=store)
    assert resolved.value == "sk-store"
    assert resolved.source == "keychain"


def test_resolve_key_missing_raises_product_message(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="本地 API Key 还没配置好"):
        resolve_key("deepseek", store=InMemoryKeyStore())


def test_resolve_key_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        resolve_key("nope", store=InMemoryKeyStore())


def test_resolved_key_repr_never_contains_key_value(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    store = InMemoryKeyStore({"DEEPSEEK_API_KEY": "sk-secret-do-not-leak"})
    resolved = resolve_key("deepseek", store=store)
    assert "sk-secret-do-not-leak" not in repr(resolved)
    assert "sk-secret-do-not-leak" not in str(resolved)


def test_resolve_key_uses_credential_id_slot(monkeypatch):
    # 按端点存的凭据：给定 credential_id 时从该槽位取，而非 provider.env 共享槽
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = InMemoryKeyStore(
        {"openai-compatible::https://b.example/v1": "kb", "OPENAI_API_KEY": "shared-old"}
    )
    resolved = resolve_key(
        "openai-compatible", store=store, credential_id="openai-compatible::https://b.example/v1"
    )
    assert resolved.value == "kb"
    assert resolved.source == "keychain"


def test_resolve_key_credential_id_none_falls_back_to_provider_env(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    store = InMemoryKeyStore({"DEEPSEEK_API_KEY": "ds"})
    assert resolve_key("deepseek", store=store).value == "ds"


def test_endpoint_bound_credential_ignores_shared_env_override(monkeypatch):
    # F1：openai-compatible 有端点专属 credential_id 时，不吃共享 OPENAI_API_KEY env 覆盖，
    # 否则 env 里的 key 会被发往用户自填端点
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")
    store = InMemoryKeyStore({"openai-compatible::https://b.example/v1": "slot-key-b"})
    resolved = resolve_key(
        "openai-compatible", store=store, credential_id="openai-compatible::https://b.example/v1"
    )
    assert resolved.value == "slot-key-b"
    assert resolved.source == "keychain"


def test_builtin_provider_still_honors_env_override(monkeypatch):
    # 内置 provider 单端点，credential_id 等于 provider.env（或 None），env 覆盖照常
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-ds")
    store = InMemoryKeyStore({"DEEPSEEK_API_KEY": "slot-ds"})
    resolved = resolve_key("deepseek", store=store, credential_id="DEEPSEEK_API_KEY")
    assert resolved.value == "env-ds"
    assert resolved.source == "env"


@pytest.mark.parametrize("bad", ["key\nmid", "key\tmid", " leading", "trailing ", "key\x80mid", "key\xffmid", "key\x7f"])
def test_ensure_api_key_usable_rejects_non_ascii_and_control(bad):
    # F5：httpx 按 ASCII 编码 header，0x80–0xFF 与控制字符会在发送时炸且异常 repr 带 key
    with pytest.raises(ValueError):
        ensure_api_key_usable(bad)


def test_ensure_api_key_usable_accepts_printable_ascii():
    ensure_api_key_usable("sk-Abc123._-~+/=")  # 常见 key 字符集，不抛
