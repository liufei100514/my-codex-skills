# 把 ERP 价格接进应用（价格三层 + 定时同步）

配套技能：`kingdee-k3cloud-readonly`（ERP 侧怎么登录、取数、字段坑）。
这里只讲**应用侧**：怎么存、怎么同步、怎么不把人工修正冲掉。

---

## 1. 价格三层：为什么不能只加一个 `price` 字段

最简单做法是同步时直接 `UPDATE price = erp_price`。跑一周就出事：业务方手工修正过的价被静默覆盖，第二次就没人敢改价了。

正确结构：

```
erp_price      ERP 同步来的原值（只读，每次同步覆盖，永远可用于对账）
price          当前生效价（参与计算，界面显示的就是它）
price_locked   true = 人工锁定，同步只更新 erp_price，不动 price
price_source   manual | erp | seed（这条生效价从哪来）
```

DDL：

```sql
ALTER TABLE cost_materials ADD COLUMN IF NOT EXISTS erp_price numeric(18,6);
ALTER TABLE cost_materials ADD COLUMN IF NOT EXISTS erp_synced_at timestamptz;
ALTER TABLE cost_materials ADD COLUMN IF NOT EXISTS price_locked boolean NOT NULL DEFAULT false;
ALTER TABLE cost_materials ADD COLUMN IF NOT EXISTS price_source varchar(20) NOT NULL DEFAULT 'manual';
ALTER TABLE cost_materials ADD CONSTRAINT cost_materials_price_source_check
  CHECK (price_source IN ('manual','erp','seed'));
```

存量数据先标 `seed`（来源是初始导入），且不锁定 —— 接上 ERP 后自动跟随。

---

## 2. 同步逻辑（关键就 20 行）

```ts
for (const code of matchedCodes) {
  const price = priceByCode.get(code)!;

  // ① ERP 原值：所有行都写（对账用）
  await db.update(costMaterials)
    .set({ erpPrice: String(price), erpSyncedAt: now, updatedAt: now })
    .where(eq(costMaterials.erpCode, code));

  // ② 未锁定的行：生效价跟随 ERP
  const unlocked = await db.update(costMaterials)
    .set({ price: String(price), priceSource: 'erp', updatedAt: now,
           version: sql`${costMaterials.version} + 1` })
    .where(and(eq(costMaterials.erpCode, code), eq(costMaterials.priceLocked, false)))
    .returning({ id: costMaterials.id });
  updated += unlocked.length;

  // ③ 锁定的行：只计数，不动 price
  skippedLocked += (await db.select({ id: costMaterials.id }).from(costMaterials)
    .where(and(eq(costMaterials.erpCode, code), eq(costMaterials.priceLocked, true)))).length;
}
```

人工改价时顺手锁定：

```ts
if (data.priceLocked === true)  { patch.priceLocked = true;  patch.priceSource = 'manual'; }
else if (data.priceLocked === false) { patch.priceLocked = false; }   // 解锁，恢复跟随
```

---

## 3. 匹配规则

```
优先 erp_code 精确匹配（NFKC + 去空格 + 大写）
没有 erp_code 的 → 退化用 code 匹配
ERP 有、本地没有的 → 进 unmatched，不自动建
本地有、ERP 没返回价的 → 保持原值，记一条"ERP 无采购价"
```

**不自动创建**是刻意的：价格库一旦被 ERP 脏数据填满，"待补价"统计就废了，业务方再也判断不出哪些真的缺。

实测覆盖率参考（116 条原料）：91 条填了 `erp_code` → 46 个唯一编码 → 45 个能在 ERP 匹配 → 39 个有采购历史价。剩下 25 条没有 `erp_code` 的，是**自产母胶**（不是外购料，ERP 里本来就没有采购价），保持手工价是对的。

---

## 4. 同步状态表（单行）

```sql
CREATE TABLE IF NOT EXISTS cost_erp_sync (
  id varchar(40) PRIMARY KEY DEFAULT 'erp',
  last_checked_at timestamptz,
  last_success_at timestamptz,
  last_error text NOT NULL DEFAULT '',
  fetched_count integer NOT NULL DEFAULT 0,
  updated_count integer NOT NULL DEFAULT 0,
  skipped_locked integer NOT NULL DEFAULT 0,
  unmatched jsonb NOT NULL DEFAULT '[]',
  version integer NOT NULL DEFAULT 1,
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

`last_success_at` 和 `last_checked_at` 分开：前者是数据新鲜度，后者是任务心跳。失败时只更新 `last_error` 和 `checked_at`，**保留上次成功时间**。

---

## 5. 触发器

```ts
@Automation()
export class CostAutomation {
  @BindTrigger('cost-erp-price-refresh')
  async refreshErpPrices() {
    if (!this.erpSyncService.isConfigured()) return { fetched: 0, updated: 0, skipped: true };
    const r = await this.erpSyncService.syncPrices();
    return { fetched: r.fetched, updated: r.updated, skipped: false };
  }
}
```

未配置凭据时**静默跳过**，不要每小时报一次错 —— 会让真实故障淹在噪声里。

cron 建议每小时一次（`23 * * * *`），和配方同步（`7,37 * * * *`）错开。

---

## 6. 云端连通性怎么验证（最容易卡住的地方）

本地能连 ERP，不代表**云端服务端也能连**（出口 IP、白名单、DNS 都可能不同）。这是整个方案最大的未知数，必须尽早验证。

最快的验证套路：

1. 把触发器 cron 临时改成"下 1~2 分钟"的整点分钟数，例如当前 12:21 → `24 * * * *`
2. 等 2 分钟 + 60 秒
3. 直接查同步状态表：

```sql
SELECT last_checked_at, last_success_at, last_error, fetched_count, updated_count, skipped_locked FROM cost_erp_sync;
```

看到 `last_success_at` 有值、`last_error` 为空、计数合理，说明**云端能连 ERP、凭据有效、代码跑通**，三个问题一次验证完。

4. 验证完把 cron 改回正式值

这一步比在本地写多少测试都值 —— 它一次性排掉"云端出不去"和"凭据不对"两种最坏情况。

---

## 7. 前端要显示什么

| 位置 | 展示 |
|---|---|
| 原料行 | 价格 + 来源标签（`ERP` / `已锁定`） |
| 缺价行 | "待补价" + "ERP 参考 ¥x"（ERP 有价但没收上去时，人一眼能看出来） |
| 编辑弹窗 | ERP 参考价 + 与生效价的差额提示 + 锁定开关（默认新增时锁定） |
| 关联页 | 上次成功时间、命中/更新/锁定跳过计数、未匹配数量、手动同步按钮 |

锁定的文案要写清后果：`已锁定：不跟随 ERP 自动更新` / `未锁定：下次同步会用 ERP 价覆盖`。

---

## 8. 多环境 DDL 的正确路径

多环境应用里，**online 分支禁止 DDL**：

```
{"code":4000001,"message":"forbid ddl/dcl operation in online env",
 "hint":"the online branch of a multi-env app forbids DDL/DCL.
         Run the DDL against dev, then publish it with
         lark-cli apps +db-env-migrate --app-id <app_id>"}
```

正确顺序：

```bash
# 1. dev 执行 DDL
lark-cli apps +db-execute --app-id <app_id> --environment dev --file migration.sql --yes
# 2. 预览结构差异
lark-cli apps +db-env-diff --app-id <app_id>
# 3. 发布到 online（不可逆）
lark-cli apps +db-env-migrate --app-id <app_id> --yes
# 4. 迁移只搬结构，DML 要单独对 online 跑一遍
lark-cli apps +db-execute --app-id <app_id> --environment online --file data-fix.sql --yes
# 5. 确认差异归零
lark-cli apps +db-env-diff --app-id <app_id>   # changes 应为 []
```

**别忘第 4 步**：`db-env-migrate` 只迁移 schema，`UPDATE` 这类 DML 不会跟过去。

---

## 9. 落地前必须和业务方确认的两件事

1. **取价口径**：最近一次成交价 / 近 N 次加权 / 价目表。三者在成本上差得不是一点半点。
2. **偏离容忍度**：ERP 价和当前价差多少要提示而不是直接覆盖（建议 ±10% 标黄）。

实测一次性改价的幅度供参考：90 行里有 11 行变动超 ±10%，最大 -20.3%（14.5→11.55）和 +18.2%（33→39）。**上线头一天一定要把变动清单拉出来给业务方过一遍**，不然成本数字突变没人能解释。
