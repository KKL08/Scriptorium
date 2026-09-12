from __future__ import annotations

from typing import Any, Protocol

import httpx

from violet_refine.auth import ensure_api_key_usable
from violet_refine.llm.adapters import ADAPTERS
from violet_refine.llm.errors import LLMRequestError


def _status_message(status: int) -> str:
    """把 HTTP 状态码映射成受控、可读的固定文案。

    绝不回显上游响应体或原始异常原文——脱敏是打地鼠（key 含引号/反斜杠被 JSON 转义后
    正则/replace 都会漏），最稳的做法是根本不把上游原文放进对外错误里。
    """
    if status in (401, 403):
        return "鉴权失败：API Key 无效或无权限。"
    if status == 404:
        return "接口或模型不存在，请检查模型名与 Base URL。"
    if status == 429:
        return "请求被限流，请稍后重试。"
    if 500 <= status < 600:
        return "服务端错误，请稍后重试。"
    return f"请求被拒绝（HTTP {status}）。"


class LLMClient(Protocol):
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
    ) -> str: ...


class HttpLLMClient:
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
        adapter = ADAPTERS.get(provider)
        if adapter is None:
            raise LLMRequestError(
                provider, None, f"内置客户端暂不支持 provider {provider}，添加 adapter 后启用"
            )
        # 发请求前先校验 key 无 header 非法字符：否则底层 HTTP 库序列化 header 时会抛出
        # 带 key 明文的异常（如换行 key 触发 h11 Illegal header value），脱敏难以完全兜住。
        # 固定消息、不含 key，也保证非法 key 一次都不触网。
        if api_key is not None:
            try:
                ensure_api_key_usable(api_key)
            except ValueError as error:
                raise LLMRequestError(provider, None, str(error)) from None
        # 构造、发送、解析三阶段整体兜底。对外错误只用受控摘要。原始异常（httpx/h11）的 repr、
        # traceback 与 __context__ 都可能带 key——先在 except 里把受控异常存起来，出 except 块后
        # 再抛：此时无活动异常上下文，异常的 __context__/__cause__ 均为 None，遍历也取不到原文。
        error: LLMRequestError | None = None
        try:
            url, headers, body = adapter.build(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                api_key=api_key,
                api_base=api_base,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
            )
            resp = httpx.post(url, headers=headers, json=body, timeout=timeout)
            if not 200 <= resp.status_code < 300:
                error = LLMRequestError(provider, resp.status_code, _status_message(resp.status_code))
            else:
                return adapter.parse(resp.json())
        except LLMRequestError as known:
            error = known
        except Exception:  # noqa: BLE001 - 不透传原始异常，避免其 repr/traceback/__context__ 带出 key
            error = LLMRequestError(provider, None, "请求发送失败，请检查网络连接与接口配置。")
        raise error
