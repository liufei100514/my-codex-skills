---
name: no-c-drive-storage
description: 落盘位置铁律：非必要不把文件写到 C 盘。给出"什么该放 F:、什么可以留在 C:"的判定口径、$env:TEMP 的陷阱、AI 工具配置目录里只放 junction 不放实体的规则，以及把已有 C 盘克隆/产物迁到 F: 的迁移与自查命令。当要克隆仓库、解压资料、生成中间产物、写日志报告，或怀疑某个任务把文件丢到 C 盘时使用。
whenToUse: 准备 clone / 下载 / 解压 / 生成大文件前；要决定临时目录用哪个；有人（或自己上一轮）用 `$env:TEMP` 做了中间产物；要新建 AI 工具的技能链接；要自查"这次有没有写到 C 盘"。
---

# 非必要不落 C 盘

> 用户明确要求（2026-11-22）：**非必要不把文件存到 C 盘。**
> 本文是落地口径，不是偏好陈述。

## 一、判定表（先看这张）

| 要放的东西 | 放哪 | 理由 |
|---|---|---|
| 知识实体、Skill、脚本、报告、日志、数据库 | `F:\Codex专用知识库\...` / `F:\2号机器人\Dsh\...` | 用户唯一工作区在 F: |
| 第三方仓库克隆、语料库、镜像 | `F:\git-mirrors\<name>` | 可重建，但体积大，不该占系统盘 |
| 临时产物、解压中间件、试验脚本 | `F:\tmp\` | **不要用 `$env:TEMP`**（在 C 盘） |
| AI 工具配置目录里的**技能条目** | `C:\Users\<u>\.codex\skills\<name>` 等，**只放 junction** | 工具只认自己配置目录，链接 0 字节、不存内容 |
| 已安装工具本体（git、python、node、Office） | 原安装位置，不动 | 迁移成本高于收益 |
| 应用认证、配置、实时会话数据库 | 不动（用户 2026-09-16 明确不授权搬移） | 搬了会掉登录/丢会话 |

一句话口径：**内容放 F:，指针可以放 C:，安装体不动。**

## 二、`$env:TEMP` 是最常见的坑

`$env:TEMP` 展开成 `C:\Users\<u>\AppData\Local\Temp`，于是：

| 常见写法 | 后果 |
|---|---|
| `git clone ... $env:TEMP\repo` | 整个仓库实体落在 C 盘 |
| `Expand-Archive -DestinationPath $env:TEMP\x` | 解压产物落 C 盘 |
| `python -m pip install --target $env:TEMP\libs` | 依赖落 C 盘 |
| 脚本里 `$env:TEMP\<name>-backup` | 备份落 C 盘，且用户看不见 |

替换规则：**`$env:TEMP` → `F:\tmp`**（不存在就先建）。

```powershell
New-Item -ItemType Directory -Force -Path 'F:\tmp','F:\git-mirrors' | Out-Null
```

## 三、迁移已有 C 盘产物

```powershell
# 1) 目标目录先建好
New-Item -ItemType Directory -Force -Path 'F:\git-mirrors' | Out-Null

# 2) 跨盘移动（Move-Item 跨卷是"复制+删除"，失败时源还在，可重试）
$src = "$env:TEMP\my-codex-skills"
$dst = 'F:\git-mirrors\my-codex-skills'
if ((Test-Path $src) -and -not (Test-Path $dst)) { Move-Item $src $dst -Force }

# 3) 验证：源没了、目标在、git 还能用
Test-Path $src            # False
Test-Path $dst            # True
git -C $dst log --oneline -1
```

移动前若有改动没提交，先 `git status` 看一眼；跨盘 `Move-Item` 中断会留下半个副本，此时**删目标、留源**再重试。

> 2026-11-22 实例：`$env:TEMP\my-codex-skills`（技能镜像克隆）→ `F:\git-mirrors\my-codex-skills`，HEAD `b229421`，迁完照常 push。

## 四、工具配置目录：只放链接，不放实体

本机四个 AI 工具的技能入口（**这些都是工具自己定的路径，不能改**）：

| 工具 | 技能入口 | 放什么 |
|---|---|---|
| DSH | `C:\Users\<u>\.dsh\skills\` 与 `<工作区>\.dsh\skills\` | junction |
| Codex | `C:\Users\<u>\.codex\skills\` | junction |
| WorkBuddy | `C:\Users\<u>\.workbuddy\skills\` | junction |
| Grok Bot | 无全局目录，扫**工作区内** `<name>/SKILL.md` | 在工作区里建 junction |

```powershell
New-Item -ItemType Junction `
  -Path   'C:\Users\46485\.codex\skills\<skill-name>' `
  -Target 'F:\Codex专用知识库\50-Codex协作\Skills\<skill-name>'
```

判定"是链接还是副本"：

```powershell
Get-Item 'C:\Users\46485\.codex\skills\<skill-name>' | Select-Object LinkType,Target
# Junction + 指向 F: → 合规；空 LinkType → 是实体副本，违反"只放链接"
```

例外：`C:\Users\<u>\.agents\skills\` 由 `skills` CLI 依 `.skill-lock.json` 管理，**不要手塞 junction**（会被清理或破坏锁文件）。

## 五、自查（交活前跑一次）

```powershell
# 1) 我这轮用过的临时位置还在不在 C
Test-Path "$env:TEMP\my-codex-skills"; Test-Path "$env:TEMP\prompt-corpus"

# 2) 工具技能目录里有没有实体副本（应为空）
foreach ($h in @("$env:USERPROFILE\.dsh\skills","$env:USERPROFILE\.codex\skills","$env:USERPROFILE\.workbuddy\skills")) {
  Get-ChildItem $h -Directory -ErrorAction SilentlyContinue |
    Where-Object { -not $_.LinkType } | Select-Object @{n='实体副本';e={$_.FullName}}
}

# 3) 我这轮新写的文件都在哪
Get-ChildItem 'F:\git-mirrors','F:\tmp' -ErrorAction SilentlyContinue | Select-Object FullName
```

## 六、例外与边界

1. **工具安装路径不动**：git 在 `C:\Users\46485\tools\mingit\cmd\git.exe`，python 在 `C:\Users\46485\.workbuddy\binaries\python\...`——这是既有安装，迁移风险大于收益。
2. **`__pycache__` / `.pytest_cache`** 跟着脚本走；脚本在 F 盘（或 junction 指向 F 盘）时就落在 F 盘，不用额外处理。
3. **系统计划任务**是注册表项，不是文件，不受本约束。
4. 若将来要连配置目录一起搬（如 `CODEX_HOME` 指到 F:），先确认该工具支持环境变量覆盖，失败就回滚——**不要为省几 MB 把工具搞坏**。

## 七、执行记录（本机现状）

| 日期 | 动作 | 结果 |
|---|---|---|
| 2026-11-22 | `$env:TEMP\my-codex-skills` → `F:\git-mirrors\my-codex-skills` | 迁完照常 push |
| 2026-11-23 | `~/.codex/skills` + `~/.workbuddy/skills` 的 **54 个实体副本**迁入 Obsidian `Skills/` 并回填 junction | 搬出 C 盘 **24.05 MB**；备份 `F:\tmp\skills-migrate-backup-20261123-101003`；日志 `F:\tmp\skills-migrate-20261123-101003.log` |

迁移脚本与审计脚本（可复用）：`F:\tmp\migrate-skills.ps1`、`F:\tmp\inv-skills.ps1`、`F:\tmp\diff-collisions.ps1`。

**同名冲突的处理规则（重要）**：两边都有同名技能时，不能盲删。本次遇到 4 例：
- 只有 `SKILL.md` 有差异、Obsidian 版本更大 → 保留 Obsidian；
- 一边是"薄壳"、一边带 `references/` 与 `_skillhub_meta.json` → **把富版本合并进 Obsidian**（本次 `a-share-daily-review`：C 盘薄壳 2.4KB vs WorkBuddy 20KB+7 个 references，已按富版本合并）；
- 只差 `__pycache__/*.pyc` → 忽略，不合并。

## 八、已知遗留

| 项 | 现状 | 建议 |
|---|---|---|
| `~/.codex/skills/.system` | Codex 系统自带目录，实体在 C 盘 | 不动（升级会被重写） |
| `F:\2号机器人\Dsh\.dsh\skills\cangjie-skill` | F 盘上的重复实体（85 文件 vs Obsidian 63 文件，内容不同） | 在 F 盘，不影响 C 盘约束；要统一需人工确认留哪版 |
