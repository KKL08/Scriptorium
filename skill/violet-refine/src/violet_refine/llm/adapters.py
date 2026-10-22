from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from violet_refine.llm.errors import LLMRequestError, LLMTruncatedError


@dataclass(frozen=True)
class Reply:
    """一跳响应的解析结果。continuation 非 None 表示正文未完：合入原请求体顶层再发一跳。

    is_complete 表示这一跳是否正常结束（Gemini 仅 STOP）；非正常结束时正文为空或半截，不能当结果交出。
    """

    text: str
    continuation: dict[str, Any] | None = None
    is_complete: bool = True


class Adapter(Protocol):
    """provider 的 wire 翻译器：归一化参数 → 该厂商的 URL/headers/body，响应 → 正文文本。"""

    def build(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        api_key: str | None,
        api_base: str | None,
        thinking: dict[str, str] | None,
        reasoning_effort: str | None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]: ...

    def parse(self, data: dict[str, Any]) -> Reply: ...


# DeepSeek 官方枚举中的非正常结束：正文被过滤或生成被打断。自定义端点取值不统一，只拦这几个已知值
_OPENAI_ABORTED_FINISH_REASONS = frozenset({"content_filter", "insufficient_system_resource", "aborted"})


class OpenAICompatibleAdapter:
    """标准 OpenAI Chat Completions 形态（DeepSeek 与自定义兼容端点共用）。

    base 原样拼接 /chat/completions，不替用户补 /v1（DeepSeek 无 /v1，
    Ollama/vLLM 等自定义端点的 base 通常已含所需路径）。
    """

    def __init__(self, *, provider: str, default_base: str | None, strip_prefix: str | None) -> None:
        self.provider = provider
        self.default_base = default_base
        self.strip_prefix = strip_prefix

    def build(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        api_key: str | None,
        api_base: str | None,
        thinking: dict[str, str] | None,
        reasoning_effort: str | None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        base = api_base or self.default_base
        if not base:
            raise LLMRequestError("openai-compatible", None, "自定义 OpenAI 接口需填写 Base URL")
        wire_model = model.removeprefix(self.strip_prefix) if self.strip_prefix and model.startswith(self.strip_prefix) else model
        url = f"{base.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body: dict[str, Any] = {
            "model": wire_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # DeepSeek 思考模式：thinking 与 reasoning_effort 均为顶层字段（官方 thinking_mode 指南）
        if thinking:
            body["thinking"] = {"type": thinking.get("type")}
        if reasoning_effort and reasoning_effort != "none":
            body["reasoning_effort"] = reasoning_effort
        return url, headers, body

    def parse(self, data: dict[str, Any]) -> Reply:
        choices = data.get("choices") or []
        if not choices:
            return Reply("")
        finish_reason = choices[0].get("finish_reason")
        # length：max_tokens 用尽，正文只有半截；文案受控，不回显正文
        if finish_reason == "length":
            raise LLMTruncatedError(self.provider)
        message = choices[0].get("message") or {}
        return Reply(message.get("content") or "", is_complete=finish_reason not in _OPENAI_ABORTED_FINISH_REASONS)


class GeminiAdapter:
    """Google generateContent 端点；认证只走 x-goog-api-key header，key 不进 URL。"""

    def __init__(self, *, default_base: str, strip_prefix: str | None) -> None:
        self.default_base = default_base
        self.strip_prefix = strip_prefix

    def build(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        api_key: str | None,
        api_base: str | None,
        thinking: dict[str, str] | None,
        reasoning_effort: str | None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        wire_model = model.removeprefix(self.strip_prefix) if self.strip_prefix and model.startswith(self.strip_prefix) else model
        # 无 api_base：默认 base 补 /v1beta 版本段；有 api_base（网关）：视为用户已带版本段
        versioned_base = api_base.rstrip("/") if api_base else f"{self.default_base}/v1beta"
        url = f"{versioned_base}/models/{wire_model}:generateContent"
        headers = {"x-goog-api-key": api_key or "", "Content-Type": "application/json"}

        system_parts: list[dict[str, str]] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role", "user")
            text = message.get("content", "")
            if role == "system":
                system_parts.append({"text": text})
                continue
            contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]})

        body: dict[str, Any] = {"contents": contents}
        if system_parts:
            body["systemInstruction"] = {"parts": system_parts}
        generation_config: dict[str, Any] = {"maxOutputTokens": max_tokens}
        # Gemini 恒思考，忽略 thinking 开关；effort 档位 low/medium/high 直接映射
        if reasoning_effort and reasoning_effort != "none":
            generation_config["thinkingConfig"] = {
                "thinkingLevel": reasoning_effort,
                "includeThoughts": True,
            }
        body["generationConfig"] = generation_config
        return url, headers, body

    def parse(self, data: dict[str, Any]) -> Reply:
        candidates = data.get("candidates") or []
        if not candidates:
            return Reply("", is_complete=False)
        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        token = candidate.get("continuationToken")
        # MAX_TOKENS：maxOutputTokens 总预算（思考 + 正文，跨所有续写跳）用尽，同预算续写会 400。
        # 截断时绝不把半截正文当完整结果交出；文案受控，不回显正文或续写 token
        if finish_reason == "MAX_TOKENS" or (finish_reason == "CONTINUATION" and not token):
            raise LLMTruncatedError("google")
        # 全程防御式 .get()：candidate 缺 content/parts 视作空正文，不 KeyError
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        # 每跳 parts 是增量（实测），只取非思考正文；整跳都在思考时正文为空
        text = "".join(part.get("text", "") for part in parts if part.get("thought") is not True)
        # CONTINUATION：单跳到上限（非流式 32K）、预算未尽——原请求顶层加 token 续写
        if finish_reason == "CONTINUATION":
            return Reply(text, {"continuationToken": token}, is_complete=False)
        return Reply(text, is_complete=finish_reason == "STOP")


ADAPTERS: dict[str, Adapter] = {
    "deepseek": OpenAICompatibleAdapter(
        provider="deepseek", default_base="https://api.deepseek.com", strip_prefix="deepseek/"
    ),
    "openai-compatible": OpenAICompatibleAdapter(provider="openai-compatible", default_base=None, strip_prefix=None),
    "google": GeminiAdapter(
        default_base="https://generativelanguage.googleapis.com", strip_prefix="gemini/"
    ),
}
