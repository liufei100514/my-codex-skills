# 技能与工作流存储约定

> 立此约定的目的：所有 AI（DSH / Codex / WorkBuddy / 其它）读同一份技能，改一次处处生效，不再出现"三个地方三个版本"。

## 一、唯一两处

| 位置 | 角色 | 路径 |
|---|---|---|
| **Obsidian** | **唯一实体**（source of truth） | `F:\Codex专用知识库\50-Codex协作\Skills\`（真实路径 `F:\codex工作区\05-知识库与技能\Codex专用知识库\...`） |
| **GitHub** | 远端镜像 / 换机共享 | https://github.com/liufei100514/my-codex-skills （`skills/` 目录） |

除此之外的任何位置——项目目录、AI 配置目录、桌面、临时文件夹——**只允许放链接，不允许放副本**。

## 一之二、主动提报（对 AI 的硬要求）

AI 在**任何任务收口时**，只要产生了可复用的东西，必须主动提报，不能等用户想起来问。

**算候选**：反复要做的流程（发布/备份/同步/迁移/验收/对接外部系统）、踩过的坑加正确解法、可参数化的模板脚本清单、跨任务成立的判断口径（单位、取价口径、缺数据语义、超时阈值、去重规则）。

**不算候选**：单次任务进度、完成状态、页面或文件小改、版本号、部署结果、一次性排障过程、临时路径、聊天记录、工具日志、任何凭据与个人信息。

提报格式（任务末尾一次说清）：

```
候选：<一句话名称>
来源：<哪个任务 / 哪条证据>
可复用点：<流程 / 清单 / 口径 / 脚本>
建议落点：Obsidian 50-Codex协作/Skills/<kebab-name>/ ＋ GitHub 同步
```

**提报 ≠ 入库**：没拿到明确同意就不写。用户可改名、改落点、就地否掉。同一条候选不重复提。

## 二、铁律

1. **只在 Obsidian 建实体**。GitHub 是镜像，不是编辑入口。
2. **不给任何地方留副本**。需要让某个 AI 读到，就用链接指过去。
3. **改一处即改全部**：改 Obsidian → 推 GitHub → 所有 AI 下次读取就是新版。

## 三、DSH 怎么读到（已按此配置）

```
F:\2号机器人\Dsh\.dsh\skills\
├── lark-apaas-app-builder     → Junction → Obsidian\50-Codex协作\Skills\lark-apaas-app-builder
├── kingdee-k3cloud-readonly   → Junction → Obsidian\...\kingdee-k3cloud-readonly
├── connector-market           → Junction → Obsidian\...\connector-market
└── stock-strategy-assistant   → Junction → Obsidian\...\stock-strategy-assistant
```

`.dsh/skills/` 下**没有任何实体目录**，全是 junction。删除 Obsidian 里某个技能，DSH 侧自动消失；改内容，DSH 侧自动是新版。

新增技能后补链接：

```powershell
New-Item -ItemType Junction `
  -Path "F:\2号机器人\Dsh\.dsh\skills\<skill-name>" `
  -Target "F:\Codex专用知识库\50-Codex协作\Skills\<skill-name>"
```

## 四、新增或修改一个技能的流程

1. 在 `50-Codex协作/Skills/<skill-name>/` 下写 `SKILL.md`（frontmatter 必须有 `name` + `description`）。
2. 按需加 `references/`、`scripts/`、`agents/openai.yaml`。
3. 在 `Codex协作索引.md` 的「技能与自动化」章节加一条 wikilink。
4. 推 GitHub（见第六节）。
5. 若要给 DSH 用，补 junction（见第三节）。

## 五、目录与命名规范

```
<skill-name>/
├── SKILL.md               # 必须有；frontmatter: name, description（+可选 whenToUse）
├── agents/openai.yaml     # 可选：display_name / short_description（Codex 界面用）
├── references/*.md        # 可选：长文档拆分
├── scripts/*              # 可选：可直接跑的脚本
└── assets/*               # 可选：模板、样例
```

- 目录名 **kebab-case 英文**，与 `SKILL.md` 里的 `name` 一致
- `description` 写清"什么时候用"，中文更利于命中
- 一个技能一个目录，不并列同义技能（同义就合并）

## 六、同步到 GitHub

```powershell
$git = 'E:\workbuddy\resources\vendor\PortableGit\cmd\git.exe'
$work = "$env:TEMP\my-codex-skills"
if (-not (Test-Path $work)) { & $git clone https://github.com/liufei100514/my-codex-skills.git $work }
else { & $git -C $work pull --ff-only }

# 只精确覆盖要同步的技能（下面是示例清单，按需增删）
$sync = @('lark-apaas-app-builder', 'kingdee-k3cloud-readonly')
foreach ($s in $sync) {
  $dst = Join-Path $work "skills\$s"
  if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
  Copy-Item "F:\Codex专用知识库\50-Codex协作\Skills\$s" $dst -Recurse -Force
}

# 新增 clone 后要配身份，否则 commit 报 Author identity unknown
& $git -C $work config user.name  'liufei100514'
& $git -C $work config user.email 'liufei100514@users.noreply.github.com'

& $git -C $work add -A
& $git -C $work commit -m "sync: 从 Obsidian 同步技能"
& $git -C $work push origin main
```

> ⚠️ **绝对不要用 `robocopy /MIR`**：`/MIR` 会把目标端"源里没有"的文件删掉。
> 2026-11-15 有一次误用，把 GitHub 仓库里 5 个原有技能（a-share-*、production-daily-analysis、silicone-rubber-process-diagnosis、test-driven-development）全部标记为删除，靠 `git checkout -- .` 才恢复。
> 同步只做"精确覆盖指定技能"，不做目录镜像。

> 说明：`miaoda-rd-*` 两个项目专用技能只在 Obsidian 使用，不同步到 GitHub，所以上面的 `$sync` 清单里不要放它们。

## 七、冲突与回滚

- **以 Obsidian 为准**。GitHub 落后时直接覆盖推送。
- **不要在 GitHub 网页上直接改技能**——下次同步会被覆盖。
- 批量改动前先备份：`Copy-Item <Skills目录> $env:TEMP\skills-backup-YYYYMMDD-HHMMSS -Recurse`。

## 八、当前技能清单

| 技能 | 用途 | GitHub 同步 |
|---|---|---|
| `lark-apaas-app-builder` | 飞书妙搭全栈应用搭建/改造（平台契约、前后端范式、外部同步、ERP 集成、成本样板） | ✅ |
| `kingdee-k3cloud-readonly` | 金蝶云星空只读取数（物料、采购价、库存） | ✅ |
| `connector-market` | WorkBuddy 连接器市场 306 个连接器接入 DSH | 待定 |
| `stock-strategy-assistant` | A 股策略助手（行情、选股、复盘） | 待定（GitHub 已有 `a-share-*`，需先去重） |
| `miaoda-rd-platform-delivery` | 项目专用：妙搭研发平台交付工作流 | ❌ 仅 Obsidian |
| `miaoda-rd-data-lifecycle` | 项目专用：妙搭数据迁移与备份 | ❌ 仅 Obsidian |

## 九、为什么不留副本

副本一定会漂移。三个地方放同一份技能，一周后就会出现"DSH 里是旧版、Obsidian 里是新版、GitHub 里是谁也说不清"的局面，然后所有人都不知道该信哪一份。链接不占空间、不会过期，改一处全局生效。

---

制定日期：2026-11-15
适用：本机全部 AI 工具
维护：改这个文件要同步推 GitHub
