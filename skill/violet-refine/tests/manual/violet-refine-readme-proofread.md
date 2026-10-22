# VioletRefine repo README 中文测试样本

> 来源语义：本仓库 `README.md` 与 `skill/violet-refine/README.md` 的介绍内容。
> 用途：本地手工测试 VioletRefine 的 `proofread`、`refine`、`rewrite` 三种模式。

VioletRefine 是一个 Skill-first 的中文文本润色包，主要给 Claude Code、Codex 这一类 agent 工作流使用。它的本地 CLI 是 Skill 背后的执行内核，负责读取文本输入、通过 LiteLLM 调用模型、触发 review 或 direct 模型请求、生成 diff、处理凭据设置，以及保存用户确认过的偏好记忆。也就是说，Skill 负责任务理解和交互，CLI 负责把这个润色动作真的做完。

安装的时候可以运行 `pip install -e ".[dev]"`。配置 API key 的时候，不应该把 key 粘贴到 Claude、Codex 或任何聊天窗口里。对于不熟悉终端的用户，可以运行 `violet-refine auth setup --ui`，它会尽量打开本地浏览器页面，同时也会打印 localhost 地址作为兜底。如果是在纯终端里面，可以运行 `violet-refine auth setup`，这个命令会使用隐藏输入。自动化场景可以通过 `DEEPSEEK_API_KEY` 环境变量传入。

使用上，默认用户流程是先 review，再根据用户确认决定是否 direct。只有在用户明确说要直接修改的时候，才应该使用 `--workflow direct`。例如可以运行 `violet-refine --mode refine --brief "去 AI 腔，保留 Markdown 结构、命令和路径。" --file README.md --workflow review`。当使用 `--in-place` 的时候，VioletRefine 会先写一个 `.bak` 备份再替换原文件。

目前它支持三个模式：`proofread` 用来修复语法、错别字、标点、语句不顺和连贯性问题；`refine` 用来去 AI 腔、去翻译腔、压缩冗余、理顺表达；`rewrite` 则允许更大幅度重写句子和结构，但是仍然必须保留事实。隐私方面，VioletRefine 不会把原文、润色结果、完整 diff 或 API key 写入记忆文件。偏好记忆只保存用户明确确认过的写作偏好。

当用户引用前文时，Skill 只应该把用户要求处理的文字片段传给 CLI，并把前文中的风格或用途信息压缩到 brief 里，不要把完整聊天记录传过去。主机支持 subagent 的时候，Skill 应该主动建议把较长文档、review、rewrite、多文件任务或者前文润色任务交给 subagent 完成，避免主上下文被打乱。