from __future__ import annotations

from typing import Any


class FakeLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        provider: str,
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
                "provider": provider,
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
