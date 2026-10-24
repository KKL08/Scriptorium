import json
import threading
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlencode

import pytest

from violet_refine.auth import InMemoryKeyStore
from violet_refine.config import load_runtime_config
from violet_refine.setup_page import create_setup_server
from violet_refine.llm import FakeLLMClient


@pytest.fixture
def server_env(tmp_path):
    store = InMemoryKeyStore()
    client = FakeLLMClient(["ok"])
    config_path = tmp_path / "config.toml"
    server, url, token = create_setup_server(
        store=store, llm_client=client, config_path=config_path, token="test-token"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield store, client, config_path, url, token
    server.shutdown()
    server.server_close()


def _post(url, payload):
    request = urllib.request.Request(
        url, data=urlencode(payload).encode(), method="POST"
    )
    with urllib.request.urlopen(request) as response:
        return response.status, response.read().decode()


def test_get_serves_page_with_providers(server_env):
    _, _, _, url, _ = server_env
    with urllib.request.urlopen(url) as response:
        page = response.read().decode()
    assert "DeepSeek" in page
    assert "Google" in page
    assert "测试连接" in page
    # 页面只露出 SETUP_PAGE_PROVIDERS 里的服务商；其他家验证过真实调用后再加回
    assert 'value="anthropic"' not in page
    assert 'value="openai-compatible"' in page


def test_page_has_custom_model_input_and_base_url_field(server_env):
    _, _, _, url, _ = server_env
    with urllib.request.urlopen(url) as response:
        page = response.read().decode()
    # openai-compatible：模型是自由文本输入，另有 Base URL 字段
    assert 'id="model-text"' in page
    assert 'id="api_base"' in page
    assert "OpenAI 兼容" in page


def test_page_catalog_includes_new_models_and_default_unchanged(server_env):
    _, _, _, url, _ = server_env
    with urllib.request.urlopen(url) as response:
        page = response.read().decode()
    assert "Gemini 3.8 Flash" in page
    assert "Gemini 4 Argon" in page
    assert "DeepSeek V4.1 Flash" in page
    # 3.7 已退役，不再出现在下拉里
    assert "gemini-3.7-flash" not in page
    assert '"gemini/gemini-3.8-flash"' in page
    assert '"deepseek/deepseek-v4-pro"' in page


def test_post_save_selecting_gemini_38(server_env):
    store, _, config_path, url, token = server_env
    status, _ = _post(
        url + "save",
        {
            "setup_token": token,
            "provider": "google",
            "api_key": "g-38",
            "model": "gemini/gemini-3.8-flash",
            "api_base": "",
        },
    )
    assert status == 200
    config = load_runtime_config(config_path)
    assert config.model == "gemini/gemini-3.8-flash"


def test_post_test_with_selected_gemini_38(server_env):
    _, client, _, url, _ = server_env
    status, body = _post(
        url + "test",
        {"provider": "google", "api_key": "g-38", "model": "gemini/gemini-3.8-flash", "api_base": ""},
    )
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert client.calls[0]["model"] == "gemini/gemini-3.8-flash"
    assert client.calls[0]["reasoning_effort"] == "low"


def test_post_save_selecting_deepseek_flash(server_env):
    store, _, config_path, url, token = server_env
    status, _ = _post(
        url + "save",
        {
            "setup_token": token,
            "provider": "deepseek",
            "api_key": "sk-flash",
            "model": "deepseek/deepseek-flash",
            "api_base": "",
        },
    )
    assert status == 200
    assert load_runtime_config(config_path).model == "deepseek/deepseek-flash"


def test_post_test_with_selected_deepseek_flash(server_env):
    _, client, _, url, _ = server_env
    status, body = _post(
        url + "test",
        {"provider": "deepseek", "api_key": "sk-flash", "model": "deepseek/deepseek-flash", "api_base": ""},
    )
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert client.calls[0]["model"] == "deepseek/deepseek-flash"
    assert client.calls[0]["thinking"] == {"type": "disabled"}


def test_post_test_builtin_provider_drops_api_base(server_env):
    # /save 有「内置 provider 丢弃 api_base」防线，/test 同样要有：残留地址不能收到探测请求里的 key
    _, client, _, url, _ = server_env
    status, body = _post(
        url + "test",
        {"provider": "deepseek", "api_key": "sk-x", "model": "", "api_base": "http://evil-gateway.example/v1"},
    )
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert client.calls[0]["api_base"] is None


def test_get_serves_design_assets(server_env):
    _, _, _, url, _ = server_env
    with urllib.request.urlopen(url + "assets/violet-photo.webp") as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/webp"
        assert len(response.read()) > 1000
    with pytest.raises(HTTPError) as excinfo:
        urllib.request.urlopen(url + "assets/../setup_page.py")
    assert excinfo.value.code == 404


def test_post_test_calls_llm_with_submitted_key(server_env):
    _, client, _, url, _ = server_env
    status, body = _post(
        url + "test",
        {"provider": "deepseek", "api_key": "sk-x", "model": "", "api_base": ""},
    )
    assert status == 200
    assert json.loads(body)["ok"] is True
    assert client.calls[0]["api_key"] == "sk-x"
    assert client.calls[0]["model"] == "deepseek/deepseek-v4-pro"
    assert client.calls[0]["thinking"] == {"type": "disabled"}


def test_post_test_google_probe_uses_lowest_supported_effort(server_env):
    _, client, _, url, _ = server_env
    status, body = _post(
        url + "test",
        {"provider": "google", "api_key": "g-key", "model": "", "api_base": ""},
    )
    assert status == 200
    assert json.loads(body)["ok"] is True
    call = client.calls[0]
    assert call["model"] == "gemini/gemini-3.8-flash"
    assert call["reasoning_effort"] == "low"


def test_post_save_google_stores_gemini_config(server_env):
    store, _, config_path, url, token = server_env
    status, body = _post(
        url + "save",
        {
            "setup_token": token,
            "provider": "google",
            "api_key": "gemini-key",
            "model": "",
            "api_base": "",
        },
    )
    assert status == 200
    assert "已保存" in body
    assert store.get("GEMINI_API_KEY") == "gemini-key"
    config = load_runtime_config(config_path)
    assert config.provider == "google"
    assert config.model == "gemini/gemini-3.8-flash"


def test_post_test_ok_even_when_probe_content_empty(server_env):
    # 真实场景：finish_reason=length 时 content 为空串，但请求成功＝key 可用
    _, client, _, url, _ = server_env
    client.responses[0] = ""
    status, body = _post(
        url + "test",
        {"provider": "deepseek", "api_key": "sk-x", "model": "", "api_base": ""},
    )
    assert status == 200
    assert json.loads(body)["ok"] is True


def test_page_key_input_is_masked_with_toggle(server_env):
    _, _, _, url, _ = server_env
    with urllib.request.urlopen(url) as response:
        page = response.read().decode()
    assert 'type="password"' in page
    assert 'id="key-eye"' in page


def test_post_save_stores_key_and_config_then_shuts_down(server_env):
    store, _, config_path, url, token = server_env
    status, body = _post(
        url + "save",
        {
            "setup_token": token,
            "provider": "deepseek",
            "api_key": "sk-saved",
            "model": "",
            "api_base": "",
        },
    )
    assert status == 200
    assert "已保存" in body
    assert store.get("DEEPSEEK_API_KEY") == "sk-saved"
    assert load_runtime_config(config_path).provider == "deepseek"


def test_post_save_rejects_bad_token(server_env):
    store, _, _, url, _ = server_env
    with pytest.raises(HTTPError) as excinfo:
        _post(url + "save", {"setup_token": "wrong", "provider": "deepseek", "api_key": "sk-x"})
    assert excinfo.value.code == 403
    assert store.get("DEEPSEEK_API_KEY") is None


def test_rejects_non_local_host_header(server_env):
    store, _, _, url, token = server_env
    evil = {"Host": "evil.example.com"}

    get_request = urllib.request.Request(url, headers=evil)
    with pytest.raises(HTTPError) as excinfo:
        urllib.request.urlopen(get_request)
    assert excinfo.value.code == 403

    payload = urlencode({"setup_token": token, "provider": "deepseek", "api_key": "sk-x"})
    post_request = urllib.request.Request(
        url + "save", data=payload.encode(), headers=evil, method="POST"
    )
    with pytest.raises(HTTPError) as excinfo:
        urllib.request.urlopen(post_request)
    assert excinfo.value.code == 403
    assert store.get("DEEPSEEK_API_KEY") is None


def test_post_test_openai_compatible_sends_plain_probe(server_env):
    _, client, _, url, _ = server_env
    status, body = _post(
        url + "test",
        {
            "provider": "openai-compatible",
            "api_key": "sk-x",
            "model": "gpt-4o",
            "api_base": "http://localhost:11434/v1",
        },
    )
    assert status == 200
    assert json.loads(body)["ok"] is True
    call = client.calls[0]
    assert call["provider"] == "openai-compatible"
    assert call["model"] == "gpt-4o"
    assert call["api_base"] == "http://localhost:11434/v1"
    assert call["thinking"] is None
    assert call["reasoning_effort"] is None


def test_post_save_openai_compatible_requires_model_and_base(server_env):
    store, _, config_path, url, token = server_env
    with pytest.raises(HTTPError) as excinfo:
        _post(
            url + "save",
            {
                "setup_token": token,
                "provider": "openai-compatible",
                "api_key": "sk-x",
                "model": "",
                "api_base": "http://localhost:11434/v1",
            },
        )
    assert excinfo.value.code == 403
    assert store.get("OPENAI_API_KEY") is None

    with pytest.raises(HTTPError) as excinfo:
        _post(
            url + "save",
            {
                "setup_token": token,
                "provider": "openai-compatible",
                "api_key": "sk-x",
                "model": "gpt-4o",
                "api_base": "",
            },
        )
    assert excinfo.value.code == 403
    assert store.get("OPENAI_API_KEY") is None
    assert not config_path.exists()


def test_post_save_openai_compatible_stores_model_and_base(server_env):
    store, _, config_path, url, token = server_env
    status, body = _post(
        url + "save",
        {
            "setup_token": token,
            "provider": "openai-compatible",
            "api_key": "sk-custom",
            "model": "llama-3.1-70b",
            "api_base": "http://localhost:11434/v1",
        },
    )
    assert status == 200
    assert "已保存" in body
    # 凭据按端点存：不再落进共享的 OPENAI_API_KEY 槽
    slot = "openai-compatible::http://localhost:11434/v1"
    assert store.get(slot) == "sk-custom"
    config = load_runtime_config(config_path)
    assert config.provider == "openai-compatible"
    assert config.model == "llama-3.1-70b"
    assert config.api_base == "http://localhost:11434/v1"
    assert config.credential_id == slot


def test_post_save_drops_api_base_for_builtin_providers(server_env):
    # 自定义→内置切换后，页面残留的 api_base 不得进配置：内置 provider 的 key 不能被发往自定义地址
    store, _, config_path, url, token = server_env
    status, _ = _post(
        url + "save",
        {
            "setup_token": token,
            "provider": "deepseek",
            "api_key": "sk-ds",
            "model": "",
            "api_base": "http://evil-gateway.example/v1",
        },
    )
    assert status == 200
    config = load_runtime_config(config_path)
    assert config.provider == "deepseek"
    assert config.api_base is None


def test_post_save_bad_model_chars_rejected_before_storing_key(server_env):
    store, _, config_path, url, token = server_env
    with pytest.raises(HTTPError) as excinfo:
        _post(
            url + "save",
            {
                "setup_token": token,
                "provider": "openai-compatible",
                "api_key": "sk-x",
                "model": "m\x7f",
                "api_base": "http://localhost:11434/v1",
            },
        )
    assert excinfo.value.code == 403
    # 校验失败时 key 不落盘、配置文件不产生
    assert store.get("OPENAI_API_KEY") is None
    assert not config_path.exists()


def test_openai_compatible_credentials_scoped_per_endpoint(tmp_path, monkeypatch):
    # 换端点用不同凭据槽：A 的 key 不被 B 覆盖，两把 key 各存各的（根治共享槽失配）。
    # save 成功后 server 自动 shutdown，故 A/B 各用一个 server，共享同一 store/config。
    from violet_refine.auth import InMemoryKeyStore, resolve_key

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # 隔离 env 覆盖，测钥匙串槽路径
    store = InMemoryKeyStore()
    config_path = tmp_path / "config.toml"

    def _save(base, key):
        server, url, token = create_setup_server(
            store=store, llm_client=FakeLLMClient(["ok"]), config_path=config_path, token="t"
        )
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            _post(url + "save", {
                "setup_token": "t", "provider": "openai-compatible",
                "api_key": key, "model": "m", "api_base": base,
            })
        finally:
            t.join(timeout=2)

    _save("https://a.example/v1", "key-a")
    _save("https://b.example/v1", "key-b")
    assert store.get("openai-compatible::https://a.example/v1") == "key-a"
    assert store.get("openai-compatible::https://b.example/v1") == "key-b"
    # 当前 config 指向 B，resolve 用其 credential_id 取到 B 的 key，而非旧 A
    cfg = load_runtime_config(config_path)
    resolved = resolve_key(cfg.provider, store=store, credential_id=cfg.credential_id)
    assert resolved.value == "key-b"


def test_save_keystore_failure_leaves_old_config_untouched(tmp_path):
    # 钥匙串写入失败时：先存 key 再写 config 的顺序保证 config 不被改到新端点，
    # 旧 (config, key) 配对保持一致，杜绝「旧 key 发往新端点」
    from violet_refine.auth import InMemoryKeyStore
    from violet_refine.config import RuntimeConfig, save_runtime_config
    from violet_refine.llm import FakeLLMClient
    import threading
    import urllib.request
    from urllib.parse import urlencode
    from urllib.error import HTTPError

    class FailingStore(InMemoryKeyStore):
        def set(self, name, value):
            raise RuntimeError("keychain denied")

    config_path = tmp_path / "config.toml"
    # 预置旧配置：openai-compatible 指向端点 A
    save_runtime_config(
        RuntimeConfig(provider="openai-compatible", model="m", api_base="https://a.example/v1",
                      credential_id="openai-compatible::https://a.example/v1"),
        config_path,
    )
    store = FailingStore({"openai-compatible::https://a.example/v1": "key-a"})
    server, url, token = create_setup_server(
        store=store, llm_client=FakeLLMClient(["ok"]), config_path=config_path, token="t"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            url + "save",
            data=urlencode({"setup_token": "t", "provider": "openai-compatible",
                            "api_key": "key-b", "model": "m", "api_base": "https://b.example/v1"}).encode(),
            method="POST",
        )
        with pytest.raises(HTTPError):
            urllib.request.urlopen(req)
    finally:
        server.shutdown()
        server.server_close()
    # 钥匙串失败 → 配置仍指向旧端点 A、旧 key 仍在，未出现「A 的 key 配 B 端点」
    cfg = load_runtime_config(config_path)
    assert cfg.api_base == "https://a.example/v1"
    assert store.get("openai-compatible::https://a.example/v1") == "key-a"


def test_config_write_failure_after_store_leaves_old_config(tmp_path, monkeypatch):
    # F4（轻量）：存 key 成功但写 config 失败时，旧 config 不被半写坏——因为顺序是
    # 校验→存 key→写 config，写 config 是最后一步，失败则磁盘上仍是旧配置
    import violet_refine.setup_page as sp
    from violet_refine.auth import InMemoryKeyStore
    from violet_refine.config import RuntimeConfig, save_runtime_config
    import urllib.request
    from urllib.parse import urlencode
    from urllib.error import HTTPError

    config_path = tmp_path / "config.toml"
    save_runtime_config(
        RuntimeConfig(provider="openai-compatible", model="m", api_base="https://a.example/v1",
                      credential_id="openai-compatible::https://a.example/v1"),
        config_path,
    )
    store = InMemoryKeyStore({"openai-compatible::https://a.example/v1": "key-a"})

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(sp, "save_runtime_config", _boom)
    server, url, token = create_setup_server(
        store=store, llm_client=FakeLLMClient(["ok"]), config_path=config_path, token="t"
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            url + "save",
            data=urlencode({"setup_token": "t", "provider": "openai-compatible",
                            "api_key": "key-b", "model": "m", "api_base": "https://b.example/v1"}).encode(),
            method="POST",
        )
        with pytest.raises(HTTPError):
            urllib.request.urlopen(req)
    finally:
        server.shutdown()
        server.server_close()
    # 磁盘配置仍是旧端点 A；新 key 落进 B 的独立槽（孤儿、无害），旧 A 槽不动
    cfg = load_runtime_config(config_path)
    assert cfg.api_base == "https://a.example/v1"
    assert store.get("openai-compatible::https://a.example/v1") == "key-a"


def test_post_test_google_probe_ok_when_truncated(tmp_path, monkeypatch):
    # 探测故意只给 16 token，Gemini 必然 MAX_TOKENS 截断；走真实 HttpLLMClient，
    # 截断说明鉴权已通过，探测应报成功而非错误
    import httpx

    from violet_refine.llm import HttpLLMClient

    class _Resp:
        status_code = 200

        def json(self):
            return {"candidates": [{
                "content": {"parts": [{"text": "想", "thought": True}]},
                "finishReason": "MAX_TOKENS",
                "continuationToken": "tok",
            }]}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    server, url, _ = create_setup_server(
        store=InMemoryKeyStore(), llm_client=HttpLLMClient(),
        config_path=tmp_path / "config.toml", token="t",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            url + "test",
            {"provider": "google", "api_key": "g-key", "model": "", "api_base": ""},
        )
    finally:
        server.shutdown()
        server.server_close()
    assert status == 200
    assert json.loads(body)["ok"] is True


def _probe_with_http_client(tmp_path, monkeypatch, provider, payload):
    # 走真实 HttpLLMClient，只在 httpx.post（系统边界）回放给定响应
    import httpx

    from violet_refine.llm import HttpLLMClient

    class _Resp:
        status_code = 200

        def json(self):
            return payload

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    server, url, _ = create_setup_server(
        store=InMemoryKeyStore(), llm_client=HttpLLMClient(),
        config_path=tmp_path / "config.toml", token="t",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post(
            url + "test",
            {"provider": provider, "api_key": "k", "model": "", "api_base": ""},
        )
    finally:
        server.shutdown()
        server.server_close()
    assert status == 200
    return json.loads(body)


def test_post_test_google_probe_fails_on_safety(tmp_path, monkeypatch):
    # /test 只豁免截断：被内容审核拦下不能报「key 可用」，错误文案也不回显枚举值
    result = _probe_with_http_client(
        tmp_path, monkeypatch, "google",
        {"candidates": [{"content": {"parts": [{"text": "半截"}]}, "finishReason": "SAFETY"}]},
    )
    assert result["ok"] is False
    assert "SAFETY" not in result["error"]
    assert "半截" not in result["error"]


def test_post_test_deepseek_probe_ok_when_length(tmp_path, monkeypatch):
    # 16 token 探测下 finish_reason=length 是预期结果：截断说明鉴权已通过
    result = _probe_with_http_client(
        tmp_path, monkeypatch, "deepseek",
        {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
    )
    assert result["ok"] is True
