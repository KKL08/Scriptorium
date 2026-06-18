# Violet-Refine

中文写作润色工具，跑在 Claude Code / Codex 等 AI Agent 工作流里。

用户说"润色一下"、"去 AI 味"、"改顺一点"，Skill 接管交互（读文 → 校准意图 → 选模式），CLI 调外部模型执行润色，输出审阅报告或改稿。

## 三个模式

- **proofread** — 只修错别字、标点、语法
- **refine** — 去 AI 腔、去翻译腔、压缩冗余（默认）
- **rewrite** — 允许重组段落和论述顺序

## 安装

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
# Claude Code
mkdir -p ~/.claude/skills
cp -r violet-refine ~/.claude/skills/

# Codex
mkdir -p ~/.codex/skills
cp -r violet-refine ~/.codex/skills/
```

首次使用前配置 API Key：

```bash
violet-refine/scripts/violet-refine auth --ui
```

## 使用

安装后在 Agent 里直接说"帮我润色一下这段"就会触发。也可以手动运行 CLI：

```bash
violet-refine/scripts/violet-refine run --workflow review --mode refine \
  --file input.md
```
