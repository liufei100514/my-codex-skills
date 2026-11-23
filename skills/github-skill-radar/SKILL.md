---
name: github-skill-radar
description: 每日筛 GitHub 上"好玩 / 有趣 / 好用"的 Agent Skill 与工具并出中文日报。七路 search 采集 → 词表打分（好玩 + 动量 + 质量 − 噪音）→ seen 库去重 → 写 reports/latest.md，已挂 Windows 每日 09:00 定时任务。当用户说"今天有什么好玩的 skill""GitHub 上有什么新东西""帮我盯着某个方向""日报没出来/筛得不准"时使用。
whenToUse: 要看每日/每周 GitHub 精选；要调整筛选口味（太杂、太少、全是合集）；日报脚本报错或被 GitHub 限速；要把它搬到另一台机器或改成飞书推送。
---

# GitHub 有趣 Skill 每日雷达

> 本机成品：`F:\2号机器人\Dsh\skill-radar\`（2026-11-22 建，已实测）
> 本 skill 的 `scripts/` 下是同一份可复制的脚本。

## 一、它产出什么

每天一条 `reports/latest.md`：8 条"高分且没见过"的仓库，每条含一句话、为什么值得看、star 动量、许可、装法。

实测一轮（2026-11-22，无 token）：7 路采集 → **311 个候选** → 84 条过初筛 → 推 8 条，耗时 ≈110s。

## 二、为什么不用现成开源项目

| 现成的 | 星 | 差在哪 |
|---|---|---|
| [majiayu000/claude-skill-registry](https://github.com/majiayu000/claude-skill-registry) | 748 | 每日自动发现的**全量目录**，不做"好不好玩"的主观筛选 |
| [kort0881-free-ai-aggregator](https://github.com/kort0881/kort0881-free-ai-aggregator) | 3 | 架构最像（Actions + LLM 打分），但目标是通用仓库、不做 skill、几乎无人维护 |
| [SoulKyu/github-scraping-agent-ai](https://github.com/SoulKyu/github-scraping-agent-ai) | 6 | 思路对（AI 判断你感不感兴趣），无去重库、工程化差 |
| [fireinrain/github-trending](https://github.com/fireinrain/github-trending) 等 | 7–840 | 只搬 trending，无个性化、无 skill 维度 |
| [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) 等 | 37k | 人工目录，不解决"每天筛" |

结论：**采集用它们的口径，筛选只能自己写**。

## 三、打分口径（改口味就改这里）

| 维度 | 分值 | 位置 |
|---|---|---|
| 好玩/有用关键词命中 | ≤31 | `WOW_WORDS` / `USE_WORDS`（`game*` 前缀匹配，`chess` 整词匹配） |
| 原生 Skill 形态（`agent-skills`、`claude-skills`、`SKILL.md`…） | +12 | `score_repo()` |
| star 动量（stars/天：≥50→15，≥20→12，≥10→8，≥3→5，≥1→2） | ≤15 | 同上 |
| 新鲜度（3 天内推送 +8；建库 ≤30 天 +6） | ≤18 | 同上 |
| 质量门（license +6；描述 ≥40 字 +4；fork/star >5% +4） | ≤14 | 同上 |
| 噪音扣分（合集/目录 −14；免费节点/白嫖/破解 −18；新库 star 异常 −25） | 扣 | `NOISE_WORDS` / `LISTWORDS` |

入选门槛默认 45；**同一作者最多留 2 条**（防一个组织刷屏）；推过的进 `data/seen.sqlite3` 不再推。

## 四、跑与调

```powershell
cd F:\2号机器人\Dsh\skill-radar
python radar.py                 # 默认：近 7 天、推 8 条、门槛 45
python radar.py --days 14 --top 10 --min-score 50
python radar.py --no-seen        # 忽略历史重排（调试）
python radar.py --no-llm         # 强制跳过 LLM 复评
```

定时（已建，任务名 `SkillRadar`，每日 09:00）：

```powershell
Start-ScheduledTask -TaskName "SkillRadar"          # 立刻跑一次
Get-ScheduledTaskInfo -TaskName "SkillRadar"        # 看上次结果
Get-Content F:\2号机器人\Dsh\skill-radar\logs\run.log -Tail 20
Unregister-ScheduledTask -TaskName "SkillRadar" -Confirm:$false   # 不要了
```

## 五、可选增强（不配也能跑）

| 环境变量 | 作用 |
|---|---|
| `GITHUB_TOKEN` | 搜索限额 10 次/分 → 30 次/分，耗时 110s → ≈20s |
| `RADAR_LLM_BASE` / `RADAR_LLM_KEY` / `RADAR_LLM_MODEL` | OpenAI 兼容接口复评：给「趣味分/实用分」+ 中文点评，占最终分 40% |
| `RADAR_FEISHU_WEBHOOK` | 推到飞书群（自定义机器人 webhook） |

## 六、坑（实测踩过）

| 现象 | 根因 | 做法 |
|---|---|---|
| 脚本卡住几分钟不结束 | 无 token 时 7 路查询撞 10 次/分限速，每路退避 25–50s | 代码里无 token 时 `gap=6.5s` 摊开；退避最多 2 次后放弃该路，不拖死整轮 |
| 中文标签乱命中（"唱歌"出现在 ffmpeg） | `sing` 子串命中了 `using` | 短词必须整词匹配（`(?<![a-z0-9])key s?(?![a-z0-9])`），只有明确要前缀匹配的才加 `*` |
| 计划任务日志里日期乱码 | `chcp 65001` 下 `%date%` 仍是 GBK 输出 | 包装脚本里不要 echo `%date%`，时间戳交给 Python 写 |
| `cmd /c run_daily.cmd` 找不到文件 | PowerShell 的 `Set-Location` 不改进程工作目录 | 用 pwsh 的 `workdir` 参数，或 `cmd /c "绝对路径"` |
| 同一组织占满日报 | 采集按 updated 排序 | `per_owner` 上限 2 |

## 七、搬到新机器

1. 复制 `scripts/radar.py` + `scripts/run_daily.cmd` 到一个目录（如 `D:\tools\skill-radar`）；
2. `python radar.py` 跑通一次（只需 Python 3.9+，纯标准库）；
3. 用 `New-ScheduledTaskAction/Trigger` 注册每日任务（见第四节）；
4. 想换方向：改 `SEARCH_QUERIES`（加 `("topic:xxx", "label")`）和 `WOW_WORDS`。
