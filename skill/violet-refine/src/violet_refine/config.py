from __future__ import annotations

import json
import os
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".violet-refine/config.toml"


@dataclass(frozen=True)
class RuntimeConfig:
    provider: str = "deepseek"
    model: str = "deepseek/deepseek-v4-pro"
    api_base: str | None = None
    # 凭据在钥匙串里的槽名；openai-compatible 按端点区分（避免共享槽把旧 key 发往新端点）。
    # 旧配置无此字段 → None，resolve_key 回退到 provider.env（向后兼容）。
    credential_id: str | None = None


def load_runtime_config(path: str | Path | None = None) -> RuntimeConfig:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return RuntimeConfig()
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if "api_key" in data:
        raise ValueError("Config file must not contain api_key. Run: violet-refine auth --ui")
    api_base = data.get("api_base")
    credential_id = data.get("credential_id")
    return RuntimeConfig(
        provider=str(data.get("provider", RuntimeConfig.provider)),
        model=str(data.get("model", RuntimeConfig.model)),
        api_base=None if api_base is None else str(api_base),
        credential_id=None if credential_id is None else str(credential_id),
    )


def _toml_basic_string(value: str) -> str:
    # JSON 字符串的转义规则（\\ \" 控制字符 \uXXXX）与 TOML basic string 兼容
    return json.dumps(value, ensure_ascii=False)


def _serialize_config(config: RuntimeConfig) -> str:
    """把 config 序列化成 TOML 文本，并 round-trip 校验；无法无损写入的字符在此抛 ValueError。

    与写盘分离，使调用方能在存 key 之前先验证配置可写（坏输入不会先存 key 后写坏文件）。
    """
    lines = [
        f"provider = {_toml_basic_string(config.provider)}",
        f"model = {_toml_basic_string(config.model)}",
    ]
    if config.api_base:
        lines.append(f"api_base = {_toml_basic_string(config.api_base)}")
    if config.credential_id:
        lines.append(f"credential_id = {_toml_basic_string(config.credential_id)}")
    content = "\n".join(lines) + "\n"
    # 空串 api_base/credential_id 不落盘，回读等价 None
    data = tomllib.loads(content)
    if data.get("provider") != config.provider or data.get("model") != config.model:
        raise ValueError("config 含有无法安全写入 TOML 的字符（model/provider）")
    if data.get("api_base") != (config.api_base or None):
        raise ValueError("config 含有无法安全写入 TOML 的字符（api_base）")
    if data.get("credential_id") != (config.credential_id or None):
        raise ValueError("config 含有无法安全写入 TOML 的字符（credential_id）")
    return content


def ensure_config_serializable(config: RuntimeConfig) -> None:
    """校验 config 可无损写入 TOML；不可则抛 ValueError。不写盘。"""
    _serialize_config(config)


def save_runtime_config(config: RuntimeConfig, path: str | Path | None = None) -> None:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    content = _serialize_config(config)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    # 原子写：先写同目录临时文件并 fsync，再 os.replace 原子替换。避免 write_text 的
    # 截断+部分写在磁盘故障时留下缺字段的「合法但错误」配置（缺 credential_id 会回退共享 env
    # 凭据、把 key 发往新端点）。替换成功前旧配置一字节不动。
    fd, tmp_name = tempfile.mkstemp(dir=config_path.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, config_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
