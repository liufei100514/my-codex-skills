# 外部数据源同步（飞书 Drive 表格 → 应用内）

适用：配方/价目/台账这类**由业务方在飞书表格里维护、应用内只读**的数据。
成本核算台的实现（166 条配方、两份源表、30 分钟云端兜底）已验证可生产使用，整套逻辑可照搬。

---

## 1. 总体数据流

```
业务方在飞书表格里维护
        │
        ▼
[触发器 cron 30min] ──→ syncAll()
        │                   ├─ getToken()            租户令牌，内存缓存，提前 120s 过期
        │                   ├─ download(fileToken)    18s 超时 / 12MB 上限
        │                   ├─ 校验 PK 魔数           拿到的是不是真 xlsx
        │                   ├─ sha256 与 current_hash 比对 → 没变就只更新 checked_at
        │                   ├─ 解析（结构化容错）
        │                   ├─ 新条目补空壳（price=null），绝不猜值
        │                   └─ 写回 formulas + hash + last_success_at（乐观锁 version）
        ▼
界面：「关联」页显示最近成功读取时间、错误、可手动点"立即检查"
```

用户手动点"立即检查"走同一个 `syncAll()`，不要写第二套。

---

## 2. 令牌：只缓存内存，不进库

```ts
private cachedToken: { value: string; expiresAt: number } | null = null;

private async getToken(): Promise<string> {
  if (this.cachedToken && this.cachedToken.expiresAt > Date.now()) return this.cachedToken.value;
  const res = await firstValueFrom(this.http.post<TokenResponse>(
    'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
    { app_id: process.env.FEISHU_SOURCE_APP_ID, app_secret: process.env.FEISHU_SOURCE_APP_SECRET },
    { timeout: 10000 },
  ));
  if (res.data.code !== 0 || !res.data.tenant_access_token) throw new Error('飞书应用认证失败');
  this.cachedToken = { value: res.data.tenant_access_token, expiresAt: Date.now() + Math.max(0, (res.data.expire ?? 0) - 120) * 1000 };
  return this.cachedToken.value;
}
```

- 凭据只从**服务端环境**读（`lark-cli` 写进 dev/online 两套环境），不进代码、不进仓库、不回显
- 用**专用飞书应用**（只读该文件的权限），不要复用个人或 CLI 的宽授权凭据
- 令牌失效（`code=99991672`）时把 `last_error` 写成人话，界面上直接告诉用户去检查哪一项权限

---

## 3. 下载 + 幂等判定

```ts
const res = await firstValueFrom(this.http.get<ArrayBuffer>(
  `https://open.feishu.cn/open-apis/drive/v1/files/${encodeURIComponent(source.driveToken)}/download`,
  { headers: { Authorization: `Bearer ${token}` }, responseType: 'arraybuffer',
    timeout: 18000, maxContentLength: 12 * 1024 * 1024 },
));
const buffer = Buffer.from(res.data);

// 1) 魔数校验：不是 zip(PK) 就说明拿到的是 JSON 错误体或空文件
if (buffer[0] !== 0x50 || buffer[1] !== 0x4b) throw new Error('未能取得 Excel 文件，请检查飞书文件读取权限');

// 2) 哈希幂等：没变只更新 checked_at / last_success_at
const hash = createHash('sha256').update(buffer).digest('hex');
if (hash === source.currentHash) { /* 只更新检查时间，直接 return */ }
```

- 只读场景永远用「哈希比对」而不是「时间戳/文件大小」判断变更
- 保留 `last_success_at` 和 `checked_at` 两个字段：前者是数据新鲜度，后者是任务心跳，界面上分别展示

---

## 4. 解析：宁可失败，不要半截数据

```ts
export function parseFormulaWorkbook(workbook: Workbook, scope: CostScope): Formula[] {
  const sheet = workbook.getWorksheet('配方汇总表');
  if (!sheet) throw new Error('源文件缺少"配方汇总表"，保留上次成功配方');
  if (sheet.rowCount > 5000 || sheet.columnCount > 256) throw new Error('源表规模超过当前读取范围');

  // 表头在第 3 行、第 5 列开始：业务表结构必须显式写死并注释，不要猜
  // 单元格值可能带单位（"12.5kg"/"500g"），统一换算成 kg
  // 任一单元格是 Excel 错误值（#REF!）→ 抛错，整表不落地
}
```

三条原则：

1. **结构写死 + 注释**：表头从第几行第几列开始、哪列是型号、哪些列是原料，都写进解析器并在注释里说明依据（来自哪份源表）
2. **任何异常整表拒绝**：少一个表头、超大、有错误单元格，都 `throw`。因为**部分导入比不导入更危险**（用户会拿缺料的价格去报价）
3. **失败保留上次成功快照**：错误写 `last_error`，配方 JSON 原封不动，界面上标"仍保留上次成功配方"

```ts
catch (error: unknown) {
  const message = isAxiosError(error)
    ? feishuReadError(error.response?.status, error.response?.data)
    : error instanceof Error ? error.message : '飞书读取失败，请检查文件授权与网络';
  failures.push(`${source.name}：${message}`);
  await this.db.update(costSources).set({ checkedAt, lastError: message })   // 只写错误，不动 formulas
    .where(and(eq(costSources.id, source.id), eq(costSources.version, source.version)));
}
```

---

## 5. 新条目补空壳，绝不猜值

同步发现新配方/新原料时：

```ts
// 新配方 → 建一条空参数行（系数/费用/售价全为空）
await this.db.insert(costSettings).values({
  id: `${source.id}:${formula.modelKey}`, scope: source.id, modelKey: formula.modelKey,
  productModel: formula.productModel, lossMultiplier: null, fees: [],
  feesConfigured: false, sellingPrice: null,
  notes: '飞书新增配方，请补充耗用系数和加工费用。', updatedBy: 'source-sync',
}).onConflictDoNothing();

// 新原料 → 建一条缺价行，分类挂"未分类"
await this.db.insert(costMaterials).values({
  id: sha256(`${source.id}:${code}`).slice(0, 24), scope: source.id, code,
  displayName: code, categoryId: 'uncategorized', price: null,
  notes: '飞书新增原料，请补充单价。', updatedBy: 'source-sync',
}).onConflictDoNothing();
```

**禁止**：按名字相似度自动匹配旧型号参数、按同类均值补价、用 0 代替 null。
新增量在界面上明确列出"待完善 N 项"，让业务方逐个补 —— 这是本类应用的信任基础。

---

## 6. 状态机（前端直接展示这个）

```ts
export const CLOUD_SYNC_STATES = ['authorization_required', 'cloud_configured', 'cloud_ready', 'cloud_error'] as const;
export const SYNC_STATE_LABELS = {
  authorization_required: '配方快照已载入',   // 没配凭据，只有历史快照
  cloud_configured: '云端待验证',             // 配了凭据，还没成功跑过一次
  cloud_ready: '云端已连接',                  // 最近一轮成功
  cloud_error: '云端连接异常',                // 有 source 带 last_error
};
```

```ts
syncMode: !appId || !appSecret ? 'authorization_required'
        : sources.some((s) => !!s.lastError) ? 'cloud_error'
        : sources.length > 0 && sources.every((s) => s.updatedBy === 'source-sync') ? 'cloud_ready'
        : 'cloud_configured',
```

用 `updatedBy === 'source-sync'` 判断"数据是云端同步来的"而不是种子导入的 —— 这个字段顺便成了数据来源溯源。

---

## 7. 错误码 → 人话

```ts
export function feishuReadError(status: number | undefined, data: unknown): string {
  const code = ...;                                        // 从响应体取 code
  if (code === 99991672) return '飞书应用的下载文件权限尚未生效，请检查应用身份权限并发布';
  if (status === 403) return '飞书应用没有该源文件的读取权限，请添加只读协作者';
  if (status === 429) return '飞书请求频率受限，请稍后重试';
  return typeof code === 'number' ? `飞书读取失败（错误码 ${code}），保留上次成功配方`
    : '飞书读取失败，请检查文件授权与网络';
}
```

原则：错误文案必须**指向具体动作**（去开权限 / 去加协作者 / 稍后重试），不要"同步失败"四个字。

---

## 8. 触发节奏

| 通道 | 用途 | 注意 |
|---|---|---|
| cron 触发器（30 分钟） | 兜底自动同步 | 平台最小间隔受限；用 `7,37 * * * *` 错开整点；必须 ENABLE + GET 回读 |
| 界面手动按钮 | 业务方改完表想立刻生效 | 调同一个 `syncAll()`，返回 `{checked, updated}` 给 toast |
| 保存后立即重算 | 用户在应用内改价 | **不需要同步**，直接重算即可（这是最容易被过度设计的地方） |

不要为了"实时"去接在线文档编辑事件 —— 用云端轮询 + 手动按钮已经被业务方接受，且比事件通道稳。

---

## 9. 首次上线顺序

1. 建表（`cost_sources` 存 driveToken / currentHash / lastError / formulas）
2. 用一次性脚本导入历史快照（`analysis/seed.json`），`updatedBy` 标成种子来源
3. 备份：`backups/<时间点>/` 五张表导出 + manifest（行数 + 哈希）
4. 配凭据 → 手动点一次同步 → 核对 `checked/updated` 与配方条数
5. 建触发器 → ENABLE → GET 回读 → 等首轮 cron → 看线上日志 + 回读数据
6. 全程把每一步的 JSON 证据落到 `analysis/`
