"""HttpLLMClient 的行为测试：通过 complete() seam + 假 httpx.post（系统边界）观察 wire。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from violet_refine.llm import HttpLLMClient
from violet_refine.llm.errors import LLMRequestError


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text if text else json.dumps(self._payload)

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def wire(monkeypatch):
    """捕获 HttpLLMClient 发出的 url/headers/body；可重设响应、按序排多跳响应，或让 post 抛异常。"""
    captured: dict[str, Any] = {
        "calls": [],
        "response": FakeResponse(payload={"choices": [{"message": {"content": "好"}}]}),
        "responses": [],  # 非空时按序逐跳返回（续写），优先于 response
    }
    raised: dict[str, Exception] = {}

    def fake_post(url, *, headers=None, json=None, timeout=None):  # noqa: A002
        captured["calls"].append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if "exc" in raised:
            raise raised["exc"]
        if captured["responses"]:
            return captured["responses"].pop(0)
        return captured["response"]

    monkeypatch.setattr(httpx, "post", fake_post)
    captured["raise"] = lambda exc: raised.update({"exc": exc})
    return captured


def test_deepseek_sends_top_level_thinking_and_effort(wire):
    client = HttpLLMClient()
    result = client.complete(
        [{"role": "user", "content": "hi"}],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
        max_tokens=384_000,
        api_key="sk-live",
        thinking={"type": "enabled"},
        reasoning_effort="max",
    )
    assert result == "好"
    call = wire["calls"][0]
    # DeepSeek base 不带 /v1（官方文档实证）
    assert call["url"] == "https://api.deepseek.com/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-live"
    # thinking 与 reasoning_effort 均为 body 顶层字段，互不嵌套（litellm 曾丢弃，此为修正）
    assert call["json"]["thinking"] == {"type": "enabled"}
    assert call["json"]["reasoning_effort"] == "max"
    assert call["json"]["model"] == "deepseek-v4-pro"
    assert call["json"]["max_tokens"] == 384_000
    assert call["json"]["stream"] is False


def test_deepseek_probe_disables_thinking_without_effort(wire):
    client = HttpLLMClient()
    client.complete(
        [{"role": "user", "content": "回复一个字：好"}],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
        max_tokens=16,
        timeout=30,
        api_key="sk-live",
        thinking={"type": "disabled"},
    )
    body = wire["calls"][0]["json"]
    assert body["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in body


def test_deepseek_parse_returns_empty_for_missing_content(wire):
    wire["response"] = FakeResponse(payload={"choices": [{"message": {}}]})
    assert HttpLLMClient().complete(
        [{"role": "user", "content": "hi"}],
        provider="deepseek", model="deepseek/deepseek-v4-pro", api_key="sk",
    ) == ""
    wire["response"] = FakeResponse(payload={"choices": [{"message": {"content": None}}]})
    assert HttpLLMClient().complete(
        [{"role": "user", "content": "hi"}],
        provider="deepseek", model="deepseek/deepseek-v4-pro", api_key="sk",
    ) == ""


def test_openai_compatible_without_base_reports_clear_error(wire):
    with pytest.raises(LLMRequestError, match="Base URL"):
        HttpLLMClient().complete(
            [{"role": "user", "content": "hi"}],
            provider="openai-compatible", model="gpt-4o", api_key="sk-x",
        )


def test_openai_compatible_posts_minimal_body_to_user_base(wire):
    client = HttpLLMClient()
    client.complete(
        [{"role": "user", "content": "hi"}],
        provider="openai-compatible",
        model="org/model",
        api_key="sk-x",
        api_base="http://localhost:11434/v1",
    )
    call = wire["calls"][0]
    assert call["url"] == "http://localhost:11434/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-x"
    # 自定义裸名原样保留（含 / 也不剥），且不发思考参数，最大兼容
    assert call["json"] == {
        "model": "org/model",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 8192,
        "stream": False,
    }


def test_gemini_request_maps_roles_and_thinking(wire):
    wire["response"] = FakeResponse(
        payload={"candidates": [{"content": {"parts": [{"text": "好"}]}}]}
    )
    client = HttpLLMClient()
    result = client.complete(
        [
            {"role": "system", "content": "你是校对"},
            {"role": "user", "content": "第一句"},
            {"role": "assistant", "content": "中间回复"},
            {"role": "user", "content": "第二句"},
        ],
        provider="google",
        model="gemini/gemini-3.8-flash",
        api_key="goog-key",
        reasoning_effort="medium",
    )
    assert result == "好"
    call = wire["calls"][0]
    assert call["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    )
    # key 只进 header，绝不进 URL query（隐私红线）
    assert "goog-key" not in call["url"]
    assert call["headers"]["x-goog-api-key"] == "goog-key"
    body = call["json"]
    assert body["systemInstruction"] == {"parts": [{"text": "你是校对"}]}
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "第一句"}]},
        {"role": "model", "parts": [{"text": "中间回复"}]},
        {"role": "user", "parts": [{"text": "第二句"}]},
    ]
    assert body["generationConfig"]["maxOutputTokens"] == 8192
    assert body["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "medium",
        "includeThoughts": True,
    }


def test_gemini_custom_base_keeps_version_segment(wire):
    wire["response"] = FakeResponse(payload={"candidates": []})
    client = HttpLLMClient()
    client.complete(
        [{"role": "user", "content": "hi"}],
        provider="google", model="gemini/gemini-3.8-flash",
        api_key="k", api_base="https://gw/v1beta",
    )
    # 自定义 base 视为已带版本段，只补 /models/...，不得出现 /v1beta/v1beta
    assert wire["calls"][0]["url"] == "https://gw/v1beta/models/gemini-3.8-flash:generateContent"


def _gemini_complete(wire, payload):
    wire["response"] = FakeResponse(payload=payload)
    return HttpLLMClient().complete(
        [{"role": "user", "content": "hi"}],
        provider="google", model="gemini/gemini-3.8-flash", api_key="k",
    )


def test_gemini_parse_skips_thought_parts(wire):
    payload = {"candidates": [{"content": {"parts": [
        {"text": "思考中…", "thought": True},
        {"text": "正文"},
    ]}}]}
    assert _gemini_complete(wire, payload) == "正文"


def test_gemini_parse_all_thought_returns_empty(wire):
    payload = {"candidates": [{"content": {"parts": [{"text": "只有思考", "thought": True}]}}]}
    assert _gemini_complete(wire, payload) == ""


def test_gemini_parse_missing_candidates_returns_empty(wire):
    assert _gemini_complete(wire, {}) == ""
    assert _gemini_complete(wire, {"candidates": []}) == ""


def test_gemini_parse_missing_content_or_parts_returns_empty(wire):
    # finishReason 等原因导致 candidate 无 content：合法但空，不抛 KeyError
    assert _gemini_complete(wire, {"candidates": [{"finishReason": "SAFETY"}]}) == ""
    assert _gemini_complete(wire, {"candidates": [{"content": {}}]}) == ""


def test_unknown_provider_raises_clear_error(wire):
    with pytest.raises(LLMRequestError, match="暂不支持 provider anthropic"):
        HttpLLMClient().complete(
            [{"role": "user", "content": "hi"}],
            provider="anthropic", model="anthropic/claude-fable-5", api_key="k",
        )


def test_non_2xx_error_uses_controlled_summary_no_upstream_body(wire):
    # 含引号的 key（能过校验）被 401 回显、JSON 转义后 replace/正则都会漏——
    # 受控摘要方案根本不回显上游 body：错误只含固定文案，不含 key、也不含上游原文
    secret = 'sk-live"secret\\x'
    wire["response"] = FakeResponse(
        status_code=401, text=f'{{"error": {{"message": "bad key {secret}"}}}}'
    )
    with pytest.raises(LLMRequestError) as excinfo:
        HttpLLMClient().complete(
            [{"role": "user", "content": "hi"}],
            provider="deepseek", model="deepseek/deepseek-v4-pro", api_key=secret,
        )
    message = str(excinfo.value)
    assert "sk-live" not in message
    assert "bad key" not in message  # 上游原文一律不回显
    assert "鉴权失败" in message


def test_error_chain_traceback_has_no_key(wire):
    # from None 断链：即便打印完整 traceback，也不应出现 key（Codex 复现的 traceback 泄漏）
    import traceback

    secret = "sk-chain-secret-123"
    wire["raise"](httpx.ConnectError(f"failed connecting with Bearer {secret}"))
    with pytest.raises(LLMRequestError) as excinfo:
        HttpLLMClient().complete(
            [{"role": "user", "content": "hi"}],
            provider="deepseek", model="deepseek/deepseek-v4-pro", api_key=secret,
        )
    full_tb = "".join(traceback.format_exception(excinfo.value))
    assert secret not in full_tb
    # 出 except 块后再抛：上下文链为空，显式遍历 __context__/__cause__ 也取不到原始异常
    assert excinfo.value.__context__ is None
    assert excinfo.value.__cause__ is None


def test_illegal_header_key_rejected_before_any_connection():
    # 端到端真 httpx：含换行的 key 曾在发送阶段触发带 key 的 LocalProtocolError。
    # 前置校验修复后，这类 key 在连接建立前就被拒——监听 socket 不该收到任何连接，
    # 且异常不泄露 key 主体。
    import socket
    import threading

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    accepted = []

    def drain() -> None:
        server.settimeout(1.5)
        try:
            conn, _ = server.accept()
            accepted.append(True)
            conn.close()
        except OSError:
            pass

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    try:
        with pytest.raises(LLMRequestError) as excinfo:
            HttpLLMClient().complete(
                [{"role": "user", "content": "hi"}],
                provider="openai-compatible",
                model="m",
                api_key="sk-bad\nkey",
                api_base=f"http://127.0.0.1:{port}",
            )
        assert "sk-bad" not in str(excinfo.value)
    finally:
        server.close()
        thread.join(timeout=2)
    assert accepted == []  # 校验先于连接，非法 key 一次都没触网


def test_complete_validates_illegal_header_key_before_request_no_leak(monkeypatch):
    # 含换行的 key 会让 h11 在序列化 header 时抛出带 key 的异常；客户端必须在发请求前
    # 就拦下，绝不触网、也绝不泄漏 key 主体（Codex-v2 高危项复现）
    import violet_refine.llm.client as client_mod

    called = []

    def _rec(*args, **kwargs):
        called.append(True)
        return FakeResponse(200, {"choices": [{"message": {"content": "x"}}]})

    monkeypatch.setattr(client_mod.httpx, "post", _rec)
    secret = "AIza-secret-body\n"
    with pytest.raises(LLMRequestError) as excinfo:
        HttpLLMClient().complete(
            [{"role": "user", "content": "hi"}],
            provider="google",
            model="gemini/gemini-3.8-flash",
            api_key=secret,
            reasoning_effort="medium",
        )
    # 校验必须发生在发请求之前：post 一次都不能被调用
    assert called == []
    assert "AIza-secret-body" not in str(excinfo.value)


def test_gemini_truncated_response_raises_controlled_error(wire):
    from violet_refine.llm.errors import LLMTruncatedError

    # 总预算（思考 + 正文，跨所有续写跳）用尽：正文只有半截，带 token 也不再续写
    payload = {"candidates": [{
        "content": {"parts": [{"text": "思考中…", "thought": True}, {"text": "半截正"}]},
        "finishReason": "MAX_TOKENS",
        "continuationToken": "CiQ4ZmQ3-secret-token",
    }]}
    with pytest.raises(LLMTruncatedError) as excinfo:
        _gemini_complete(wire, payload)
    message = str(excinfo.value)
    assert "截断" in message
    # 受控文案：不回显半截正文、思考内容或续写 token
    assert "半截正" not in message
    assert "思考中" not in message
    assert "CiQ4ZmQ3" not in message
    # 截断仍属请求失败，调用方按 LLMRequestError 兜底即可
    assert isinstance(excinfo.value, LLMRequestError)


def test_gemini_stop_finish_reason_returns_text(wire):
    payload = {"candidates": [{"content": {"parts": [{"text": "完整正文"}]}, "finishReason": "STOP"}]}
    assert _gemini_complete(wire, payload) == "完整正文"


# —— Gemini long-decode 续写（wire 形态以 2026-10-22 真 key 实测为准）——


def _gemini_hop(text, finish_reason, token=None, thought=None):
    parts = []
    if thought is not None:
        parts.append({"text": thought, "thought": True})
    if text is not None:
        parts.append({"text": text, "thoughtSignature": "sig"})
    candidate: dict[str, Any] = {"content": {"parts": parts}, "finishReason": finish_reason, "index": 0}
    if token is not None:
        candidate["continuationToken"] = token
    return FakeResponse(payload={"candidates": [candidate]})


def _argon_complete(wire, *responses, max_tokens=131_072):
    wire["responses"] = list(responses)
    return HttpLLMClient().complete(
        [{"role": "system", "content": "你是校对"}, {"role": "user", "content": "长文"}],
        provider="google",
        model="gemini/gemini-4-argon",
        max_tokens=max_tokens,
        timeout=1200,
        api_key="goog-key",
        reasoning_effort="medium",
    )


def test_gemini_continuation_resends_identical_request_with_top_level_token(wire):
    result = _argon_complete(
        wire,
        _gemini_hop("第1行：春天的风吹过田野，农民在地里播种", "CONTINUATION", token="tok-1", thought="想一想"),
        _gemini_hop("，孩子们在河边奔跑。", "STOP"),
    )
    # 实测每跳 parts 是增量：拼接各跳非思考正文即完整结果
    assert result == "第1行：春天的风吹过田野，农民在地里播种，孩子们在河边奔跑。"
    first, second = wire["calls"]
    assert "continuationToken" not in first["json"]
    # 续写跳原样重发整份请求（预算不变），只在请求体顶层加 token
    assert second["json"] == {**first["json"], "continuationToken": "tok-1"}
    assert second["url"] == first["url"]
    assert second["headers"] == first["headers"]
    assert second["timeout"] == first["timeout"] == 1200
    assert first["json"]["generationConfig"]["maxOutputTokens"] == 131_072


def test_gemini_continuation_sends_latest_token_and_tolerates_thought_only_hop(wire):
    result = _argon_complete(
        wire,
        # 整跳都花在思考上：CONTINUATION + 空正文，照样续写
        _gemini_hop(None, "CONTINUATION", token="tok-1", thought="长思考"),
        _gemini_hop("前半", "CONTINUATION", token="tok-2"),
        _gemini_hop("后半", "STOP"),
    )
    assert result == "前半后半"
    assert [call["json"].get("continuationToken") for call in wire["calls"]] == [None, "tok-1", "tok-2"]


def test_gemini_max_tokens_on_continuation_hop_raises_without_echo(wire):
    from violet_refine.llm.errors import LLMTruncatedError

    with pytest.raises(LLMTruncatedError) as excinfo:
        _argon_complete(
            wire,
            _gemini_hop("前半正文", "CONTINUATION", token="tok-1-secret"),
            _gemini_hop("半截后文", "MAX_TOKENS", token="tok-2-secret"),
        )
    # 总预算用尽就停：不再拿 MAX_TOKENS 的 token 续写（同预算续写实测 400）
    assert len(wire["calls"]) == 2
    message = str(excinfo.value)
    for leaked in ("前半正文", "半截后文", "tok-1-secret", "tok-2-secret"):
        assert leaked not in message


def test_gemini_continuation_without_token_raises_truncated(wire):
    from violet_refine.llm.errors import LLMTruncatedError

    with pytest.raises(LLMTruncatedError) as excinfo:
        _argon_complete(wire, _gemini_hop("前半", "CONTINUATION"))
    assert len(wire["calls"]) == 1
    assert "前半" not in str(excinfo.value)


def test_gemini_continuation_stops_at_hop_limit(wire):
    from violet_refine.llm.client import MAX_CONTINUATIONS
    from violet_refine.llm.errors import LLMTruncatedError

    endless = [_gemini_hop("片段", "CONTINUATION", token=f"tok-{i}") for i in range(MAX_CONTINUATIONS + 5)]
    with pytest.raises(LLMTruncatedError):
        _argon_complete(wire, *endless)
    # 首跳 + 至多 MAX_CONTINUATIONS 次续写，超出即按截断报错，不无限续
    assert len(wire["calls"]) == MAX_CONTINUATIONS + 1


def test_gemini_continuation_hop_http_error_uses_controlled_summary(wire):
    with pytest.raises(LLMRequestError) as excinfo:
        _argon_complete(
            wire,
            _gemini_hop("前半正文", "CONTINUATION", token="tok-1"),
            FakeResponse(status_code=400, text='{"error": {"message": "max_output_tokens (40000) has already been exhausted"}}'),
        )
    assert excinfo.value.status_code == 400
    message = str(excinfo.value)
    assert "exhausted" not in message  # 上游原文一律不回显
    assert "前半正文" not in message


def test_gemini_continuation_hop_malformed_json_uses_controlled_summary(wire):
    class BrokenJSON(FakeResponse):
        def json(self) -> dict:
            raise ValueError("Expecting value: tok-1 前半正文")

    with pytest.raises(LLMRequestError) as excinfo:
        _argon_complete(wire, _gemini_hop("前半正文", "CONTINUATION", token="tok-1"), BrokenJSON())
    message = str(excinfo.value)
    assert "前半正文" not in message
    assert "tok-1" not in message
    # 后续跳的原始异常同样不进异常链
    assert excinfo.value.__context__ is None
    assert excinfo.value.__cause__ is None


@pytest.mark.parametrize(
    "aborted_hop",
    [
        _gemini_hop("后半截", "SAFETY"),
        _gemini_hop("后半截", "RECITATION"),
        _gemini_hop("后半截", "OTHER"),
        FakeResponse(payload={"candidates": [{"content": {"parts": [{"text": "后半截"}]}}]}),  # 无 finishReason
        FakeResponse(payload={"candidates": []}),
    ],
    ids=["safety", "recitation", "other", "no-finish-reason", "no-candidates"],
)
def test_gemini_non_stop_after_continuation_raises_truncated(wire, aborted_hop):
    from violet_refine.llm.errors import LLMTruncatedError

    # 续写过之后只认 STOP 为正常结束：否则已拼好的前文缺了后半，不能当完整结果交出
    with pytest.raises(LLMTruncatedError) as excinfo:
        _argon_complete(wire, _gemini_hop("前半正文", "CONTINUATION", token="tok-1"), aborted_hop)
    assert len(wire["calls"]) == 2
    message = str(excinfo.value)
    assert "前半正文" not in message
    assert "后半截" not in message
