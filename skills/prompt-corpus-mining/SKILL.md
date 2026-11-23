---
name: prompt-corpus-mining
description: 把公开/泄露的 system prompt 语料库当"样板矿"用：稀疏检出只拉需要的目录，按 official → tools → agents 三档优先级读，只抽结构与可机读字段（whenToUse / disallowedTools / model / 只读约束段 / 工具描述要素），不抄口吻、不抄历史包袱。当要新写或改一个 agent 角色稿、skill、persona、工具描述，或想弄清"大厂是怎么写系统提示词和子智能体边界"时使用。
whenToUse: 要给 DSH / Codex / WorkBuddy 写新的子智能体角色稿或 persona；要判断自己的 skill description 写法是否规范；要查某家产品（Claude Code / Codex / Cursor / Kimi / GLM）的工具调用与拒答边界怎么写；手上只有"感觉不对"的提示词但不知道规范长什么样。
---

# 把 prompt 语料库当样板矿

> 本文的用法已在 2026-11-22 对本机实测（`asgeirtj/system_prompts_leaks`）。

## 一、先分清：这是语料，不是插件

| 你可能以为 | 实际 |
|---|---|
| 能装的能力 | ❌ 装不了，它是 Markdown 语料仓（CC0） |
| 最佳实践手册 | ❌ 里面混着历史包袱、A/B 文案、产品策略 |
| 写提示词时的对照样板 | ✅ **这个才是它的价值** |

所以只用一种方式消费它：**定向检索 + 抽结构**。

## 二、主力语料仓（已验证）

`https://github.com/asgeirtj/system_prompts_leaks`

| 项 | 实测值（2026-11-22） |
|---|---|
| 体量 | 72,430★ / 11,656 fork / 26MB / CC0-1.0 |
| 更新 | 每日更新（最后推送 2026-11-20） |
| 覆盖 | Anthropic、OpenAI、Google、xAI、Meta、Microsoft、Qwen、Kimi、GLM、MiniMax、Mistral、DeepSeek、Cursor、Perplexity、Notion、Pi |

其它备选见 `references/sources.md`。

## 三、三档阅读优先级（别通读）

| 档 | 路径 | 体积 | 用途 |
|---|---|---|---|
| **A 档（先读）** | `Anthropic/official/` | 每档 1–13KB | 官方 system prompt 版本史（2024-03 起）。**短、干净**，能看出输出格式/拒答边界的迭代脉络 |
| **A 档** | `Anthropic/tools/` | 1–38KB | `bash-tool.md`、`web-search-tool.md`、`web-fetch-tool.md`、`browser-use-tool.md`、`computer-use-tool.md`、`code-execution-tool.md`。**"工具描述怎么写才不让模型跑偏"的样板** |
| **A 档** | `Anthropic/claude-code/agents/` | 1–41KB | 9 个真实子智能体定义：`Explore`、`Plan`、`general-purpose`、`fork`、`shared-notes`、`web-fetch`、`statusline-setup`、`claude-code-guide`、`claude.md` |
| **B 档（按需）** | `OpenAI/Codex/`、`Google/`、`Kimi/`、`GLM/` | 不等 | 换模型复评或做竞品口径对照时看 |
| **C 档（跳过）** | `claude-code-desktop-*.md`（675KB）、`claude-opus-4.7.md`（471KB）等 | 300–700KB | 整段抓取拼接，噪音极高，读它=烧 token |

## 四、拉取：稀疏检出，只拿 A 档

```powershell
$git = 'C:\Users\46485\tools\mingit\cmd\git.exe'   # 或 E:\workbuddy\resources\vendor\PortableGit\cmd\git.exe
$dir = "$env:TEMP\prompt-corpus"
if (-not (Test-Path $dir)) { & $git clone --depth 1 --filter=blob:none --sparse https://github.com/asgeirtj/system_prompts_leaks $dir }
& $git -C $dir sparse-checkout set Anthropic/official Anthropic/tools Anthropic/claude-code/agents OpenAI/Codex
```

> `--depth 1 --filter=blob:none --sparse` 只下载选定目录的文件内容，26MB → 通常几 MB。

## 五、抽取：只拿这几个东西

### 5.1 角色稿的可机读字段（最有价值）

`Anthropic/claude-code/agents/Plan.md` 实测开头：

```yaml
---
name: Plan
whenToUse: Software architect agent for designing implementation plans. Use this when you need to plan the implementation strategy for a task. Returns step-by-step plans, identifies critical files, and considers architectural trade-offs.
disallowedTools: Agent, Artifact, Edit, Write, NotebookEdit
model: inherit
omitClaudeMd: true
---
You are a software architect and planning specialist for Claude Code.
=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY planning task. You are STRICTLY PROHIBITED from:
- Creating new files (no Write, touch, or file creation of any kind)
...
```

要抄的是这 4 个结构决策，不是英文句子：

| 字段 | 抄什么 | 落到本机哪里 |
|---|---|---|
| `whenToUse` | **"什么时候调用我"写进 frontmatter**，而不是藏在正文里 | Skill 的 `description` 第二句；DSH 角色稿的任务书开头 |
| `disallowedTools` | **用白名单外的显式黑名单**兜住越权（Plan 禁写盘） | 只读型角色（评估、审计、资产梳理）必须写死"不得写盘/不得扫描" |
| `model: inherit` | 子智能体默认继承父模型，不硬编码 | 与 DSH `redteamRole` 派活方式一致 |
| 顶部一行角色 + 第二条 CRITICAL 约束段 | **"你是谁"一句 + "你绝对不许干什么"一段**，两段紧邻 | 角色稿开头的固定套路 |

### 5.2 工具描述的四要素（从 `Anthropic/tools/*.md` 归纳）

1. 一句话定义边界（能干什么，不能干什么）；
2. 参数语义 + 什么时候**不要**用；
3. 失败/超时的返回形态；
4. 与相邻工具的区分（"要 X 用 A，不要用 B"）。

本机对照点：`connectors-marketplace` 里的 MCP 工具描述、DSH skill 的 `whenToUse`，都可以按这四条补齐。

### 5.3 定向检索命令

```powershell
# 有 rg 时（GitHub 镜像/DSH grep 工具同理）
rg -n "whenToUse|disallowedTools|model: inherit" "$dir\Anthropic\claude-code\agents"
rg -n "READ-ONLY|STRICTLY PROHIBITED|Do NOT use" "$dir\Anthropic"

# 只有 PowerShell 时
$dir = "$env:TEMP\prompt-corpus"
Select-String -Path "$dir\Anthropic\claude-code\agents\*.md" -Pattern 'whenToUse|disallowedTools' | Select-Object -First 20
```

## 六、反模式（踩过的）

| 反模式 | 后果 |
|---|---|
| 把 400KB+ 的整段抓取文件读进来"找灵感" | 烧掉大半上下文，拿到的全是重复的工具清单 |
| 直接把英文段落抄进 persona | 带进你不需要的行为约束（过度免责、过度确认、过度礼貌），把本地 `AGENTS.md` 的五段式冲掉 |
| 当成"官方最佳实践"引用 | 很多是历史版本与 A/B 文案，真实性、时效都无法保证 |
| 拿它当规范来"纠错"本机写法 | 本机已有约定（`50-Codex协作/技能存储约定.md`、`AGENTS.md`）优先，语料只提供**结构灵感** |

## 七、一次典型用法（10 分钟）

1. 稀疏检出 A 档（第四节命令）。
2. 读 `Anthropic/claude-code/agents/Plan.md` + `general-purpose.md`，抽出 4 个结构字段。
3. 读 `Anthropic/tools/web-fetch-tool.md`，对照自己要写的工具描述补四要素。
4. 按本机规范写/改 `Skills/<name>/SKILL.md`（frontmatter 必须有 `name` + `description`）。
5. 反向检查：新写的 `description` 第一句能不能独立说清"干什么"（`/` 菜单只显示第一句，≤40 字）。

---

来源与免责：语料为第三方公开收集（CC0-1.0），真伪与时效自行判断；引用时不要声称"官方文档"。
