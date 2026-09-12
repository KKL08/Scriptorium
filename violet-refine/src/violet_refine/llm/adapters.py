from __future__ import annotations

from typing import Any, Protocol

from violet_refine.llm.errors import LLMRequestError


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

    def parse(self, data: dict[str, Any]) -> str: ...


class OpenAICompatibleAdapter:
    """标准 OpenAI Chat Completions 形态（DeepSeek 与自定义兼容端点共用）。

    base 原样拼接 /chat/completions，不替用户补 /v1（DeepSeek 无 /v1，
    Ollama/vLLM 等自定义端点的 base 通常已含所需路径）。
    """

    def __init__(self, *, default_base: str | None, strip_prefix: str | None) -> None:
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

    def parse(self, data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return message.get("content") or ""


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

    def parse(self, data: dict[str, Any]) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        # 全程防御式 .get()：candidate 缺 content/parts 视作空正文，不 KeyError
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        return "".join(part.get("text", "") for part in parts if part.get("thought") is not True)


ADAPTERS: dict[str, Adapter] = {
    "deepseek": OpenAICompatibleAdapter(
        default_base="https://api.deepseek.com", strip_prefix="deepseek/"
    ),
    "openai-compatible": OpenAICompatibleAdapter(default_base=None, strip_prefix=None),
    "google": GeminiAdapter(
        default_base="https://generativelanguage.googleapis.com", strip_prefix="gemini/"
    ),
}
