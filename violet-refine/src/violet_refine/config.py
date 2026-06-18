from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".violet-refine/config.toml"


@dataclass(frozen=True)
class RuntimeConfig:
    provider: str = "deepseek"
    model: str = "deepseek/deepseek-v4-pro"
    api_base: str | None = None


def load_runtime_config(path: str | Path | None = None) -> RuntimeConfig:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return RuntimeConfig()
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if "api_key" in data:
        raise ValueError("Config file must not contain api_key. Run: violet-refine auth --ui")
    api_base = data.get("api_base")
    return RuntimeConfig(
        provider=str(data.get("provider", RuntimeConfig.provider)),
        model=str(data.get("model", RuntimeConfig.model)),
        api_base=None if api_base is None else str(api_base),
    )


def save_runtime_config(config: RuntimeConfig, path: str | Path | None = None) -> None:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'provider = "{config.provider}"', f'model = "{config.model}"']
    if config.api_base:
        lines.append(f'api_base = "{config.api_base}"')
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
