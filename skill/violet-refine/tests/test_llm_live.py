"""Live 冒烟：真实 DeepSeek / Gemini 调用，验证自研客户端的 wire 与鉴权。

只认环境变量（DEEPSEEK_API_KEY / GEMINI_API_KEY），无则跳过（CI 默认跳过）；
不在测试里读钥匙串，避免后台运行时阻塞在系统授权弹窗上。key 绝不打印。
"""

from __future__ import annotations

import os

import pytest

from violet_refine.auth import PROVIDERS
from violet_refine.llm import HttpLLMClient, LLMRequestError
from violet_refine.llm.errors import LLMTruncatedError


def _live_env_name(provider: str) -> str:
    # 用运行时的真实映射，避免 google→GOOGLE_API_KEY（实际是 GEMINI_API_KEY）这类错配导致静默跳过
    return PROVIDERS[provider].env


def _live_key(provider: str) -> str:
    env_name = _live_env_name(provider)
    value = os.environ.get(env_name, "")
    if not value:
        pytest.skip(f"no live key in env: {env_name}")
    return value


def test_live_env_name_matches_runtime_provider_env():
    # 非跳过的守卫：live 冒烟找的 env 名必须与 resolve_key 用的一致
    assert _live_env_name("google") == "GEMINI_API_KEY"
    assert _live_env_name("deepseek") == "DEEPSEEK_API_KEY"
    assert _live_env_name("openai-compatible") == "OPENAI_API_KEY"


def test_live_deepseek_max_effort_returns_text_and_accepts_params():
    key = _live_key("deepseek")
    client = HttpLLMClient()
    text = client.complete(
        [{"role": "user", "content": "用一句中文说「确认收到」"}],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
        max_tokens=512,
        timeout=120,
        api_key=key,
        thinking={"type": "enabled"},
        reasoning_effort="max",
    )
    # 请求被服务端接受（4xx 会抛 LLMRequestError），且拿到非空正文
    assert text.strip()


def test_live_deepseek_disabled_thinking_probe_succeeds():
    key = _live_key("deepseek")
    HttpLLMClient().complete(
        [{"role": "user", "content": "回复一个字：好"}],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
        max_tokens=16,
        timeout=60,
        api_key=key,
        thinking={"type": "disabled"},
    )
    # 不抛异常即 key 可用；content 可为空


def test_live_gemini_medium_effort_returns_text():
    key = _live_key("google")
    client = HttpLLMClient()
    text = client.complete(
        [
            {"role": "system", "content": "你是中文校对。"},
            {"role": "user", "content": "用一句中文说「确认收到」"},
        ],
        provider="google",
        model="gemini/gemini-3.8-flash",
        max_tokens=1024,
        timeout=120,
        api_key=key,
        reasoning_effort="medium",
    )
    assert text.strip()


def test_live_gemini_4_argon_returns_text():
    # Gemini 4 不对免费层开放；用 CLI 实际下发的参数（131K 总预算、20 分钟超时）
    key = _live_key("google")
    client = HttpLLMClient()
    text = client.complete(
        [
            {"role": "system", "content": "你是中文校对。"},
            {"role": "user", "content": "用一句中文说「确认收到」"},
        ],
        provider="google",
        model="gemini/gemini-4-argon",
        max_tokens=131_072,
        timeout=1200,
        api_key=key,
        reasoning_effort="medium",
    )
    assert text.strip()


def test_live_gemini_4_argon_long_output_continues_past_single_hop():
    # 真 long-decode：输出约 40K token，超过非流式单跳 32K，必须经 CONTINUATION 续写一跳才完整。
    # 约 80K 输入 + 40K 输出 token、耗时约 5 分钟，需显式 VIOLET_LIVE_LONG=1 才跑
    if os.environ.get("VIOLET_LIVE_LONG") != "1":
        pytest.skip("long live test needs VIOLET_LIVE_LONG=1")
    key = _live_key("google")
    total = 1500
    line = "春天的风吹过田野，农民在地里播种，孩子们在河边奔跑。"
    source = "\n".join(f"第{i}行：{line}" for i in range(1, total + 1))
    text = HttpLLMClient().complete(
        [{"role": "user", "content": f"请把下面的文本逐字原样复制输出，一行都不能省略，不要加任何说明：\n\n{source}"}],
        provider="google",
        model="gemini/gemini-4-argon",
        max_tokens=131_072,
        timeout=1200,
        api_key=key,
        reasoning_effort="medium",
    )
    # 跨跳拼接无缺漏无重复：行号从 1 连续到末行（单跳 32K 约止于第 1210 行）
    numbers = [int(row.split("行")[0].removeprefix("第")) for row in text.strip().splitlines() if row.startswith("第")]
    assert numbers == list(range(1, total + 1))


def test_live_gemini_4_argon_setup_probe_succeeds():
    # setup 页 /test 探测形态：16 token + low；与 /test 一致，截断说明已过鉴权
    key = _live_key("google")
    try:
        HttpLLMClient().complete(
            [{"role": "user", "content": "回复一个字：好"}],
            provider="google",
            model="gemini/gemini-4-argon",
            max_tokens=16,
            timeout=30,
            api_key=key,
            reasoning_effort="low",
        )
    except LLMTruncatedError:
        pass


def test_live_gemini_bad_key_is_redacted_error():
    # 错 key 必须返回 4xx LLMRequestError，且消息不含我们传入的假 key
    client = HttpLLMClient()
    with pytest.raises(LLMRequestError) as excinfo:
        client.complete(
            [{"role": "user", "content": "hi"}],
            provider="google",
            model="gemini/gemini-3.8-flash",
            max_tokens=16,
            timeout=60,
            api_key="fake-key-for-redaction-check",
        )
    assert excinfo.value.status_code is not None and excinfo.value.status_code >= 400
    assert "fake-key-for-redaction-check" not in str(excinfo.value)


def test_live_openai_compatible_real_endpoint():
    # 对真实 OpenAI 端点走一次自定义接入：标准 /v1/chat/completions、裸模型名
    key = _live_key("openai-compatible")
    client = HttpLLMClient()
    text = client.complete(
        [{"role": "user", "content": "回复一个字：好"}],
        provider="openai-compatible",
        model="gpt-4o-mini",
        max_tokens=16,
        timeout=60,
        api_key=key,
        api_base="https://api.openai.com/v1",
    )
    # 鉴权探测语义：请求被接受即可，content 可为空
    assert isinstance(text, str)
