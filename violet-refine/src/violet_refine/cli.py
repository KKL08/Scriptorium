from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from violet_refine.auth import KeyringStore, MissingKeyError, provider_for, resolve_key
from violet_refine.config import DEFAULT_CONFIG_PATH, load_runtime_config
from violet_refine.diffing import unified_diff
from violet_refine.llm import LiteLLMClient
from violet_refine.prompts import VALID_MODES, build_messages
from violet_refine.review import ReviewReport
from violet_refine.setup_page import create_setup_server

SCHEMA_FAILURE_EXIT = 4

# DeepSeek v4 官方输出上限 384K（api-docs.deepseek.com 模型规格页）
DEEPSEEK_MAX_OUTPUT_TOKENS = 384_000


def _read_input(file: Path | None) -> str:
    if file is not None:
        return file.read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise ValueError("No input. Pass --file or pipe text via stdin.")
    return sys.stdin.read()


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        text = _read_input(args.file)
        config = load_runtime_config(DEFAULT_CONFIG_PATH)
        key = resolve_key(config.provider, store=KeyringStore())
    except (ValueError, OSError, MissingKeyError) as error:
        print(str(error), file=sys.stderr)
        return 1

    client = LiteLLMClient()
    model = args.model or config.model
    review_context = ""
    if args.review_context is not None:
        review_context = args.review_context.read_text(encoding="utf-8")

    messages = build_messages(
        workflow=args.workflow,
        mode=args.mode,
        text=text,
        brief=args.brief,
        rule_context=args.rule_context,
        review_context=review_context,
    )

    # thinking/reasoning_effort 是 DeepSeek 专有参数（合法取值 high/max），其他 provider 不传
    request_options: dict[str, object] = {}
    if config.provider == "deepseek":
        request_options = {
            "max_tokens": DEEPSEEK_MAX_OUTPUT_TOKENS,
            "thinking": {"type": "enabled"},
            "reasoning_effort": "max" if args.mode == "rewrite" else "high",
        }

    def complete() -> str:
        return client.complete(
            messages,
            model=model,
            api_key=key.value,
            api_base=config.api_base,
            **request_options,
        )

    try:
        raw = complete()
    except Exception as error:  # noqa: BLE001 - litellm 异常族杂，统一报请求失败
        print(f"模型请求失败：{error}。可以稍后重试，或改用 host 模型路径。", file=sys.stderr)
        return 1

    if args.workflow == "direct":
        if args.format == "diff":
            print(unified_diff(text, raw), end="")
        else:
            print(raw)
        return 0

    for attempt in (1, 2):
        try:
            report = ReviewReport.parse(raw, mode=args.mode, brief=args.brief)
            print(report.render())
            return 0
        except ValueError:
            if attempt == 1:
                try:
                    raw = complete()
                except Exception as error:  # noqa: BLE001
                    print(f"模型请求失败：{error}。可以稍后重试，或改用 host 模型路径。", file=sys.stderr)
                    return 1
    print("模型两次返回都不符合报告结构，以下是原始输出，交由调用方处置：", file=sys.stderr)
    print(raw)
    return SCHEMA_FAILURE_EXIT


def _cmd_auth(args: argparse.Namespace) -> int:
    config = load_runtime_config(DEFAULT_CONFIG_PATH)

    if args.ui:
        server, url, _ = create_setup_server(store=KeyringStore(), llm_client=LiteLLMClient())
        print(f"本机配置页面已打开：{url}")
        print("如果浏览器没有自动弹出，手动打开上面这个地址。配置完成后这里会自动结束。")
        webbrowser.open(url)
        try:
            server.serve_forever()
        finally:
            server.server_close()
        print("配置已保存。")
        return 0

    provider_for(config.provider)
    print(f"服务商：{config.provider}")
    print(f"模型：{config.model}")
    try:
        key = resolve_key(config.provider, store=KeyringStore())
        print(f"API Key：已配置（来源：{'环境变量' if key.source == 'env' else '本机钥匙串'}）")
        return 0
    except MissingKeyError:
        print("API Key：本地 API Key 还没配置好。运行 violet-refine auth --ui 打开本机配置页面。")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="violet-refine", description="中文润色执行内核")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="发起一次润色请求")
    run_parser.add_argument("--workflow", required=True, choices=["review", "direct"])
    run_parser.add_argument("--mode", required=True, choices=list(VALID_MODES))
    run_parser.add_argument("--brief", default="")
    run_parser.add_argument("--rule-context", dest="rule_context", default="")
    run_parser.add_argument("--file", type=Path)
    run_parser.add_argument("--format", choices=["text", "diff"], default="text")
    run_parser.add_argument("--review-context", dest="review_context", type=Path,
                            help="审阅报告文件路径，传入后 direct 按报告建议改写")
    run_parser.add_argument("--model", help="覆盖配置中的模型名")
    run_parser.set_defaults(func=_cmd_run)

    auth_parser = subparsers.add_parser("auth", help="检查或配置本地凭证")
    auth_parser.add_argument("--ui", action="store_true", help="打开本机配置页面")
    auth_parser.set_defaults(func=_cmd_auth)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
