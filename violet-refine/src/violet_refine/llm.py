from __future__ import annotations

from typing import Any, Protocol

import litellm


class LLMClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int = 8192,
        timeout: int | float = 300,
        api_key: str | None = None,
        api_base: str | None = None,
        thinking: dict[str, str] | None = None,
        reasoning_effort: str | None = None,
    ) -> str: ...


class LiteLLMClient:
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int = 8192,
        timeout: int | float = 300,
        api_key: str | None = None,
        api_base: str | None = None,
        thinking: dict[str, str] | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "stream": False,
        }
        if api_key is not None:
            kwargs["api_key"] = api_key
        if api_base is not None:
            kwargs["api_base"] = api_base
        if thinking is not None:
            kwargs["thinking"] = thinking
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
        response = litellm.completion(**kwargs)
        return response.choices[0].message.content


class FakeLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        max_tokens: int = 8192,
        timeout: int | float = 300,
        api_key: str | None = None,
        api_base: str | None = None,
        thinking: dict[str, str] | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "timeout": timeout,
                "api_key": api_key,
                "api_base": api_base,
                "thinking": thinking,
                "reasoning_effort": reasoning_effort,
            }
        )
        return self.responses.pop(0)
