from __future__ import annotations

import html
import json
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from violet_refine.auth import PROVIDERS, KeyStore, ensure_api_key_usable, provider_for
from violet_refine.config import RuntimeConfig, ensure_config_serializable, save_runtime_config
from violet_refine.llm import LLMClient

SETUP_SUCCESS_MESSAGE = "API Key 已保存，可以关闭这个页面，回到对话继续使用。"

# 页面下拉只露出这里列的服务商；后端（resolve_key/config）仍支持 PROVIDERS 全表，
# 其他服务商验证过真实调用后再加回来
SETUP_PAGE_PROVIDERS = ("deepseek", "google", "openai-compatible")

# 页面与素材来自设计交付包（design-handoff/，薇尔莉特的工作台 v3），随包分发
ASSETS_DIR = Path(__file__).resolve().parent / "setup_assets"
ASSET_TYPES = {
    "violet-photo.webp": "image/webp",
    "typewriter.png": "image/png",
    "quill.png": "image/png",
    "fonts/ma-shan-zheng.sub.woff2": "font/woff2",
    "fonts/courier-prime.sub.woff2": "font/woff2",
    "fonts/cormorant.sub.woff2": "font/woff2",
    "fonts/cormorant-italic.sub.woff2": "font/woff2",
}


def build_setup_page(token: str) -> str:
    template = (ASSETS_DIR / "page.html").read_text(encoding="utf-8")
    options = "".join(
        f'<option value="{name}">{PROVIDERS[name].label}</option>'
        for name in SETUP_PAGE_PROVIDERS
    )
    urls = {name: PROVIDERS[name].key_url for name in SETUP_PAGE_PROVIDERS}
    models_data = {
        name: [{"id": m.id, "label": m.label} for m in PROVIDERS[name].models]
        for name in SETUP_PAGE_PROVIDERS
        if PROVIDERS[name].models
    }
    default_models = {name: PROVIDERS[name].default_model for name in SETUP_PAGE_PROVIDERS}
    return (
        template.replace("__SETUP_TOKEN__", html.escape(token, quote=True))
        .replace("__PROVIDER_OPTIONS__", options)
        .replace("__PROVIDER_URLS__", json.dumps(urls, ensure_ascii=False))
        .replace("__PROVIDER_MODELS__", json.dumps(models_data, ensure_ascii=False))
        .replace("__DEFAULT_MODELS__", json.dumps(default_models, ensure_ascii=False))
    )


def _resolve_request_model(provider_name: str, submitted_model: str) -> str:
    if submitted_model.strip():
        return submitted_model.strip()
    return provider_for(provider_name).default_model


def create_setup_server(
    *,
    store: KeyStore,
    llm_client: LLMClient,
    config_path: Path | None = None,
    token: str | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
) -> tuple[ThreadingHTTPServer, str, str]:
    expected_token = token or secrets.token_urlsafe(32)

    class SetupHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _host_allowed(self) -> bool:
            # 只接受本机 Host，拒绝 DNS rebinding 一类把外部域名解析到 127.0.0.1 的请求
            request_host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return request_host in ("127.0.0.1", "localhost", "[::1]")

        def do_GET(self) -> None:
            if not self._host_allowed():
                self._send(HTTPStatus.FORBIDDEN, "Forbidden")
                return
            if self.path == "/":
                self._send(HTTPStatus.OK, build_setup_page(expected_token), "text/html")
                return
            if self.path.startswith("/assets/"):
                name = self.path.removeprefix("/assets/")
                if name in ASSET_TYPES and (ASSETS_DIR / name).is_file():
                    self._send_bytes(HTTPStatus.OK, (ASSETS_DIR / name).read_bytes(), ASSET_TYPES[name])
                    return
            self._send(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:
            if not self._host_allowed():
                self._send(HTTPStatus.FORBIDDEN, "Forbidden")
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64 * 1024:
                self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large")
                return
            fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)

            def field(name: str) -> str:
                return fields.get(name, [""])[0]

            if self.path == "/test":
                # /test 不校验 setup token：它不读取已存密钥、不落盘，只用请求里的 key 发一次探测请求
                try:
                    provider_name = field("provider")
                    provider_for(provider_name)
                    # 探测只配 16 token：DeepSeek 服务端 thinking 默认开启、Gemini 默认有思考过程，
                    # 都会把这个预算耗光，显式压低
                    if provider_name == "deepseek":
                        probe_options = {"thinking": {"type": "disabled"}}
                    elif provider_name == "google":
                        # "none" 会映射成 thinkingLevel=minimal，gemini-3.x-flash 的真实 API
                        # 不接受该档位（400），用支持的最低档 low
                        probe_options = {"reasoning_effort": "low"}
                    else:
                        probe_options = {}
                    # api_base 只属于 openai-compatible，与 /save 同一道后端防线
                    probe_base = (field("api_base").strip() or None) if provider_name == "openai-compatible" else None
                    llm_client.complete(
                        [{"role": "user", "content": "回复一个字：好"}],
                        provider=provider_name,
                        model=_resolve_request_model(provider_name, field("model")),
                        max_tokens=16,
                        timeout=30,
                        api_key=field("api_key"),
                        api_base=probe_base,
                        **probe_options,
                    )
                    # 鉴权探测：请求没抛异常即 key 可用；content 可能因 token 预算耗尽为空，不作为判据
                    payload = {"ok": True}
                except Exception as error:  # noqa: BLE001 - 任何失败都报给页面
                    payload = {"ok": False, "error": str(error)[:200]}
                self._send(HTTPStatus.OK, json.dumps(payload, ensure_ascii=False), "application/json")
                return

            if self.path == "/save":
                if not secrets.compare_digest(expected_token, field("setup_token")):
                    self._send(HTTPStatus.FORBIDDEN, "Setup token was rejected")
                    return
                api_key = field("api_key").strip()
                if not api_key:
                    self._send(HTTPStatus.FORBIDDEN, "API key must not be empty")
                    return
                provider_name = field("provider")
                provider = provider_for(provider_name)
                model = _resolve_request_model(provider_name, field("model"))
                # api_base 只属于 openai-compatible：内置 provider 一律丢弃，
                # 防止切换服务商后残留地址把 key 发往自定义端点
                api_base = None
                if provider_name == "openai-compatible":
                    api_base = field("api_base").strip() or None
                    if not api_base:
                        self._send(HTTPStatus.FORBIDDEN, "自定义 OpenAI 接口需填写 Base URL")
                        return
                    if not field("model").strip():
                        self._send(HTTPStatus.FORBIDDEN, "自定义 OpenAI 接口需填写模型名")
                        return
                # key 含 header 非法字符（换行/控制字符）当场拒绝：既防落盘一个不可用的 key，
                # 也不给它进入请求 header 泄漏的机会
                try:
                    ensure_api_key_usable(api_key)
                except ValueError as error:
                    self._send(HTTPStatus.FORBIDDEN, str(error))
                    return
                # 凭据按端点存：openai-compatible 用「provider::base」区分槽位，换端点不覆盖旧 key；
                # 内置 provider 单端点，仍用 provider.env（向后兼容）
                credential_id = (
                    f"{provider_name}::{api_base}"
                    if provider_name == "openai-compatible"
                    else provider.env
                )
                config = RuntimeConfig(
                    provider=provider_name, model=model, api_base=api_base, credential_id=credential_id
                )
                # 顺序保证一致性：① 先校验 config 可无损写入（坏字符在此拦下，key 尚未落盘）
                try:
                    ensure_config_serializable(config)
                except ValueError as error:
                    self._send(HTTPStatus.FORBIDDEN, str(error))
                    return
                # ② 再存 key（按端点槽）——若钥匙串失败，config 尚未改写，旧 (config,key) 配对不变
                try:
                    store.set(credential_id, api_key)
                except Exception as error:  # noqa: BLE001 - 钥匙串各平台异常族杂
                    self._send(HTTPStatus.INTERNAL_SERVER_ERROR, f"凭据写入失败：{error}")
                    return
                # ③ 最后写 config（已校验，仅剩磁盘 IO）；失败给干净 500，旧 config 保持不变
                try:
                    save_runtime_config(config, config_path)
                except OSError as error:
                    self._send(HTTPStatus.INTERNAL_SERVER_ERROR, f"配置写入失败：{error}")
                    return
                self._send(HTTPStatus.OK, SETUP_SUCCESS_MESSAGE)
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            self._send(HTTPStatus.NOT_FOUND, "Not found")

        def _send(self, status: HTTPStatus, body: str, content_type: str = "text/plain") -> None:
            self._send_bytes(status, body.encode("utf-8"), f"{content_type}; charset=utf-8")

        def _send_bytes(self, status: HTTPStatus, data: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer((host, port), SetupHandler)
    actual_host, actual_port = server.server_address[:2]
    return server, f"http://{actual_host}:{actual_port}/", expected_token
