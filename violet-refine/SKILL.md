---
name: violet-refine
description: Use Violet-Refine to polish, proofread, refine, de-AI, de-translationese, rewrite, or make Chinese writing natural across reports, docs, messages, speeches, README files, PRDs, meeting notes, and agent final responses. Trigger this skill whenever the user wants Chinese text to read more natural, clearer, or less AI-flavored — including requests like 润色一下表述、改顺一点、去 AI 味、去翻译腔、太像 AI 写的、这段读起来不符合中文习惯、这段话写的自然一点、帮我看看这篇文档/报告的中文 — even if the user never names the skill or only vaguely asks to improve some Chinese text.
---

# Violet-Refine

本 skill 负责全部交互；`violet-refine` CLI 是执行内核，只发模型请求。文中相对路径（`references/`、`scripts/`）一律以本 SKILL.md 所在目录为基准。

## 三步流程

### 1. 理解与确认（先读后问，一轮问完）

识别目标文本（粘贴、文件、URL 或前文片段）后，**先通读全文**，形成自己对以下维度的判断：

- **读者**：这篇文档面向谁？具体到什么程度——"开发者"太泛，"第一次看到这个工具、想判断值不值得试"才够
- **目的**：读者读完应该能做什么 / 知道什么 / 决定什么
- **语域**：当前文本的语气是什么（口语 / 中性 / 书面），是否一致；如果不一致，哪段是例外
- **问题观察**：读到哪些地方觉得不对——句子不连贯、语气跳、信息重复、铺垫太长等具体问题

然后把读后判断摆出来，**一轮**问完以下内容：

1. **意图校准**（让用户确认或纠正你的判断）：
   - 你判断的读者和目的对不对
   - 你观察到的问题是不是用户关心的；用户还有没有别的关切
   - 推荐的语域对不对
2. **mode 确认**（必须由用户确认，推荐不算确认）：
   - `proofread`：只修错别字、标点、语法、语病
   - `refine`：去 AI 腔、去翻译腔、压缩冗余、提升自然度（默认推荐）
   - `rewrite`：允许重组段落和论述顺序
3. **流程确认**：是否先出审阅报告再改（默认建议先审阅；用户要求直出就直出）
4. **结构保留假设**：代码块、链接、表格、数字、路径默认冻结

首次使用时在同一轮里确认调用路径：建议外部 API，并提示用户选和当前 agent 不同家的模型效果更好（同族模型对自己的 AI 腔有盲区，换个模型挑得更准）；也可以用当前 agent 的模型直接润色。只给提示，不用探测当前 agent 具体是什么模型。用户的选择沿用到后续任务，用户可随时改。

mode、流程、调用路径等确认信息已经在本次会话历史里的，直接沿用，不要重复问。意图维度（读者、目的、语域）每篇文档不同，需要每次确认。

**怎么问：**

- 用 host 的问题组件让选项可框选：Claude Code 用 AskUserQuestion，Codex 用对应的 request user question 机制；host 没有问题组件时才退回纯文本提问。
- 先说你读完后的判断和观察，再基于判断自然地引出需要确认的选项。不把维度名、参数名当问题主体念出来。好的例子：

  > 读完了。这篇是 Skill 合集仓的主 README，面向第一次看到这个仓库的开发者，目的是让人快速知道有什么、怎么装。
  >
  > 我注意到几个问题：开头几段的句子各说各的，读起来像列表而不是连贯的介绍；语气在"不用每次重新搭"（口语）和"有额外依赖的会单独注明"（书面）之间跳；六个 skill 简介用了一模一样的收尾句式。整体语域建议统一到中性偏口语。
  >
  > 这些是你想改的吗？还有别的觉得不对的地方？
  >
  > 力度上我建议 rewrite（连段落结构一起调），也可以只调措辞不动结构（refine），或者只修错别字（proofread）。先出审阅报告看看全貌，还是直接改？

  坏的例子：「请确认读者、目的、语域。请选择 mode：proofread / refine / rewrite。」

### 2. 执行

把用户校准后的意图整理成两个参数：

- `--brief`：结构化的上下文块，包含经用户确认的读者、目的、语域、作者关切和结构保留假设。用换行分行，每行一个维度，不需要写成一句话：
  ```
  读者：第一次看到这个仓库的开发者或 AI 从业者
  目的：快速了解有哪些 skill、选一个安装
  语域：中性偏口语
  关切：开头几段不连贯，语气跳，简介句式重复
  结构保留：代码块、链接、版本号冻结
  ```
- `--rule-context`：refine/rewrite 时从 `references/anti-ai-rules.zh.md` 第二层按语境选 2-3 条软约束规则行；proofread 不传。写作全局规则（G01-G07）和强规则（S01-S10）由 CLI 自动整段带入，不用复制

**外部 API 路径**（推荐）：

```bash
skill/violet-refine/scripts/violet-refine run --workflow review --mode refine \
  --brief "读者：第一次看到仓库的开发者\n目的：快速了解有哪些 skill、选一个安装\n语域：中性偏口语\n关切：开头不连贯，语气跳\n结构保留：代码块、链接冻结" \
  --rule-context "- 减少模板化开场\n- 保留全部技术标识" \
  --file path/to/input.md
```

review 后用面向用户的表述总结报告：讲清查了什么、发现哪几类问题（文档架构、写作质量、AI 腔等）、建议改哪些，不照搬 JSON 字段名；然后问用户是否继续生成改稿。review 总会返回各维度的发现和建议，按风险高低排列呈现给用户。

生成改稿时，把 review 的原始输出存到临时文件，通过 `--review-context` 传给 direct 调用，让改写严格按审阅建议执行：

```bash
skill/violet-refine/scripts/violet-refine run --workflow direct --mode refine \
  --format text --review-context /tmp/review-output.txt \
  --brief "..." --rule-context "..." --file path/to/input.md
```

只跑**一次** direct，结果写到新文件，再用本地 diff（如 `diff -u 原文 新文件`）展示对照——不要为了出 diff 再跑一次模型。

用户直接选 direct（跳过 review）时不传 `--review-context`，CLI 会自动让模型先内部审阅再改写，审阅过程不会出现在输出里。

**host 模型路径**：读 `references/prompts/` 下对应模板（`review.md` 或 `direct.md`），用 `references/prompts/modes.md` 中对应 mode 的段落替换 `[[MODE_RULES]]`，用规则包「写作全局规则」整段替换 `[[GLOBAL_RULES]]`，用「第一层：强规则」整段替换 `[[STRONG_RULES]]`（proofread 填「无」），再填入 `[[MODE]]`、`[[BRIEF]]`、`[[RULE_CONTEXT]]`。direct 模板的 `[[REVIEW_CONTEXT]]`：有 review 结果时填入审阅报告 + "按报告建议改写"；无 review 时填入"先内部审阅再改写，只输出改写结果"。按模板要求自己执行或交给 subagent。长文、多文件用 subagent，只传目标文本、mode、brief、规则行，不传聊天历史。

### 3. 交付

展示 diff 或原文/改稿对照，说明改了什么、保留了什么、结果文件在哪。输出默认写到新文件，不覆盖原文件；用户明确要求时才原地覆盖。

## API Key 安全

绝不让用户把 API Key 粘贴到聊天里。缺凭证时用面向用户的表述：「本地 API Key 还没配置好，要我打开本机配置页面吗？」用户同意后运行：

```bash
skill/violet-refine/scripts/violet-refine auth --ui
```

页面会引导选服务商、粘贴 Key、测试连接。检查状态用 `auth`（不带 --ui）。如果用户已经把 key 发进聊天，提醒去服务商后台作废重建，不要使用它。

## CLI 速查

```bash
violet-refine run --workflow review|direct --mode proofread|refine|rewrite \
    --brief "..." [--rule-context "..."] [--file path] [--format text|diff] \
    [--review-context path/to/review.txt]
violet-refine auth [--ui]
```

`--mode` 和 `--workflow` 必填。CLI 不问问题、不推荐 mode、不自动从 review 接到 direct——追问、推荐 mode、决定是否继续改，这些由 skill 来做。
