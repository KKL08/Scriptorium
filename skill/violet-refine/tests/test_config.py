import pytest

from violet_refine.config import RuntimeConfig, load_runtime_config, save_runtime_config


def test_load_missing_file_returns_defaults(tmp_path):
    config = load_runtime_config(tmp_path / "absent.toml")
    assert config.provider == "deepseek"
    assert config.model == "deepseek/deepseek-v4-pro"
    assert config.api_base is None


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    save_runtime_config(
        RuntimeConfig(provider="anthropic", model="anthropic/claude-fable-5", api_base=None),
        path,
    )
    config = load_runtime_config(path)
    assert config.provider == "anthropic"
    assert config.model == "anthropic/claude-fable-5"


def test_load_rejects_api_key_in_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('provider = "deepseek"\napi_key = "sk-123"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="api_key"):
        load_runtime_config(path)


def test_save_escapes_special_characters_and_roundtrips(tmp_path):
    # openai-compatible 的 model/api_base 是自由文本：引号、反斜杠、控制字符都得无损往返
    path = tmp_path / "config.toml"
    model = 'mod"el\\x'
    api_base = "http://h/tag\"base\ttab"
    save_runtime_config(
        RuntimeConfig(provider="openai-compatible", model=model, api_base=api_base), path
    )
    config = load_runtime_config(path)
    assert config.model == model
    assert config.api_base == api_base


def test_save_rejects_values_that_cannot_roundtrip(tmp_path):
    # 万一有序列化不了的字符（如裸 DEL），写盘前就报错，不留坏配置
    path = tmp_path / "config.toml"
    with pytest.raises(ValueError):
        save_runtime_config(
            RuntimeConfig(provider="openai-compatible", model="m\x7f", api_base=None), path
        )
    assert not path.exists()


def test_save_empty_api_base_is_none_equivalent(tmp_path):
    # 空串 api_base 不落盘，回读为 None；round-trip 校验不得误报
    path = tmp_path / "config.toml"
    save_runtime_config(
        RuntimeConfig(provider="openai-compatible", model="m", api_base=""), path
    )
    assert load_runtime_config(path).api_base is None


def test_config_roundtrip_credential_id(tmp_path):
    path = tmp_path / "config.toml"
    save_runtime_config(
        RuntimeConfig(
            provider="openai-compatible",
            model="llama-3.1-70b",
            api_base="http://localhost:11434/v1",
            credential_id="openai-compatible::http://localhost:11434/v1",
        ),
        path,
    )
    loaded = load_runtime_config(path)
    assert loaded.credential_id == "openai-compatible::http://localhost:11434/v1"
    assert loaded.api_base == "http://localhost:11434/v1"


def test_save_is_atomic_old_config_intact_on_replace_failure(tmp_path, monkeypatch):
    # F1：写 config 时 os.replace 失败，旧配置必须一字节不变（原子写，不留半写/缺字段文件）
    import violet_refine.config as cfg

    path = tmp_path / "config.toml"
    save_runtime_config(
        RuntimeConfig(provider="openai-compatible", model="m", api_base="https://a.example/v1",
                      credential_id="openai-compatible::https://a.example/v1"),
        path,
    )
    before = path.read_bytes()

    def _boom(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(cfg.os, "replace", _boom)
    with pytest.raises(OSError):
        save_runtime_config(
            RuntimeConfig(provider="openai-compatible", model="m2", api_base="https://b.example/v1",
                          credential_id="openai-compatible::https://b.example/v1"),
            path,
        )
    assert path.read_bytes() == before  # 旧配置逐字节不变
    # 未留下临时文件
    assert not any(p.name.startswith(".config-") for p in tmp_path.iterdir())
