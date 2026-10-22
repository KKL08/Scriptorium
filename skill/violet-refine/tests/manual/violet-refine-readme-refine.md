# VioletRefine repo README 中文测试样本

> 来源语义：本仓库 `README.md` 与 `skill/violet-refine/README.md` 的介绍内容。  
> 用途：本地手工测试 VioletRefine 的 `proofread`、`refine`、`rewrite` 三种模式。

VioletRefine 是基于 Skill 的中文文本润色包，主要用于 Claude Code、Codex 这类 agent 工作流。其本地 CLI 是 Skill 的执行内核，负责读取文本输入、通过 LiteLLM 调用模型、触发 review 或 direct 模型请求、生成 diff、管理凭据设置并保存用户确认的偏好记忆。Skill 负责理解任务与交互，CLI 则实际完成润色动作。

安装时可运行 `pip install -e ".[dev]"`。配置 API key 时，不要将 key 粘贴到 Claude、Codex 或任何聊天窗口。不熟悉终端的用户，可运行 `violet-refine auth setup --ui`，它会尽量打开本地浏览器页面，并打印 localhost 地址作为备选。如果使用纯终端，运行 `violet-refine auth setup`，该命令会使用隐藏输入。自动化场景可通过 `DEEPSEEK_API_KEY` 环境变量传入。

默认用户流程为先 review，再根据用户确认决定是否 direct。仅在用户明确要求直接修改时，才使用 `--workflow direct`。例如：`violet-refine --mode refine --brief "去 AI 腔，保留 Markdown 结构、命令和路径。" --file README.md --workflow review`。使用 `--in-place` 时，VioletRefine 会先创建 `.bak` 备份再替换原文件。

目前支持三种模式：`proofread` 用于修复语法、错别字、标点、语句不顺和连贯性问题；`refine` 用于去 AI 腔、去翻译腔、压缩冗余、理顺表达；`rewrite` 允许更大幅度重写句子和结构，但必须保留事实。隐私方面，VioletRefine 不会将原文、润色结果、完整 diff 或 API key 写入记忆文件。偏好记忆仅保存用户明确确认的写作偏好。

当用户引用前文时，Skill 只应将用户要求处理的文字片段传给 CLI，并将前文中的风格或用途信息压缩到 brief 中，不要传递完整聊天记录。主机支持 subagent 时，Skill 应主动建议将较长文档、review、rewrite、多文件任务或前文润色任务交给 subagent 完成，避免扰乱主上下文。