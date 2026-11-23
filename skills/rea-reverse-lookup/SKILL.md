---
name: rea-reverse-lookup
description: 逆向类目标的"动手前查表"技能。基于 Awesome-REA 目录（3.3k★，5,191 条资源/4,025 案例/442 论文/3,309 仓库，六域：website/game/app/binary/firmware/protocol），用本地稀疏克隆 + `catalog.py` 离线检索选工具与参考案例，再把结论交回红队/正常执行链动手。当目标涉及 JS 混淆、APK/IPA 逆向、游戏包与引擎资源、固件、私有协议、二进制分析，而不知道该用哪个工具、或想先看别人怎么做的时使用。
whenToUse: 拿到 APK/IPA/小程序包/游戏资源包/固件镜像/私有协议抓包，不知道从哪下手；要在 frida / jadx / ghidra / unicorn / mitmproxy 之间选型；要给某一类逆向任务找可参考的公开案例；红队流程中"发现"阶段之前需要确定静态/动态分析路线。
---

# 逆向动手前先查表（Awesome-REA）

> 实测日期 2026-11-23。上游 `reacher-z/Awesome-REA`：MIT，3,369★，仍在日更。

## 一、它是什么 / 不是什么

| 是 | 不是 |
|---|---|
| 逆向工程资源目录 + 生成站点（`awesomerea.org`）+ 开放 API | ❌ 攻击框架，不发包、不提权、不搭隧道 |
| 5,191 条策展资源 · 4,025 个案例 · 442 篇论文 · 3,309 个已索引仓库 | ❌ “已验证可用”背书；`source-reviewed` 只代表文档审阅 |
| 六域分类 + 证据分级 + 243 个测试 + validator | ❌ 我们红队模式的替代品（红队是执行与留痕） |

一句话：**它是菜谱库，红队模式是厨房。**用在“选工具/找案例”这一步。

## 二、本地落地（F 盘，稀疏克隆）

```powershell
$git = 'C:\Users\46485\tools\mingit\cmd\git.exe'
$dir = 'F:\git-mirrors\Awesome-REA'
if (-not (Test-Path $dir)) {
  & $git clone --depth 1 --filter=blob:none --no-checkout https://github.com/reacher-z/Awesome-REA.git $dir
  & $git -C $dir sparse-checkout init --cone
  & $git -C $dir sparse-checkout set data scripts docs
  & $git -C $dir checkout
}
& $git -C $dir pull --ff-only     # 每日更新
```

体积要点：`data/` 合计约 35MB（`tool-resources.json` 9.93MB、`source-index.json` 6.52MB、`papers.json` 1.75MB）。**不要把 README（英文 390KB / 中文 425KB）读进上下文**，用 `catalog.py` 检索。

## 三、检索（唯一入口）

```powershell
python F:\git-mirrors\Awesome-REA\scripts\catalog.py frida          # 关键词
python F:\git-mirrors\Awesome-REA\scripts\catalog.py --papers sbox  # 只查论文
python F:\git-mirrors\Awesome-REA\scripts\catalog.py --source-index unidbg   # 查自动扫描发现（未策展）
python F:\git-mirrors\Awesome-REA\scripts\catalog.py --list-categories
```

实测覆盖（命中数）：`ghidra` 1,361 · `jadx` 130 · `apktool` 80 · `unicorn` 99 · `frida` 80 · `il2cppdumper` 25 · `binwalk` 29 · `mitmproxy` 13。

## 四、六域 → 红队动作映射

| 目标形态 | REA 域 | 先查什么 | 之后交给谁干 |
|---|---|---|---|
| 前端 JS 混淆、SPA 接口藏在 bundle 里 | `website`（128 条） | 反混淆/解包工具、`web-analysis` 类目 | 红队 `recon` 提接口 → `vuln-scan` 探未授权 |
| APK / IPA / 小程序原生包 | `app` | `jadx`/`apktool`/`frida`/`objection`；脱壳类 | `exploit` 取密钥/接口签名/硬编码凭据 |
| 游戏资源包、引擎实现、加密表 | `game`（2,976 条，最大域） | `il2cppdumper`/`assetripper`/引擎 re 案例 | 协议与签名逆推 → `exploit` |
| 服务端二进制 / so / dll | `binary` | `ghidra`/`radare2`/`unicorn`/`angr` | 找后门口令、硬编码密钥、反序列化面 |
| 固件镜像、路由器/IoT | `firmware` | `binwalk`/固件提取类 | 默认口令、未授权接口（→ `vuln-scan`） |
| 私有协议、抓包看不懂 | `protocol` | `mitmproxy`/协议解析案例 | 构造请求重放（→ `exploit`） |

## 五、证据口径（直接借它的分级）

- `verification: source-reviewed` = **只做过文档审阅**，不等于跑通、不等于可用、不等于安全；
- 证据链接钉在**已审阅的 commit**（`/blob/<sha>/...`），`url` 是可动的项目主页；
- 记录里有 `verified_at`（审阅日期）、`requirements`（前置条件 + 局限）、`relationship`（与 REA 的关系强度）。

用法：写进自己的结论时**照抄这个措辞纪律**——"某工具支持 X（据其 README，审阅日 2026-11-09）"，而不是"某工具能打 X"。

## 六、坑

| 坑 | 做法 |
|---|---|
| 想一次读 README 找灵感 | 390KB，直接烧上下文；用 `catalog.py` |
| 把目录条目当"已验证工具" | 只是文档审阅；跑通要自己验，且要写清验证方式 |
| 想全量搬进 Obsidian | 35MB JSON，不进知识库；按需稀疏拉 |
| 指望它替代红队流程 | 它没有任何执行能力；结论必须交回 `vuln-scan`/`exploit` 落地 |
| 贡献条目时手改生成块 | 它的 AGENTS.md 明令禁止；必须改 `data/*.json` 再跑 `build_readme.py` |

## 七、贡献（可选）

目录里没有的常用工具可提 PR：改 `data/tool-resources.json` → 补 `site/translations.zh-CN.json` → `python3 scripts/build_readme.py` + `build_repository_index.py` + `validate.py` → 提 issue/PR。
实测缺口（2026-11-23，只出现在自动扫描索引、未策展）：`unidbg`、`BlackDex`、`FART`、`youpk`、`jshook`、`v_jstools`。
