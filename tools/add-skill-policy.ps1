<#
  给 DSH 的任意 agent preset 补上「技能与工作流沉淀」全局规范（幂等）
  ------------------------------------------------------------------
  作用：在 preset 的 persona 组件里添加 suffix 段，让每个用该 preset 的会话
        都带上"任务收口必须提报可复用候选"的硬要求。

  为什么不用 ~/.dsh/prompt-inject.md：
        那个文件被 dsh-purge 守护，只要内容里含 <|im_start|>system: /
        <project_instructions> / Little Code Sauce 三个标记，就被判定为
        "插件默认"，任何追加都会被原子写回。persona.suffix 不受影响。

  用法：
    # 给单个 preset
    powershell -NoProfile -ExecutionPolicy Bypass -File .\add-skill-policy.ps1 -PresetPath "C:\Users\<你>\.dsh\.agent-presets\<name>\agent.cordis.yml"

    # 给所有用户级 preset（跳过 .bak 备份目录）
    powershell -NoProfile -ExecutionPolicy Bypass -File .\add-skill-policy.ps1 -All

    # 只看会改什么
    powershell -NoProfile -ExecutionPolicy Bypass -File .\add-skill-policy.ps1 -All -DryRun
#>
param(
  [string]$PresetPath,
  [switch]$All,
  [switch]$DryRun,
  [string]$PresetsRoot = (Join-Path $env:USERPROFILE '.dsh\.agent-presets'),
  [string]$NodePath = 'C:\Users\46485\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe',
  [string]$YamlLib   = 'F:/DSH/resources/app/dsh/node_modules/yaml/dist/index.js'
)

$ErrorActionPreference = 'Stop'

$Block = @(
  '    # 全局规范：任务收口必须提报可复用候选（跨任务长期有效，不受 dsh-purge 影响）'
  '    suffix: |'
  '      ## 技能与工作流沉淀（全局规范 · 长期有效）'
  ''
  '      任何对话任务中，只要产生了可复用的东西，**必须在任务收口时主动提报**，等用户明确同意后再落库。不要等用户想起来问。'
  ''
  '      **算候选**：反复要做的流程（发布/备份/同步/迁移/验收/对接外部系统）；踩过的坑加正确解法（症状→根因→做法）；可参数化的模板、脚本、清单；跨任务成立的判断口径（单位、取价口径、缺数据语义、超时阈值、去重规则）。'
  ''
  '      **不算候选**：单次任务进度、完成状态、页面或文件小改、版本号、部署结果、一次性排障过程、临时路径、聊天记录、工具日志、任何凭据与个人信息。'
  ''
  '      提报格式（任务末尾一次说清）：'
  ''
  '      ```'
  '      候选：<一句话名称>'
  '      来源：<哪个任务 / 哪条证据>'
  '      可复用点：<流程 / 清单 / 口径 / 脚本>'
  '      建议落点：Obsidian 50-Codex协作/Skills/<kebab-name>/ ＋ GitHub 同步'
  '      ```'
  ''
  '      同意后按固定路径落库：写 Obsidian `50-Codex协作/Skills/<name>/SKILL.md` → 更新 `Codex协作索引.md` → 推 GitHub（精确覆盖，禁止 `robocopy /MIR`）→ 给 DSH 用则补 junction。'
  ''
  '      **唯一两处存储**：Obsidian（实体）+ GitHub `liufei100514/my-codex-skills`（镜像）。其它位置——项目目录、AI 配置目录、桌面、临时文件夹——只放链接不放副本。'
  ''
  '      **提报 ≠ 入库**：没拿到明确同意就不写；允许用户改名、改落点、就地否掉；同一条候选不重复提。'
)

function Add-PolicyToPreset {
  param([string]$Path)

  if (-not (Test-Path $Path)) { return "跳过（文件不存在）" }
  $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
  if ($text.Contains('技能与工作流沉淀')) { return "跳过（已含规范）" }

  $lines = $text -split "`n"

  # 1) 定位 persona 组件
  $personaIdx = -1
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^-\s+id:\s*persona\s*$') { $personaIdx = $i; break }
  }
  if ($personaIdx -lt 0) { return "跳过（没有 persona 组件，需手工加）" }

  # 2) 在 persona 段内找 prefix 块，确定块结束位置
  $prefixIdx = -1
  for ($i = $personaIdx + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*prefix:\s*\|') { $prefixIdx = $i; break }
    if ($lines[$i] -match '^-\s+id:') { break }
  }

  $insertAt = $personaIdx + 1
  if ($prefixIdx -ge 0) {
    $j = $prefixIdx + 1
    while ($j -lt $lines.Count) {
      if ($lines[$j].Trim() -eq '') { $j++; continue }
      $indent = $lines[$j].Length - $lines[$j].TrimStart().Length
      if ($indent -lt 6) { break }
      $j++
    }
    $insertAt = $j
  } else {
    # 没有 prefix 就直接插在 persona 行之后（保持 4 空格缩进）
    $insertAt = $personaIdx + 1
  }

  if ($DryRun) { return "将插入第 $($insertAt + 1) 行（dry-run）" }

  $backup = "$Path.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
  Copy-Item $Path $backup -Force

  $new = @()
  $new += $lines[0..($insertAt - 1)]
  $new += $Block
  $new += $lines[$insertAt..($lines.Count - 1)]
  [System.IO.File]::WriteAllLines($Path, $new, (New-Object System.Text.UTF8Encoding($false)))

  # 3) YAML 校验（失败自动回滚）
  if ((Test-Path $NodePath) -and (Test-Path $YamlLib)) {
    $probe = Join-Path $env:TEMP 'preset-yaml-verify.cjs'
    $js = @"
const fs=require('node:fs');const yaml=require('$($YamlLib -replace '\\','/')');
try{yaml.parse(fs.readFileSync(process.argv[2],'utf8'));console.log('YAML_OK');}catch(e){console.log('YAML_FAIL:'+e.message);process.exit(1);}
"@
    [System.IO.File]::WriteAllText($probe, $js, (New-Object System.Text.UTF8Encoding($false)))
    $out = & $NodePath $probe $Path 2>&1
    if ($LASTEXITCODE -ne 0) {
      Copy-Item $backup $Path -Force
      return "YAML 校验失败已回滚：$out"
    }
  }
  return "已写入（备份 $([System.IO.Path]::GetFileName($backup))）"
}

# ── 目标收集 ────────────────────────────────────────────────
$targets = @()
if ($PresetPath) { $targets += $PresetPath }
if ($All) {
  Get-ChildItem $PresetsRoot -Directory -EA SilentlyContinue |
    Where-Object { $_.Name -notmatch '\.bak' } |
    ForEach-Object {
      $f = Join-Path $_.FullName 'agent.cordis.yml'
      if (Test-Path $f) { $targets += $f }
    }
}
if (-not $targets.Count) { Write-Host "没有目标。用 -PresetPath 指定文件，或 -All 扫 $PresetsRoot"; exit 1 }

foreach ($t in $targets) {
  $result = Add-PolicyToPreset -Path $t
  Write-Host ("{0}`n  -> {1}" -f $t, $result)
}
