---
name: feishu-app-drive-permission
description: 排查「飞书自建应用能读某个云文档、读另一个却 403」这类权限问题。覆盖四层排查顺序（协作者 → 文件公共权限 → 文件安全设置 security_entity → 应用权限范围）、用应用身份直测下载来绕过服务端缓存、以及用 lark-cli 改文件权限的正确姿势。当应用报「没有该源文件的读取权限」「请添加只读协作者」，或同步任务突然读不到某个飞书文件时使用。
whenToUse: 飞书应用读云文档失败、同步任务报无权限、只想开最小权限却不知道怎么配、排查"同一个应用为什么 A 文件能读 B 文件不能"。
---

# 飞书应用读云文档：权限四层排查

真实案例：同一个应用，气相配方表能读，沉淀配方表 403。查了半天应用权限，真正的原因在**文件自己的安全设置**上。

## 一、先做一件事：用应用身份直测，别信服务端报错

服务端有 token 缓存、有错误包装，容易误导。直接拿 `app_id + app_secret` 换一个**全新** `tenant_access_token`，自己下载一次：

```bash
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
{"app_id":"cli_xxx","app_secret":"***"}

GET https://open.feishu.cn/open-apis/drive/v1/files/{file_token}/download
Authorization: Bearer {tenant_access_token}
```

- 200 → 应用能读，问题在服务端（token 缓存 / 代码）
- 403 → 应用确实读不了，往下查文件权限
- 同一应用对 A 文件 200、B 文件 403 → **纯粹是文件级差异**，跟应用权限配置无关

`scripts/probe-app-download.ps1` 就是这个测试，一步出结果。

## 二、四层排查顺序（从最可能到最不可能）

| 层 | 查什么 | 命令 | 命中率 |
|---|---|---|---|
| 1 | 文件协作者列表 | `lark-cli drive +member-list --token X --type file` | 中 |
| 2 | 文件公共权限 | `lark-cli drive +permission-get-setting --token X --type file` | 低 |
| 3 | **文件安全设置 security_entity** | 同上，看 `security_entity` 字段 | **高** |
| 4 | 应用权限范围 | 开放平台 → 权限管理 → 可访问的数据范围 | 低 |

### 第 1 层：协作者

对比"能读的文件"和"读不了的文件"的成员列表。缺人就补：

```bash
lark-cli drive +member-add --token X --type file \
  --member-id ou_xxx --member-type openid --perm view --yes
```

注意：**应用的 appid 加不进去**（`--member-type appid` 会报 `Invalid parameter`）。应用靠的是 tenant 级权限，不是文件协作者。

### 第 2 层：公共权限

对比两份文件的 `link_share_entity`。`tenant_readable`（组织内可读）是正常值。两份都是 `tenant_readable` 还读不了，直接看第 3 层。

### 第 3 层：security_entity —— 真正的高发原因

```bash
lark-cli drive +permission-get-setting --token X --type file
```

看这个字段：

| 值 | 含义 | 应用能读吗 |
|---|---|---|
| `anyone_can_view` | 任何可查看者可管理安全设置 | ✅ |
| `anyone_can_edit` | 任何可编辑者可管理 | ✅ |
| `only_full_access` | **只有完全访问权限者可管理** | ❌ 应用身份被挡 |

`only_full_access` 会连带限制应用身份的读取——即使 `link_share_entity` 是 `tenant_readable`。

改它：

```bash
# 写 body 到无 BOM 的 UTF-8 文件
'{"security_entity":"anyone_can_view"}' > body.json

lark-cli drive permission.public patch --token X --type file --data "@body.json" --yes
```

⚠️ `--data` 用 `@文件` 时，文件必须是**无 BOM** 的 UTF-8，否则报 `--data invalid JSON format`。PowerShell 里 `Set-Content -Encoding UTF8` 会带 BOM，要用：

```powershell
[System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding($false)))
```

### 第 4 层：应用权限范围

开放平台 → 权限管理 → 搜 `drive:drive`：

- `drive:drive:readonly` —— 查看、评论、下载云空间所有文件（**免审权限，最小够用**）
- `drive:drive` —— 还带写权限，没必要

**两步都要做**：勾选后必须点右下角「确认开通权限」，然后去「版本管理与发布」创建版本 → 发布。只看勾选状态会误判。

但注意：**这一层往往不是根因**。第 3 层没解决时，开了全空间权限照样 403——因为文件级的安全设置优先级更高。

## 三、改完怎么验证

改完文件权限后，**再用应用身份直测一次下载**（脚本），看到 200 + 正确字节数才算真的好了。

不要看服务端数据库的 `last_error`——它有 25 分钟 token 缓存 + 定时任务周期，会滞后。要么手动点一次同步，要么等下一个 cron 周期。

## 四、别踩的坑

| 坑 | 后果 |
|---|---|
| 只看界面报错就下结论 | 报错文案（"请添加只读协作者"）会把人引向协作者，实际根因在安全设置 |
| 改完权限不发版本 | 权限不生效，白折腾 |
| 以为开了 `drive:drive` 就万事大吉 | 文件级安全设置优先，照样 403 |
| 用带 BOM 的 JSON 文件调 `--data @file` | `invalid JSON format`，排查方向跑偏 |
| 靠服务端数据库状态判断修没修好 | token 缓存 + cron 周期，滞后 25~30 分钟 |

## 五、一分钟决策树

```
应用读不了某文件
├─ 用 app_id+secret 直测下载
│  ├─ 200 → 服务端问题（缓存/代码），不是权限
│  └─ 403 → 继续
├─ 另找一个能读的文件对比
│  ├─ 能读的文件 security_entity = anyone_can_view
│  └─ 读不了的文件 security_entity = only_full_access  ← 改它
└─ 改完直测 200 → 收工；仍 403 → 再查应用权限范围
```

## 参考

- `references/permission-matrix.md` —— 字段取值含义、飞书权限点对照、tenant vs user token 的差异
- `scripts/probe-app-download.ps1` —— 用应用身份直测文件下载，一眼看出能不能读
- `scripts/fix-file-security.ps1` —— 批量把文件的 security_entity 改成 anyone_can_view
