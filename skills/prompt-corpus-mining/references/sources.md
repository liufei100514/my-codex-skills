# prompt 语料源清单

> 只收"能定向检索、结构清晰"的源；纯营销页、纯截图转述的不收。

## 一、主力（已在 skill 正文使用）

| 源 | 体量（2026-11-22） | 目录要点 | 用法 |
|---|---|---|---|
| https://github.com/asgeirtj/system_prompts_leaks | 72,430★ / CC0-1.0 / 每日更新 | `Anthropic/official/`（版本史）、`Anthropic/tools/`（工具描述）、`Anthropic/claude-code/agents/`（子智能体）、`OpenAI/Codex/`、`Google/`、`Kimi/`、`GLM/`、`DeepSeek/`、`Cursor/`、`Perplexity/` | 稀疏检出后定向 rg（见 SKILL.md 第四节） |

## 二、备选（能力/技能形态参考，不是 prompt 语料）

| 源 | 用途 |
|---|---|
| https://github.com/anthropics/skills | 官方 Skill 写法与目录约定，写新 skill 时对标 frontmatter 与正文结构 |
| https://agentskills.io | Agent Skills 规范（`~/.agents/skills` 那套 CLI 用的就是它） |
| https://github.com/majiayu000/claude-skill-registry | 748★，每日自动发现的 skill 全量目录，可搜"别人怎么写同类 skill" |

## 三、判断一个源值不值得挖

1. 目录按厂商/产品分层（能局部稀疏检出）；
2. 单个文件 ≤ 50KB（能整篇读）；
3. 有 frontmatter 或明确的标题结构（能机读字段）；
4. 有版本/日期（能判断时效）。

不满足 2 的，基本是抓取拼接，跳过。
