---
name: dsh-preset-policy-inject
description: 给 DSH（DeepSeek Harness / Codex 系）的 agent preset 注入全局规范或人设补充，让"每个会话都强制遵守某条规则"。覆盖注入点选型、prompt-inject.md 被 dsh-purge 反复还原的根因、persona.suffix 的正确写法、YAML 校验与回滚、硬链接副本同步。当用户要求"把某条规定作为全局规范""以后每次都要这样做"，或改了提示词发现没生效/被还原时使用。
whenToUse: 要给 DSH 加全局规则或人设追加；`~/.dsh/prompt-inject.md` 改了不见或被还原；新建 preset 需要统一注入；排查"提示词改了没生效"。
---

# 给 DSH preset 注入全局规范

## 一、先判断：你要的是"全局"还是"这次"

| 需求 | 落点 |
|---|---|
| 每个会话都必须遵守（长期规范） | preset 的 `persona.suffix` ← 本文 |
| 只是这次对话的临时要求 | 直接说，不入库 |
| 某一类任务的做法（触发才需要） | 写成 `skills/<name>/SKILL.md`，靠 description 命中 |
| 项目级约定（某个代码库） | 项目根的 `AGENTS.md` |

## 二、为什么不能改 `~/.dsh/prompt-inject.md`

它是红队人设的载体，但被 `dsh-purge` 插件守护。判定逻辑（`dsh-purge/lib/core.js`）：

```js
const PLUGIN_DEFAULT_MARKS = [
  "<|im_start|>system:",
  "<project_instructions>",
  "Little Code Sauce",
];

export function looksLikePluginDefault(text) {
  const n = normalizeOverride(text);
  if (!n) return false;
  if (n === normalizeOverride(defaultOverrideText())) return true;
  return PLUGIN_DEFAULT_MARKS.every((mark) => n.includes(mark));
}

export function isKeepableUserOverride(dshHome, text) {
  const incoming = normalizeOverride(text);
  if (!incoming) return false;
  if (incoming === normalizeOverride(defaultOverrideText())) return false;
  if (looksLikePluginDefault(text)) return false;          // ← 三个标记全中就被判为"插件默认"
  const state = readOverrideStateSync(dshHome);
  const stamp = hashOverride(text);
  if (typeof state?.seedHash === "string" && state.seedHash === stamp) return false;
  if (state.customized !== true && overrideTextIsOurs(state, text)) return false;
  return true;
}
```

**只要文件里还留着那三个标记，追加的任何内容都会被判成"插件默认"，`syncPromptInjectOnDiskSync` 会原子写回默认值。** 实测：把 `override-state.json` 的 `customized` 改成 `true` 也没用——那道血统检测在它前面，先命中先返回。

结论：**想保留原人设又追加规则，这条路走不通**。

## 三、正确落点：persona 的 suffix

`~/.dsh/.agent-presets/<preset>/agent.cordis.yml` 里的 persona 组件：

```yaml
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: |
      ## 原有人设内容（不动它）
      ...
    suffix: |          # ← 新增这一段
      ## 你的全局规范
      ...
```

- `prefix` / `suffix` 都会拼进系统提示，`suffix` 在后
- 这一层 `dsh-purge` 不管，不会被还原
- preset 的 persona 会 shadow 部署默认为该 agent 生效

## 四、四步做完

### 1. 找到所有要改的文件

```powershell
Get-ChildItem "$env:USERPROFILE\.dsh" -Recurse -File -Filter 'agent.cordis.yml'
```

典型会看到三类：
- `\.dsh\.agent-presets\<name>\agent.cordis.yml` → **生效的那份**，必改
- `\.dsh\plugins\dsh-purge\presets\<name>\agent.cordis.yml` → 插件模板，防止重装/回滚打回原形
- `\.dsh\profiles\*\node_modules\dsh-purge\presets\<name>\agent.cordis.yml` → 通常与上一条是**硬链接**（同一文件）

`Get-Item <path> | Select LinkType` 确认是否 HardLink：硬链接改一次两处都变，别重复改。

### 2. 用脚本插入（幂等 + 自动备份 + YAML 校验回滚）

```powershell
# 所有用户级 preset（自动跳过 .bak）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\add-skill-policy.ps1 -All

# 指定文件
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\add-skill-policy.ps1 -PresetPath "C:\Users\<you>\.dsh\.agent-presets\redteam\agent.cordis.yml"

# 干跑
-All -DryRun
```

脚本行为：已含目标文本就跳过 → 备份 `.bak-<时间戳>` → 在 persona 的 prefix 块之后插入 suffix → 用 DSH 自带的 yaml 解析器校验 → 失败自动回滚。

### 3. 手工改的话，插入位置要精确

```
- id: persona          ← persona 起点
  name: ...
  config:
    prefix: |          ← 块标量起点
      ...内容（缩进 ≥6）
      ...最后一行
    suffix: |          ← 插在这里（缩进 4）
      ...新内容（缩进 ≥6）
- id: 下一个组件        ← 缩进 0
```

判定 prefix 块结束：往下找第一个**缩进 < 6 的非空行**。插错会破坏 YAML，preset 加载失败 → DSH 起不来。

### 4. 校验（必做）

用 DSH 自带的 yaml 库，别用猜的：

```powershell
$node = 'C:\Users\<you>\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$yaml = 'F:/DSH/resources/app/dsh/node_modules/yaml/dist/index.js'
node -e "const y=yaml.parse(require('fs').readFileSync(process.argv[1],'utf8'));const p=y.find(r=>r&&r.id==='persona');console.log('组件',y.length,'suffix',p.config.suffix.length)" '<preset文件>'
```

警告 `TAG_RESOLVE_FAILED: tag:yaml.org,2002:js` 是 DSH 自定义的 `!!js` 标签（`disabled: !!js process.platform === 'win32'` 这类），**不影响**，忽略即可。

## 五、验证生效

**必须新开会话**。preset 是会话启动时加载的，当前会话改完不会立刻带上。

验证方法：新会话里让 AI 做一件该触发规则的事，看它有没有主动执行。没执行就是没生效，回头查 YAML 是否解析成功、suffix 是否真的在文件里。

## 六、坑

| 坑 | 后果 / 处理 |
|---|---|
| 只改 `prompt-inject.md` | 被 dsh-purge 还原，白改（实测立即被抹） |
| 改 `override-state.json` 的 `customized: true` | 无效，血统检测先命中 |
| 硬链接副本重复改 | 改一次两处都变，重复改反而可能触发冲突 |
| 缩进写错 | YAML 解析失败 → preset 加载失败 → DSH 起不来；脚本会回滚 |
| 只改插件模板不改用户级 | 不生效（生效的是 `.agent-presets` 那份） |
| 改完不新开会话就验收 | 误判为"没生效" |

## 七、配套

- `scripts/add-skill-policy.ps1` —— 幂等补丁工具，正文写的规则改动时改这个脚本里的 `$Block`
- `references/injection-points.md` —— 各注入点对比、dsh-purge 相关源码位置、找 preset 的完整路径清单
