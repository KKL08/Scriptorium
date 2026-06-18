from __future__ import annotations

import html
import json
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from violet_refine.auth import PROVIDERS, KeyStore, provider_for
from violet_refine.config import RuntimeConfig, save_runtime_config
from violet_refine.llm import LLMClient

SETUP_SUCCESS_MESSAGE = "API Key 已保存，可以关闭这个页面，回到对话继续使用。"

# 页面下拉只露出这里列的服务商；后端（resolve_key/config）仍支持 PROVIDERS 全表，
# 其他服务商验证过真实调用后再加回来
SETUP_PAGE_PROVIDERS = ("deepseek",)

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
    return (
        template.replace("__SETUP_TOKEN__", html.escape(token, quote=True))
        .replace("__PROVIDER_OPTIONS__", options)
        .replace("__PROVIDER_URLS__", json.dumps(urls, ensure_ascii=False))
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

        def do_GET(self) -> None:
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
                    provider_for(field("provider"))
                    # DeepSeek 服务端 thinking 默认开启，16 token 的探测会被思考过程耗尽，显式关掉
                    probe_options = (
                        {"thinking": {"type": "disabled"}} if field("provider") == "deepseek" else {}
                    )
                    llm_client.complete(
                        [{"role": "user", "content": "回复一个字：好"}],
                        model=_resolve_request_model(field("provider"), field("model")),
                        max_tokens=16,
                        timeout=30,
                        api_key=field("api_key"),
                        api_base=field("api_base").strip() or None,
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
                store.set(provider.env, api_key)
                save_runtime_config(
                    RuntimeConfig(
                        provider=provider_name,
                        model=_resolve_request_model(provider_name, field("model")),
                        api_base=field("api_base").strip() or None,
                    ),
                    config_path,
                )
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
