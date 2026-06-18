from __future__ import annotations

from pathlib import Path

VALID_MODES = ("proofread", "refine", "rewrite")

# load_global_rules / load_strong_rules 靠这些标题在规则包里定位对应段，改规则包时标题本身不能动
GLOBAL_RULES_HEADING = "## 写作全局规则"
STRONG_RULES_HEADING = "## 第一层：强规则"


def references_dir() -> Path:
    # 依次匹配：开发仓布局、发布扁平布局（合集仓 skill 文件夹）、pip 安装的包内副本
    project_root = Path(__file__).resolve().parents[2]
    for candidate in (
        project_root / "skill/violet-refine/references",
        project_root / "references",
    ):
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent / "_references"


def prompts_dir() -> Path:
    return references_dir() / "prompts"


def validate_mode(mode: str) -> str:
    if mode in VALID_MODES:
        return mode
    raise ValueError(f"Unknown mode: {mode}. Valid modes: {', '.join(VALID_MODES)}.")


def load_mode_rules(mode: str) -> str:
    raw = (prompts_dir() / "modes.md").read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in raw.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return "\n".join(sections[validate_mode(mode)]).strip()


def _extract_section(raw: str, heading: str) -> str:
    lines = raw.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        raise ValueError(
            f"规则包里找不到标题「{heading}」。修改规则包时请保留这个标题。"
        ) from None
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip()


def load_global_rules() -> str:
    raw = (references_dir() / "anti-ai-rules.zh.md").read_text(encoding="utf-8")
    return _extract_section(raw, GLOBAL_RULES_HEADING)


def load_strong_rules() -> str:
    raw = (references_dir() / "anti-ai-rules.zh.md").read_text(encoding="utf-8")
    return _extract_section(raw, STRONG_RULES_HEADING)


_REVIEW_GUIDED = (
    "以下是此前对这篇文本的审阅报告。请严格按照报告中的建议进行改写，"
    "不要超出报告建议的改动范围：\n\n{report}"
)
_SELF_REVIEW = (
    "改写前先在内部审阅文本，找出需要改动的地方，再据此改写。"
    "审阅过程是你的内部思考，不要输出审阅内容，只输出最终改写结果。"
)


def build_messages(
    *,
    workflow: str,
    mode: str,
    text: str,
    brief: str = "",
    rule_context: str = "",
    review_context: str = "",
) -> list[dict[str, str]]:
    mode = validate_mode(mode)
    template_name = {"review": "review.md", "direct": "direct.md"}[workflow]
    template = (prompts_dir() / template_name).read_text(encoding="utf-8")
    global_rules = load_global_rules()
    strong_rules = load_strong_rules() if mode in ("refine", "rewrite") else "无"

    if workflow == "direct" and review_context.strip():
        review_block = _REVIEW_GUIDED.format(report=review_context.strip())
    elif workflow == "direct":
        review_block = _SELF_REVIEW
    else:
        review_block = ""

    system_prompt = (
        template.replace("[[MODE]]", mode)
        .replace("[[MODE_RULES]]", load_mode_rules(mode))
        .replace("[[GLOBAL_RULES]]", global_rules)
        .replace("[[STRONG_RULES]]", strong_rules)
        .replace("[[BRIEF]]", brief.strip() or "无")
        .replace("[[RULE_CONTEXT]]", rule_context.strip() or "无")
        .replace("[[REVIEW_CONTEXT]]", review_block)
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"待处理文本：\n{text}"},
    ]
