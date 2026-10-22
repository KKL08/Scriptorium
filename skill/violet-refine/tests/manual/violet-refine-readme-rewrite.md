# VioletRefine

VioletRefine 是一个以 Skill 为先的中文文本润色工具包，主要面向 Claude Code、Codex 等 agent 工作流。本地 CLI 是 Skill 背后的执行内核，负责处理文本输入、通过 LiteLLM 调用模型、触发 review 或 direct 模型请求、生成 diff、管理凭据，并保存用户确认过的偏好记忆。简言之，Skill 承担任务理解与交互，CLI 完成具体的润色动作。

本仓库包含 `README.md` 与 `skill/violet-refine/README.md` 的介绍内容，供本地手工测试 `proofread`、`refine`、`rewrite` 三种模式。

## 安装

```bash
pip install -e ".[dev]"
```

## 配置 API 密钥

- **禁止**将 API key 粘贴到 Claude、Codex 或任何聊天窗口。
- 对于不熟悉终端的用户，运行 `violet-refine auth setup --ui`：该命令会尽量打开本地浏览器页面，并打印 localhost 地址作为兜底。
- 在纯终端环境中，运行 `violet-refine auth setup`：该命令使用隐藏输入。
- 自动化场景中，可通过环境变量 `DEEPSEEK_API_KEY` 传入密钥。

## 工作流

默认采用先 review 的用户流程：首先生成审阅报告，待用户确认后再执行 direct。仅当**用户明确要求直接修改**时，才应使用 `--workflow direct`。

示例：

```bash
violet-refine --mode refine --brief "去 AI 腔，保留 Markdown 结构、命令和路径。" --file README.md --workflow review
```

若使用 `--in-place`，VioletRefine 会先创建 `.bak` 备份文件，再替换原文件。

## 模式

- `proofread`：修复语法、错别字、标点、语句不顺和连贯性问题。
- `refine`：去 AI 腔、去翻译腔、压缩冗余、理顺表达。
- `rewrite`：允许较大幅度重写句子和结构，但仍须保留事实。

## 隐私

VioletRefine 不会将原文、润色结果、完整 diff 或 API key 写入记忆文件。偏好记忆仅保存用户明确确认过的写作偏好。

## Skill 使用注意事项

- **前文引用**：只将用户要求处理的文字片段传给 CLI，并将前文中的风格或用途信息压缩到 brief 中，绝不传递完整聊天记录。
- **子代理（subagent）**：当主机支持 subagent 时，Skill 应主动建议将较长文档、review、rewrite、多文件任务或前文润色任务交由 subagent 完成，以保持主上下文的整洁。