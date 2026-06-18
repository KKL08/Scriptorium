from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import keyring

KEYRING_SERVICE = "violet-refine"
MISSING_KEY_MESSAGE = "本地 API Key 还没配置好。运行 violet-refine auth --ui 打开本机配置页面，API Key 只填在本机页面里，不要发到聊天里。"


@dataclass(frozen=True)
class Provider:
    env: str
    default_model: str
    label: str
    key_url: str


# 顺序就是 setup 页面下拉的顺序，第一项是默认选中项；主要用户在 Codex/Claude，默认推荐 DeepSeek
PROVIDERS: dict[str, Provider] = {
    "deepseek": Provider(
        env="DEEPSEEK_API_KEY",
        default_model="deepseek/deepseek-v4-pro",
        label="DeepSeek",
        key_url="https://platform.deepseek.com/",
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


@dataclass(frozen=True)
class ResolvedKey:
    value: str
    source: str


def provider_for(name: str) -> Provider:
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}. Valid providers: {', '.join(PROVIDERS)}.")
    return PROVIDERS[name]


def resolve_key(provider_name: str, *, store: KeyStore | None = None) -> ResolvedKey:
    provider = provider_for(provider_name)
    env_value = os.environ.get(provider.env)
    if env_value:
        return ResolvedKey(value=env_value, source="env")
    key_store = store or KeyringStore()
    stored = key_store.get(provider.env)
    if stored:
        return ResolvedKey(value=stored, source="keychain")
    raise MissingKeyError()
