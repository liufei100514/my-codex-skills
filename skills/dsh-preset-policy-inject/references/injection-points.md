# DSH 提示词注入点对比

来源：实测 + `dsh-purge` 源码（`lib/core.js`、`lib/rules.js`、`lib/index.js`）。

---

## 1. 一处注入口径总表

| 注入点 | 路径 | 生效范围 | 能否追加 | 会被覆盖吗 |
|---|---|---|---|---|
| **prompt-inject.md** | `~/.dsh/prompt-inject.md` | 所有会话的基础人设 | ❌ 含插件三标记即被误判 | ✅ dsh-purge 原子写回 |
| **preset persona.prefix** | `~/.dsh/.agent-presets/<p>/agent.cordis.yml` | 用该 preset 的会话 | ✅ 可改（但会替换原人设的段落） | ❌ |
| **preset persona.suffix** | 同上 | 同上 | ✅ **推荐** | ❌ |
| **profile cordis.patch.yml** | `~/.dsh/profiles/<profile>/cordis.patch.yml` | 该 profile 的插件/工具 | ✅ | 手动改的会保留 |
| **项目 AGENTS.md** | 工作区根目录 | 该目录下的会话 | ✅ | ❌（但只对被读取的 agent 有效） |
| **skills/<name>/SKILL.md** | `~/.dsh/skills/` 或 `.dsh/skills/` | 触发时加载 | ✅ | ❌ |

## 2. prompt-inject.md 的守护机制

`dsh-purge/lib/core.js`：

```js
export function syncPromptInjectOnDiskSync(dshHome) {
  const bundled = defaultOverrideText();
  const bundledNorm = normalizeOverride(bundled);
  if (!bundledNorm) return { action: "skip", reason: "empty_slot" };
  const fp = findOverrideFile(home);
  const diskRaw = readPromptInjectFileSync(home);
  const diskNorm = normalizeOverride(diskRaw);
  if (isKeepableUserOverride(home, diskRaw)) {
    return { action: "keep", reason: "user_custom" };      // 只有这里才保留
  }
  if (diskNorm === bundledNorm) return { action: "keep", reason: "current" };
  atomicWriteSync(fp, bundled, "utf8");                    // 否则写回默认
  writeOverrideStateSync(home, { customized: false, hash: hashOverride(bundled), ... });
}
```

`isKeepableUserOverride` 的判定顺序（任一命中即"不是用户的"）：

1. 空内容
2. 等于默认内容
3. `looksLikePluginDefault(text)` —— **三个标记全中**
4. `state.seedHash === hash(text)`
5. `state.customized !== true && overrideTextIsOurs(state, text)`

三个标记：

```js
const PLUGIN_DEFAULT_MARKS = [
  "<|im_start|>system:",
  "<project_instructions>",
  "Little Code Sauce",
];
```

**推论**：只要保留原人设（必然含这三个标记），追加内容 100% 被抹。想走这条路只能"完全另写一份不含标记的提示词"，那就丢了原人设 —— 不划算。

## 3. hash 算法（改 override-state 时要对齐）

```js
export function normalizeOverride(text) {
  return String(text ?? "").replace(/\r\n/g, "\n").trim();
}
export function hashOverride(text) {
  return createHash("sha256").update(normalizeOverride(text), "utf8").digest("hex");
}
```

即：CRLF→LF、trim、UTF-8 编码后 sha256。

PowerShell 等价：

```powershell
$text = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
$norm = ($text -replace "`r`n","`n").Trim()
$sha  = [System.Security.Cryptography.SHA256]::Create()
$hash = ($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($norm)) | ForEach-Object { $_.ToString('x2') }) -join ''
```

## 4. 找 preset 的完整路径清单

```
~/.dsh/.agent-presets/<name>/agent.cordis.yml          ← 生效
~/.dsh/.agent-presets/<name>/preset.yml                ← 显示名/描述/排序
~/.dsh/.agent-presets/<name>.bak-<日期>/                ← 备份，别改
~/.dsh/plugins/dsh-purge/presets/<name>/agent.cordis.yml       ← 插件模板
~/.dsh/profiles/<profile>/node_modules/dsh-purge/presets/<name>/agent.cordis.yml  ← 常与上一条硬链接
```

判断硬链接：

```powershell
Get-Item <path> | Select-Object Name, LinkType, Target
# LinkType = HardLink 表示与其他路径是同一物理文件
```

## 5. dsh-purge 关心的范围（别误伤）

从 `lib/core.js` / `identity.js` / `index.js` 的 grep 结果看，它主要处理：

- `prompt-inject.md` 的 seed / sync / hash
- 红队 preset 的**识别**（`isRedteamPresetId`、`withoutRedteamPreset`）—— 只读判断，不写 preset 文件
- 规则表 / 面授权（`surface.js`、`rules.js`）

**没有任何"写回 `.agent-presets`"的逻辑** —— 所以在 `.agent-presets` 里做的修改不会被 reapply 抹掉（插件模板那份只在安装/重装时用）。

## 6. 什么时候该用哪一层

- "以后每次都要这样" → preset persona.suffix
- "这个项目里要这样" → 项目 AGENTS.md
- "做这类任务要这样" → 技能 SKILL.md（靠 description 命中）
- "这次先这样" → 直接说
