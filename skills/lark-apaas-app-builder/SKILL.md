---
name: lark-apaas-app-builder
description: 用飞书妙搭（Lark aPaaS / miaoda / lark-apaas）全栈模板搭一个企业业务应用，或接手改造既有的妙搭项目。覆盖：shared 类型契约先行、Drizzle + 飞书 Postgres 建表、NestJS 模块、React 移动优先页面、飞书 Drive 表格外部数据同步、cron 自动化任务、lark-cli 发布与 DB diff 校验、乐观锁与审计触发器。当用户要在妙搭里做核算/台账/看板/审批单类应用，或对已有 app_xxx 项目说"加个功能/发布/上线/改成定时同步"时使用。
whenToUse: 用户提到妙搭、飞书应用、miaoda、lark-apaas、app_ 开头的应用 ID、发布上线、定时同步、把飞书表格数据接进应用；或者工作目录里存在 .spark/meta.json（stack=nestjs-react-fullstack）需要加功能、改页面、排查构建/发布问题。
---

# 妙搭全栈应用：搭建与改造

这套做法来自一个真实上线的生产应用（硅基材料成本核算台，166 条配方、5 张表、30 分钟云端同步、166 个型号的成本核算），把里面的**平台契约、数据流、验收动作**抽成可复用流程。

先读 `references/platform-contract.md` 再动手；那是平台的地基，违反它的地方不会报错，只会静默失效。

---

## 一、先判定：这确实是妙搭项目

三个特征同时命中才是：

| 判据 | 位置 | 说明 |
|---|---|---|
| `.spark/meta.json` | 项目根 `app/` | `{"stack":"nestjs-react-fullstack","app_id":"app_xxx"}` |
| `.agents/skills/` | 项目根 | 平台自带指南：coding-guide / authz-guide / trigger-guide / user-identity / openapi-guide / plugin-guide / mcp-guide / code-fix |
| `@lark-apaas/*` 依赖 | `package.json` | `fullstack-nestjs-core`（服务端）、`client-toolkit`（前端）、`fullstack-presets`（构建） |

命中后**开工第一件事**是读 `.agents/skills/coding-guide/SKILL.md`（771 行，平台规范的真实来源）和目标项目已有的 `shared/api.interface.ts` + `server/database/schema.ts`。不要凭记忆写字段名。

发布/DB/触发器/环境变量都走 `lark-cli`（飞书官方 CLI，输出统一形如 `{ok, identity, data}`）。

---

## 二、五步搭建流程（顺序不能颠倒）

### 第 1 步：写契约 `shared/api.interface.ts`

**永远先写类型，再写实现。** 前后端都从这个文件导入，禁止各写一套。

```ts
// 1) 固定取值定义一次：as const 数组 + 联合类型 + 守卫 + 中文标签
export const SCOPES = ['precipitated', 'fumed'] as const;
export type Scope = (typeof SCOPES)[number];
export const isScope = (v: string): v is Scope => (SCOPES as readonly string[]).includes(v);
export const SCOPE_LABELS: Record<Scope, string> = { precipitated: '沉淀胶', fumed: '气相胶' };

// 2) 实体 / 请求 / 响应
export interface Material { id: string; code: string; price: number | null; version: number; updatedAt: string }
export interface MaterialUpdate { version: number; price: number | null; notes: string }
export interface DashboardResponse { materials: Material[]; serverTime: string; syncMode: SyncState }
```

规矩：
- 属性一律 camelCase；数据库的 snake_case **不许**泄漏到接口类型
- 数字型 `numeric` 在 TS 里是 `number | null`，`timestamptz` 在接口里是 `string`（跨网络 JSON 化）
- shared **禁止**反向 import `@server/*`、`@client/*`
- 缺数据用 `null` 表达，**不要用 0 冒充**（这是业务正确性的分水岭，见第五节）

### 第 2 步：建表（DDL → 重新生成 schema → 立刻重读）

```bash
# 1) 用 lark-cli 在 dev 分支执行 DDL（表、索引、CHECK、触发器）
lark-cli apps +db-execute --app app_xxx --sql "CREATE TABLE ..."
# 2) 重新生成 Drizzle schema（schema.ts 是自动生成文件，禁止手改）
npm run gen:db-schema
# 3) 立刻重新读一遍 server/database/schema.ts —— 字段名/类型以它为准
```

表设计三条固定做法（成本核算台实践证明值得抄）：
- 每张业务表带 `version integer default 1`、`updated_by varchar(80)`、`updated_at timestamptz default now()`
- 唯一天然键用 unique index 兜底（`(scope, code)`、`(scope, model_key)`），而不是靠代码判断
- 审计用**数据库触发器**记录 before/after JSON，而不是在 service 里手写日志表

```sql
CREATE OR REPLACE FUNCTION capture_change() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  INSERT INTO audit(entity_type, entity_id, actor, before, after)
  VALUES (TG_TABLE_NAME, NEW.id, NEW.updated_by, to_jsonb(OLD), to_jsonb(NEW));
  RETURN NEW;
END; $f$;
CREATE TRIGGER material_audit AFTER UPDATE ON materials FOR EACH ROW EXECUTE FUNCTION capture_change();
```

### 第 3 步：后端模块 `server/modules/<name>/`

四个文件起步：`<name>.module.ts` / `.controller.ts` / `.service.ts` / `.dto.ts`（有定时任务再加 `.automation.ts`）。

```ts
@Controller('api/cost')
@NeedLogin()                                   // 整个控制器要登录
export class CostController {
  constructor(private readonly service: CostService) {}

  @Get('dashboard') dashboard() { return this.service.dashboard(); }

  @Patch('materials/:id')
  updateMaterial(@Param('id') id: string, @Body() body: MaterialUpdateDto, @Req() req: Request) {
    return this.service.updateMaterial(id, body, req.userContext.userId!);   // 用户身份只从 req 取
  }
}
```

- `main.ts` / `index.tsx` / `components/business-ui/**` 是平台保护文件，**不改**
- 新 module 注册进 `server/app.module.ts`，`ViewModule` 必须留在 `imports` 最后一项
- Service 里抛业务异常（`BadRequestException`/`ConflictException`），Controller 不 try/catch，交给全局过滤器
- 数据访问只用注入的 Drizzle：`@Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase`；**禁止** `db.transaction`、禁止手写 SQL 字符串

细节见 `references/backend-patterns.md`。

### 第 4 步：前端页面 `client/src/pages/<name>/`

移动优先、单页多页签（本项目用底部三页签：成本 / 原料 / 关联，路由 `/`、`/materials`、`/sources` 指向同一页面组件，按 `location.pathname` 切页），比堆多页更适合现场扫码用。

```ts
// client/src/api/index.ts —— 唯一请求出口
const request = async <T>(method: string, path: string, data?: unknown): Promise<T> => {
  const r = await axiosForBackend({ url: `/api/cost/${path}`, method, data });  // 函数式调用，不是实例方法
  if (r.status >= 400) throw new Error(r.data?.error?.message ?? '请求失败，请重试');
  return r.data;
};

// pages/<name>/use-<name>.ts —— 读写封装成 hook
export const useData = () => useQuery({ queryKey: ['dash'], queryFn: getDashboard, refetchInterval: 15000 });
export const useSave = (done?: () => void) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (task: () => Promise<unknown>) => task(),
    retry: false,                                  // 平台默认会重发写请求 → 必须关
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['dash'] }); toast.success('已保存'); done?.(); },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });
};
```

- 禁止 `fetch`、禁止 `axiosForBackend.get()` 这类实例方法、禁止 mock 数据
- 三态必做：骨架屏（首屏远程数据）/ 空态 / 错误态带"重试"
- 数字与时间统一走格式化函数：`money(v, 4)` 返回 `待完善` 而不是 `0`，`dateTime()` 固定 `Asia/Shanghai`
- 纯图标按钮加 `aria-label`，选中态用 `aria-pressed`/`aria-checked`

细节见 `references/frontend-patterns.md`。

### 第 5 步：发布（三步，缺一不可）

```bash
git add -A && git commit -m "..."          # 提交后才能发布
lark-cli apps +release-create --app app_xxx
lark-cli apps +release-status --app app_xxx   # 轮询到 status=finished、error_logs=[]
lark-cli apps +db-diff --app app_xxx --from dev --to main   # changes 必须为 []
```

三条判定：
- `release-status` 要看到 `status: finished` + `error_logs: []` + 准确 `commit_id`，不能只看 "已提交"
- `db-diff` 的 `changes` 必须是 `[]`；不为空说明结构没同步，线上会缺列
- 发布是**异步**的，`publishing` 状态不算完成

完整清单见 `references/delivery-checklist.md`。

---

## 三、最容易踩死的 10 个点

1. **三个聚合文件必须串行改**：`server/app.module.ts`、`client/src/app.tsx`、`client/src/api/index.ts`。并行改会互相覆盖。
2. **`schema.ts` 是生成物**：改表后不重跑 `gen:db-schema` 并重读，会出现整片 TS2339（字段不存在）。
3. **禁止事务**：平台不支持 `db.transaction`，每个写操作自己保证幂等/一致。
4. **`shared` 不许反向引用**：`@server/*`、`@client/*` 都不能出现在 shared 里。
5. **`import type` 只导类型**：导 const 会被擦除成 `undefined`，运行时才炸。
6. **时间戳跨网络变 string**：service 内是 `Date`，接口出去是 ISO 字符串，前端要 `new Date(v)`。
7. **`numeric` 读出是 string**：`Number(row.price)` 显式转换，别直接比较。
8. **本地 dev 只能走前端端口**：`http://localhost:<CLIENT_DEV_PORT><CLIENT_BASE_PATH>/api/...`，直连 NestJS 端口会丢用户身份（`req.userContext.userId === ''`），接口还返回 200，极难查。
9. **curl 打 `/api/*` 要带双提交 CSRF**：`Cookie: suda-csrf-token=x` + `X-Suda-Csrf-Token: x`，否则 403。403 不是业务 bug，别去改 csrf 中间件。
10. **运行时文件系统只读**：生产 `process.cwd()` 是只读部署目录，临时文件一律写 `/tmp` 下的独立目录；启动钩子里不要下载/同步/建表。

---

## 四、三个值得直接抄的范式

### 范式 A：乐观锁 + 409（多人同时改价格）

```ts
const rows = await this.db.update(materials)
  .set({ price: String(price), updatedBy: actor, updatedAt: new Date(), version: sql`${materials.version} + 1` })
  .where(and(eq(materials.id, id), eq(materials.version, input.version)))
  .returning({ id: materials.id });
if (!rows.length) throw new ConflictException('该原料已被修改，请刷新后重试，当前输入尚未保存');
```

前端把 `version` 原样回传；409 时提示"刷新后重试"，不要静默覆盖别人改的值。

### 范式 B：计算引擎放 shared，前后端同一份代码

```ts
// shared/engine.ts —— 纯函数，不依赖 db / axios / DOM
export function calculate(formula: Formula, prices: Price[], setting: Params | null): Result {
  const issues: string[] = [];
  const missing: string[] = [];
  // ...
  const output = validFactor ? inputKg / factor! : null;         // 参数缺失 → null，不是 0
  if (!feesReady) issues.push('待设置加工费用');
  return { inputKg, outputKg: output, totalCostPerTon, issues, missingMaterials, warnings, lines };
}
```

后端拿它做权威结果，前端拿它做**输入即时预览**（用户改一个数，弹窗里成本立刻变），两边算法不会漂。

### 范式 C：外部数据源同步（飞书 Drive 表格 → 应用内）

完整实现见 `references/external-sync.md`，骨架是：
```
tenant_access_token（内存缓存，提前 120s 过期）
  → 下载文件（超时 18s、上限 12MB）
  → 校验 PK 魔数（拿到的是不是 xlsx）
  → sha256 与 current_hash 比对，没变就只更新 checked_at
  → 解析（缺表/超规模/单元格错误 → 抛错并保留上次成功数据）
  → 新条目的空壳补齐（price = null，绝不猜值）
  → 写回 formulas + hash + last_success_at，version 乐观锁
```

三条铁律：
- **失败保留上次成功快照**，`last_error` 落库并在界面上显式提示，不静默
- **新增数据只补空壳**（缺价/缺参数标"待完善"），不自动套用相近型号
- **触发器只服务已发布版本**：`CREATE` 默认 inactive，必须 `ENABLE` 后 `GET` 回读 `Active=true`，再看首轮线上日志

### 范式 D：ERP 价格同步（金蝶/用友 → 应用内主数据）

完整实现见 `references/erp-integration.md`，ERP 侧接口见配套技能 `kingdee-k3cloud-readonly`。

最小可复用结构：

```
适配器（登录 + 会话 + 分页 + 去重 + 单位过滤）
   → 同步服务（按 erp_code 匹配 → 三层写回 → 记状态）
   → 触发器（每小时，未配凭据时静默跳过）
```

三个不能省的设计：
- **价格三层**：`erp_price`（原值，永远留） / `price`（生效值） / `price_locked`（人工锁定）+ `price_source`（来源）。直接覆盖人工价，第二次就没人敢改价。
- **ERP 有、本地没有的物料不自动建**，进 `unmatched` 让人判断。
- **云端连通性用"临时 cron 调到下一分钟 + 查状态表"验证**，一次排掉"云端出不去"和"凭据不对"。

---

## 五、缺数据的产品化处理（这条最容易被做错）

成本类应用一旦"缺价按 0 算"，用户就会拿错数字去做报价。正确姿势：

| 状态 | 表达 | 界面 |
|---|---|---|
| 原料没价格 | `price: null` | 卡片显示"待补价"，成本显示"待完善" |
| 参数没配（耗用系数/加工费） | `feesConfigured: false` | 卡片显示"去完善" |
| 数据有冲突（同名型号/重复价格） | `issues[]` / `warnings[]` | 黄色提示 + 源表行号，**不阻断** |
| 真异常（用量为 0/负数/解析失败） | `issues[]` | 红色，阻断核算 |

同名型号这类"业务上允许"的情况做 **warning 不阻断**；只有会导致算错的（缺价、除零、无效用量）才阻断。这条口径要和业务方确认后写进代码注释和状态文档。

---

## 六、排查路径（按顺序，别乱跳）

1. 页面白屏/接口 404 → 查 `@Controller('api/xxx')` 前缀、module 是否注册、静态路由是否在 `/:id` 前
2. 接口返回 HTML → 撞上了 SPA fallback，路径写错或 module 没注册
3. TS2339 一片红 → `schema.ts` 没重新生成 / 没重读
4. 后端启动即崩 `Nest can't resolve dependencies` → 查构造函数里的空参 `@Inject()`，别先改 Module 的 imports
5. 用户身份为空 → 是不是直连了 NestJS 端口（应走前端端口）
6. 触发器不跑 → 没发布 / 没 ENABLE / 看的是开发态（开发态永远收不到 cron）
7. 发布后线上缺数据 → 跑 `db-diff`，看是不是结构没同步

---

## 七、交付时一并产出（不是可选）

- `analysis/` 下每个关键动作一份证据 JSON（发布状态、db-diff、触发器回读、同步状态）
- `backups/<时间点>/` 导入前后五张表的导出 + `manifest.json` 记录行数与哈希
- `private/` 放密钥（`.env` 不进 git，`lark-cli env-pull` 拉平台配置）
- 根目录一份"搭建状态与恢复.md"：当前 release id、commit、入口 URL、数据规模、待完善项、本地恢复命令

---

## 参考文件

| 文件 | 什么时候读 |
|---|---|
| `references/platform-contract.md` | 开工前必读；不确定平台允许什么/禁止什么 |
| `references/backend-patterns.md` | 写 module/controller/service/dto、乐观锁、错误码 |
| `references/frontend-patterns.md` | 写页面、hook、弹窗、空态、移动端布局 |
| `references/external-sync.md` | 要接飞书表格/外部 API 做同步 |
| `references/erp-integration.md` | 要把 ERP（金蝶/用友）价格或数量接进应用；价格分层与定时同步 |
| `references/cost-engine-case.md` | 做配方/工艺→成本这类核算应用；需要具体公式、算例、缺数据口径 |
| `references/delivery-checklist.md` | 每次发布前后照着走一遍 |
