# 系统地图

## 数据流

```
飞书配方 XLSX（沉淀/气相/液体）
   │  tenant_access_token 下载 → 解析 → 哈希比对
   ▼
cost_formulas ──────────────┐
                            │
金蝶 K3Cloud 采购订单         ├──→ 核算引擎 ──→ 配方成本 / 毛利率
   │  ExecuteBillQuery       │      ↑
   ▼                        │      │
cost_materials (erp_price)  │   cost_parameters
   │  三层价格写回           │   （耗用系数、加工费、售价）
   ▼                        │
cost_erp_sync（同步记账）    │
                            │
cost_categories ────────────┘
```

页面消费：配方关联页、成本核算页、原料价格页。

## 表结构

| 表 | 作用 | 关键字段 |
|---|---|---|
| `cost_sources` | 配方数据源登记 | `id`(precipitated/fumed/liquid)、`drive_token`、`last_error`、`last_success_at`、`checked_at` |
| `cost_formulas` | 解析后的配方 | 型号、产品类别、组分、用量、源哈希 |
| `cost_materials` | 原料 + 价格 | `erp_code`、`price`、`erp_price`、`price_locked`、`price_source`、`erp_synced_at` |
| `cost_parameters` | 成本参数 | 耗用系数、加工费用、售价（按型号） |
| `cost_categories` | 业务分类 | 类别名，用户自建 |
| `cost_settings` | 全局设置 | 取价口径等 |
| `cost_erp_sync` | ERP 同步记账 | 批次、fetched/updated/skipped 计数、last_error |
| `cost_audit` | 变更审计 | 由数据库触发器写入 |

## 代码模块

后端 `app/server/modules/cost/`：

| 文件 | 职责 |
|---|---|
| `erp-price.source.ts` | 金蝶适配器：登录、会话缓存 25min、分页查询、单位过滤、去重 |
| `cost-erp-sync.service.ts` | ERP 价格三层写回、`syncPrices()`、`isConfigured()`、状态记账 |
| `cost-sync.service.ts` | 飞书配方下载、哈希比对、解析、保留上次成功数据 |
| `cost.controller.ts` | `POST api/cost/sync`、`POST api/cost/erp-sync`、`GET api/cost/erp-status` |
| `cost.automation.ts` | `@BindTrigger('cost-formula-refresh')`、`@BindTrigger('cost-erp-price-refresh')` |
| `cost.service.ts` | 核算逻辑 |
| `cost.dto.ts` | 入参校验 |

契约在 `app/shared/api.interface.ts`：`COST_SCOPES = ['precipitated','fumed','liquid']`、`SCOPE_LABELS`、`PRICE_SOURCES`、`Material.erpPrice/priceLocked/priceSource`、`ErpSyncStatus`。

## 常用工具

| 工具 | 位置 | 用途 |
|---|---|---|
| 金蝶只读查询 | `analysis/kingdee-query.ps1` | 验字段、查价格 |
| 金蝶登录探测 | `analysis/kingdee-login-probe.ps1` | 确认账套/凭据可用 |
| 接口证据 | `analysis/kingdee-api-probe.json` | 历史请求响应快照 |
| 本地开发启动 | `analysis/start-dev.cjs` | 8149/3049，加载 `.env.local` |
| DDL 脚本 | `sql/2026-11-liquid-erp.sql` | 液体胶 + ERP 字段，含回滚注释 |

## 环境变量（服务端，dev 与 online 各一套）

```
FEISHU_SOURCE_APP_ID      自建应用 ID
FEISHU_SOURCE_APP_SECRET  应用密钥（不回显）
ERP_KINGDEE_URL           金蝶 WebAPI 入口
ERP_KINGDEE_ACCT          账套 ID
ERP_KINGDEE_USER          集成账号
ERP_KINGDEE_PASSWORD      口令
```

本机同名配置在 `private/feishu-source.env`；ERP 口令在 Windows 凭据管理器 `EDP/Kingdee/InventoryRead`。

## 数据库迁移顺序

```
改 schema.ts
  ↓
生成 DDL，先跑 dev
  ↓
lark-cli apps +db-env-migrate --app-id app_17hsmznx2jc --yes
  ↓
online 单独跑 DML（DDL 在 online 会被拒：forbid ddl/dcl operation in online env）
  ↓
回读确认
```
