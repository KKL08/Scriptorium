from __future__ import annotations

import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Protocol

import keyring

KEYRING_SERVICE = "violet-refine"
MISSING_KEY_MESSAGE = "本地 API Key 还没配置好。运行 violet-refine auth --ui 打开本机配置页面，API Key 只填在本机页面里，不要发到聊天里。"


@dataclass(frozen=True)
class ModelSpec:
    id: str  # 持久化模型串，如 "deepseek/deepseek-v4-pro"
    label: str  # 页面展示名，如 "DeepSeek V4 Pro"
    thinking: bool = False  # 是否发思考开关（DeepSeek 用；Gemini 恒思考，不依赖此字段）
    effort_by_mode: Mapping[str, str] = field(default_factory=dict)  # mode -> reasoning_effort
    default_effort: str | None = None  # 未命中 mode 时用
    max_output_tokens: int | None = None  # None 则用 complete 默认 8192


@dataclass(frozen=True)
class Provider:
    env: str
    default_model: str  # 值是 models 里某个 ModelSpec.id
    label: str
    key_url: str
    models: tuple[ModelSpec, ...] = ()  # 空 tuple 表示不在页面展示模型选择


# 顺序就是 setup 页面下拉的顺序，第一项是默认选中项；主要用户在 Codex/Claude，默认推荐 DeepSeek
PROVIDERS: dict[str, Provider] = {
    "deepseek": Provider(
        env="DEEPSEEK_API_KEY",
        default_model="deepseek/deepseek-v4-pro",
        label="DeepSeek",
        key_url="https://platform.deepseek.com/",
        models=(
            ModelSpec(
                id="deepseek/deepseek-v4-pro",
                label="DeepSeek V4 Pro",
                thinking=True,
                effort_by_mode=MappingProxyType({"rewrite": "max"}),
                default_effort="high",
                max_output_tokens=384_000,
            ),
            ModelSpec(
                id="deepseek/deepseek-flash",
                label="DeepSeek V4.1 Flash",
                thinking=True,
                default_effort="high",
                max_output_tokens=384_000,
            ),
        ),
    ),
    "google": Provider(
        env="GEMINI_API_KEY",
        default_model="gemini/gemini-3.7-flash",
        label="Google（Gemini）",
        key_url="https://aistudio.google.com/",
        models=(
            ModelSpec(id="gemini/gemini-3.7-flash", label="Gemini 3.7 Flash", default_effort="medium"),
            ModelSpec(id="gemini/gemini-3.8-flash", label="Gemini 3.8 Flash", default_effort="medium"),
        ),
    ),
    "anthropic": Provider(
        env="ANTHROPIC_API_KEY",
        default_model="anthropic/claude-fable-5",
        label="Anthropic（Claude）",
        key_url="https://platform.claude.com/",
    ),
    "openai-compatible": Provider(
        env="OPENAI_API_KEY",
        default_model="",
        label="OpenAI 兼容接口（自填 Base URL 和模型名）",
        key_url="",
    ),
}

# 已下线模型的持久化旧串 → 目录内现行串（provider 限定，避免误伤 openai-compatible 自填裸名）
RETIRED_MODEL_ALIASES: dict[str, dict[str, str]] = {
    "deepseek": {"deepseek/deepseek-v4-flash": "deepseek/deepseek-flash"},
}


class KeyStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...


class KeyringStore:
    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        self.service = service

    def get(self, name: str) -> str | None:
        return keyring.get_password(self.service, name)

    def set(self, name: str, value: str) -> None:
        keyring.set_password(self.service, name, value)


class InMemoryKeyStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


class MissingKeyError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(MISSING_KEY_MESSAGE)


# value 不进 repr：任何异常堆栈、日志打印这个对象都不能带出 key 明文
@dataclass(frozen=True)
class ResolvedKey:
    value: str = field(repr=False)
    source: str


def provider_for(name: str) -> Provider:
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}. Valid providers: {', '.join(PROVIDERS)}.")
    return PROVIDERS[name]


def model_spec_for(provider_name: str, model: str) -> ModelSpec | None:
    """按 provider 限定查模型元数据；不在目录（如 openai-compatible 自填裸名）返回 None。

    下线模型的旧串按别名归一（provider 限定，两个入口——落盘 config 与 --model 覆盖——都走这里），
    旧串因此不会丢掉推理策略与输出上限元数据。
    """
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        return None
    for spec in provider.models:
        if spec.id == model:
            return spec
    alias_target = RETIRED_MODEL_ALIASES.get(provider_name, {}).get(model)
    if alias_target is None:
        return None
    for spec in provider.models:
        if spec.id == alias_target:
            return spec
    return None


def ensure_api_key_usable(api_key: str) -> None:
    """拒绝含 HTTP header 非法字符的 key（换行/回车/控制字符/前后空白/非 latin-1）。

    这类字符会让底层 HTTP 库在序列化 header 时抛出带 key 明文的异常（脱敏难以完全兜住），
    在发请求和落盘之前就固定报错，从源头掐断泄漏向量。消息不含 key。
    """
    if api_key != api_key.strip():
        raise ValueError("API Key 前后不能有空白字符，请检查后重填。")
    for ch in api_key:
        # httpx 0.28 默认按 ASCII 编码 header：只放行可打印 ASCII（0x20–0x7E）。
        # 控制字符、DEL、以及 0x80–0xFF 的 latin-1/C1 字符发送时会抛 UnicodeEncodeError，
        # 且其异常 repr 可能带 key——一律在此拦下。
        if not 0x20 <= ord(ch) <= 0x7E:
            raise ValueError("API Key 只能包含可打印 ASCII 字符（无换行、控制字符或非 ASCII），请检查后重填。")


def resolve_key(
    provider_name: str, *, store: KeyStore | None = None, credential_id: str | None = None
) -> ResolvedKey:
    provider = provider_for(provider_name)
    # 端点绑定的凭据（credential_id 指向专属槽，如 openai-compatible::<base>）只认该槽，
    # 不吃共享 env 覆盖——否则 env 里的 OPENAI_API_KEY 会被发往用户自填的任意端点。
    endpoint_bound = credential_id is not None and credential_id != provider.env
    if not endpoint_bound:
        env_value = os.environ.get(provider.env)
        if env_value:
            return ResolvedKey(value=env_value, source="env")
    key_store = store or KeyringStore()
    # credential_id 优先（按端点存的槽）；旧配置无此字段则回退 provider.env
    stored = key_store.get(credential_id or provider.env)
    if stored:
        return ResolvedKey(value=stored, source="keychain")
    raise MissingKeyError()
