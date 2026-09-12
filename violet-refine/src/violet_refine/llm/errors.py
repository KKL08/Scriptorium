from __future__ import annotations


class LLMRequestError(RuntimeError):
    """模型请求失败；detail 已脱敏（不含 key 明文），可安全展示给用户。"""

    def __init__(self, provider: str, status_code: int | None, detail: str) -> None:
        self.provider = provider
        self.status_code = status_code
        prefix = f"provider {provider}"
        if status_code is not None:
            prefix += f" (HTTP {status_code})"
        super().__init__(f"{prefix}: {detail}")
