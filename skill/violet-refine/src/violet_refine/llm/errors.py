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


class LLMTruncatedError(LLMRequestError):
    """模型输出达到长度上限被截断：请求本身成功（鉴权通过），但正文不完整，不能当结果用。"""

    def __init__(self, provider: str) -> None:
        super().__init__(
            provider,
            None,
            "输出达到长度上限被截断（思考过程也占用输出额度），结果不完整已丢弃。可以缩短输入后重试。",
        )


class LLMIncompleteError(LLMRequestError):
    """模型没有正常结束（内容审核拦截、服务端中断等）：请求本身成功，但正文可能为空或半截，不能当结果用。"""

    def __init__(self, provider: str) -> None:
        super().__init__(
            provider,
            None,
            "模型没有正常完成输出（可能触发了内容审核，或服务端中断），结果不完整已丢弃。可以稍后重试，或调整内容后再试。",
        )
