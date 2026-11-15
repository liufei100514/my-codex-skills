# 妙搭平台契约

来源：真实项目 `.agents/skills/coding-guide|trigger-guide|authz-guide` + 线上发布证据。
违反这里的东西不会报错，会静默失效 —— 所以每次开工先扫一遍。

---

## 1. 工程骨架

```
app/
├── .spark/meta.json        # {"stack":"nestjs-react-fullstack","app_id":"app_xxx"} —— 应用身份
├── .agents/skills/         # 平台自带开发指南（coding / authz / trigger / user-identity / openapi / plugin / mcp / code-fix）
├── client/                 # React 19 前端（vite + tailwind + shadcn/ui）
│   ├── index.html
│   ├── public/
│   └── src/{index.tsx, app.tsx, api/index.ts, pages/, components/{ui,business-ui}/, hooks/, utils/}
├── server/                 # NestJS 10 后端（swc 编译）
│   ├── main.ts             # 入口，不可改
│   ├── app.module.ts       # 根模块，ViewModule 必须最后
│   ├── modules/<name>/     # controller / service / module / dto / automation
│   ├── database/schema.ts  # Drizzle 自动生成，禁止手改
│   └── common/             # filters / constants / interfaces / utils
├── shared/                 # 前后端共享类型与纯函数
├── scripts/                # dev.js / build.sh / prune-smart.js（平台生成，别改）
├── logs/                   # server.log / dev.log
└── .env.local              # lark-cli env-pull 下发（DATABASE_URL、CLIENT_BASE_PATH、MIAODA_*）
```

路径别名（`tsconfig.app.json` / `tsconfig.node.json` 已配好）：
`@client/*` → `client/*`，`@server/*` → `server/*`，`@shared/*` → `shared/*`，`@/*` → `client/src/*`。

---

## 2. 环境变量

`.env.local`（由 `lark-cli apps +env-pull` 拉取，不进 git）：

| 键 | 用途 |
|---|---|
| `SUDA_DATABASE_URL` | Drizzle 连接串（不要裸连，走注入实例） |
| `SUDA_WEBUSER` | 本地模拟登录身份的 JSON，dev server 拼成 `x-larkgw-suda-webuser` header |
| `MIAODA_APP_ID` / `app_id` | 应用 ID |
| `MIAODA_DEV_PLATFORM_BASE` | `__runtime__` 反代目标（没有它，平台 runtime 接口全不通） |
| `CLIENT_BASE_PATH` | 线上为 `/app/<app_id>`，本地裸跑可能为空 |
| `CLIENT_DEV_PORT` / `SERVER_PORT` | 本地两个端口（env-pull 不下发，冲突时自己改 `.env.local`） |

应用自己要用的密钥（如第三方 app_id / app_secret）由 `lark-cli` 写入 **dev 和 online 两套服务端环境**，值不回显、不进仓库、不写进代码。

`.env`（提交进仓库的那个）只放日志开关：`LOG_DIR` / `LOG_REQUEST_BODY` / `LOG_RESPONSE_BODY`。

---

## 3. 本地开发

### 启动

```bash
npm run dev          # 平台脚本：nest --watch + vite，两个进程
npm run dev:server   # 只起后端
npm run dev:client   # 只起前端
```

改过环境变量 → **必须重启整个 `npm run dev`**，只杀 `dev:server` 不会重载 `.env.local`。

### 入口只能走前端端口

```
http://localhost:<CLIENT_DEV_PORT><CLIENT_BASE_PATH>/...
```

- 前端 dev server 负责：serve 页面、反代 `/api/*` 到 NestJS、注入模拟登录 header、注入 `window.csrfToken`
- **直连 NestJS 端口**：header 丢失 → `req.userContext.userId === ''` → 依赖身份的查询/鉴权静默出错，接口还返回 200
- 端口被占：改 `.env.local` 里的 `CLIENT_DEV_PORT`，不要改 `vite.config.ts`

### CSRF（double-submit cookie）

所有 `/api/*` 要同时带：

```bash
curl -H 'Cookie: suda-csrf-token=x' \
     -H 'X-Suda-Csrf-Token: x' \
     http://localhost:<CLIENT_DEV_PORT><CLIENT_BASE_PATH>/api/xxx
```

值字面相等即可（浏览器侧零感知：后端 Set-Cookie + 注入 `window.csrfToken`，axios 拦截器自动带）。
403 是设计如此，别改中间件；依赖身份的接口用浏览器调试，别在 curl 里死磕。

### 平台 runtime 接口（`__runtime__`）

`api/v1/permissions/roles`、`api/v1/account/*`、`api/v1/studio/*`、`storage/*` 这些由平台网关承接，本地要靠 `.env.local` 里的 `MIAODA_DEV_PLATFORM_BASE` 反代过去。
没有这个变量 → POST 404、GET 落到 SPA fallback 返回 HTML。**先跑 `lark-cli apps +env-pull`，不要改代码兜底。**

### Windows 特有

标准 `npm run lint` 的子进程启动会报 EINVAL，直接跑等价命令：

```powershell
node node_modules/eslint/bin/eslint.js . --quiet
node node_modules/stylelint/bin/stylelint.mjs client/src/**/*.css --quiet
```

---

## 4. 构建与产物

`npm run build` → `scripts/build.sh` 六步：

1. `fullstack-cli action-plugin init`
2. `gen:openapi`（模板里通常是 `echo UNSUPPORTED`）
3. 清 `dist/`
4. 生成 API 路由 / 页面路由定义（`generate-api-routes`、`generate-page-routes`，`dist/routes.json`）
5. 并行 `build:server`（nest + swc）+ `build:client`（vite），`NODE_OPTIONS=--max-old-space-size=8192`
6. 产物整理（HTML 移到 `dist/dist/client`，server 用 `setBaseViewsDir` 同源 serve）+ `prune-smart.js` 裁剪 node_modules

注意：
- `nest-cli.json` 的 `deleteOutDir` 必须为 `false`，否则 `nest build` 会清掉第 4 步生成的路由文件
- `only_frontend_change=true` 可跳过 server 构建（纯前端改动省一半时间）

---

## 5. 数据库

| 事项 | 做法 |
|---|---|
| DDL | `lark-cli apps +db-execute --app app_xxx --sql "..."` |
| 类型生成 | `npm run gen:db-schema` → `server/database/schema.ts` |
| 连接 | `@Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase` |
| 事务 | **不支持** `db.transaction`，每个操作独立原子 |
| 手写 SQL | 禁止（除 Drizzle 的 `sql\`\`` 片段，如 `version + 1`、`= ANY(${ids}::uuid[])`） |

读数据的三个类型坑：

- `numeric` → 读出是 `string`，`Number(row.price)` 显式转
- `timestamptz` → service 内 `Date`，接口 JSON 化后变 string，shared 里声明 `string`
- `userProfile` 自定义类型 → TS 里就是 `string`，必须显式注解
- UUID 列 `inArray` 会报 `42809`，要用 `sql\`${table.id} = ANY(${ids}::uuid[])\``

结构变更顺序（错一步就整片 TS2339）：
`db-execute` → `gen:db-schema` → **重新读 schema.ts** → 再写业务代码。

---

## 6. 鉴权

- `@NeedLogin()` 加在控制器类上（整控制器要登录）或方法上（POST/PUT/PATCH/DELETE 必须加）
- 当前用户只从 `Req().userContext` 读：`{ userId, appId, tenantId?, env: 'preview'|'runtime', userName, userNameEn, userNameI18n }`
- 登录/注册/用户系统是内置的，**禁止自建**
- 用户展示/选择必须用 `components/business-ui/*`（UserSelect / UserDisplay / UserProfile / DepartmentSelect），禁止自拼头像一个 div

权限模式决策（详见 `authz-guide`）：

| 场景 | 模式 |
|---|---|
| 全公司可见、只分"能进/不能进" | 应用可见范围（Range）+ `@NeedLogin`，本项目就是这种 |
| 固定角色（管理员/员工） | 静态角色 `@Auth` |
| 角色可在线配置 | `AuthorizationSDK` 运行态角色 |
| 细到按钮/字段 | `@Can` + `<Can>` |

403 在业务 catch 里统一提示"无操作权限，请检查登录账号和应用访问范围"，不要到处判断。

---

## 7. 自动化任务（触发器）

四种：`cron`（无入参）、`record_change`（有入参）、`webhook`（有入参）、`feishu_approval`（有入参）。

```ts
// server/modules/<name>/<name>.automation.ts —— 每个模块只放这一个文件
@Automation()
export class CostAutomation {
  constructor(private readonly syncService: CostSyncService) {}
  @BindTrigger('cost-formula-refresh')     // 名字与平台上创建的触发器一致
  async refreshFormulas(): Promise<{ updated: number; checked: number }> {
    return this.syncService.syncAll();
  }
}
```

硬约束：

1. 平台 `CREATE` 出来的触发器默认 `inactive`，**创建 ≠ 会跑**；必须 `ENABLE` 后 `GET` 回读 `Active=true`
2. 触发器只投递到**已发布版本**；开发态（dev server）永远收不到 cron / record_change，不要靠改数据 + sleep 去等
3. `@BindTrigger` 改了必须重新发布才生效，没发布就说"发布后生效"
4. 业务逻辑写在 service 里，automation 只做接线 —— 这样开发态能用接口直接验证
5. cron 最小间隔受平台限制（本项目实测 `*/30 * * * *` 可创建，为避开整点拥挤改成 `7,37 * * * *`），时区显式写 `Asia/Shanghai`
6. 首轮要拿线上日志/回读数据验收（`trace_id`、`action_status=succeed`、`checked/updated` 计数）

cron 五段式：`minute hour day month week`，支持 `*` `,` `-` `/`，`L` 表示月末，`0` 是周日。

---

## 8. 发布

```bash
git commit -m "..."                                   # 必须已提交
lark-cli apps +release-create --app app_xxx            # 返回 release_id + status=publishing
lark-cli apps +release-status --app app_xxx            # 轮询到 finished
lark-cli apps +db-diff --app app_xxx --from dev --to main   # changes 必须 []
```

判据（本项目线上证据）：

```json
{ "status": "finished", "error_logs": [], "commit_id": "<40 位 sha>",
  "online_url": "https://<tenant>.feishuapp.com/app/app_xxx" }
```

- `publishing` 不算完成；`error_logs` 非空要贴出来
- `db-diff.changes` 非空 = 线上缺结构，必须在发布后补 DDL 再 diff 一次
- 管理入口：`https://miaoda.feishu.cn/app/app_xxx`
- 应用入口：`https://<tenant>.feishuapp.com/app/app_xxx`
- 可见范围（Range）默认收紧、需登录，不要为了省事放开成公开

---

## 9. 文件与目录红线

| 文件 | 规则 |
|---|---|
| `server/main.ts`、`client/src/index.tsx` | 不可改 |
| `server/modules/view/**` | 平台模板渲染，禁改 |
| `client/src/components/business-ui/**` | 平台保护，禁改 |
| `server/app.module.ts`、`client/src/app.tsx`、`client/src/api/index.ts` | 聚合文件，串行编辑 |
| `server/database/schema.ts` | 自动生成，只读 |
| `scripts/**`、`vite.config.ts` | 平台生成，禁改 |
| `.spark/meta.json` | 应用身份，禁改 |
