# 权限字段与令牌对照

## permission.public 各字段

`lark-cli drive +permission-get-setting --token X --type file` 返回的 `permission_public`：

| 字段 | 取值 | 含义 | 影响应用读取 |
|---|---|---|---|
| `link_share_entity` | `tenant_readable` / `tenant_editable` / `anyone_readable` / `closed` | 链接分享范围 | `tenant_readable` 及以上可读 |
| `security_entity` | `anyone_can_view` / `anyone_can_edit` / `only_full_access` | **谁能管理安全设置** | ⚠️ `only_full_access` 会挡住应用身份 |
| `copy_entity` | `anyone_can_view` / `anyone_can_edit` | 谁能复制 | 不影响下载 |
| `comment_entity` | `anyone_can_view` | 谁能评论 | 不影响 |
| `manage_collaborator_entity` | `collaborator_can_edit` / `collaborator_full_access` | 谁能管协作者 | 不影响读取 |
| `external_access_entity` | `open` / `closed` | 外部访问开关 | 不影响内部应用 |
| `share_entity` | `anyone` / `same_tenant` | 可分享对象 | 不影响 |

**关键**：`security_entity` 是唯一在 `tenant_readable` 前提下仍能挡住 `tenant_access_token` 的字段。

## 令牌类型差异

| 令牌 | 身份 | 权限来源 | 能读什么 |
|---|---|---|---|
| `tenant_access_token` | 应用自身 | 应用权限范围 + 文件级授权 | 被授权的文件；受 `security_entity` 限制 |
| `user_access_token` | 具体用户 | 该用户的协作者权限 | 该用户能看的文件；不看 `security_entity` 严格档位 |

> 如果业务允许，用 `user_access_token` 能绕过大部分文件级限制。但需要 OAuth 授权流程，且令牌 2 小时过期，服务端要能刷新。仅当 `tenant_access_token` 彻底走不通时考虑。

## 飞书云文档权限点

| 权限点 | 范围 | 是否免审 |
|---|---|---|
| `drive:drive:readonly` | 查看、评论、下载云空间所有文件 | ✅ 免审 |
| `drive:drive` | 上述 + 编辑、管理 | ✅ 免审 |
| `drive:drive.metadata:readonly` | 文件元数据 | ✅ |
| `drive:drive.search:readonly` | 搜索云文档 | ✅ |
| `drive:drive:version:readonly` | 文档版本只读 | ✅ |
| `drive:file:download` | 单文件下载（旧版权限点） | 视租户而定 |

最小够用组合：**只开 `drive:drive:readonly`**。

## 应用权限生效条件

```
开放平台勾选权限
   ↓ 必须点「确认开通权限」（不点等于没勾）
权限管理页显示「已开通」
   ↓ 必须「创建版本 + 发布」（版本详情里能看到权限变更）
版本状态「已发布」
   ↓ 数据范围：可访问的数据范围不能是「-」
生效
```

实际经验：即使走完全流程，**文件级 `security_entity` 仍可能优先否决**。所以排障顺序应该把文件级放前面。

## 错误码对照

| HTTP / code | 含义 | 下一步 |
|---|---|---|
| 403（download 接口） | 应用无该文件读取权 | 查 `security_entity` |
| 99991668 | user access token not support（接口只收 tenant token） | 换 `tenant_access_token` |
| 1063001 Invalid parameter | 参数格式错，常见于 `--member-type appid` | 应用不能用 appid 加协作者 |
| 99991663 | tenant token 无效/过期 | 重新取 token |

## lark-cli 参数坑

| 场景 | 正确写法 | 错误写法 |
|---|---|---|
| JSON body 传文件 | `--data "@C:\path\body.json"` | `--data '{"a":1}'`（PowerShell 引号被吃） |
| body 文件编码 | 无 BOM UTF-8 | `Set-Content -Encoding UTF8`（带 BOM 报 invalid format） |
| query 参数 | 用 typed 命令的 flag（如 `--token`、`--type`） | `lark-cli api GET 'path?x=1'`（拒绝 query string） |
