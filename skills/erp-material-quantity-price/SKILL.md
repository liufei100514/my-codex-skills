---
name: erp-material-quantity-price
description: 硅基智造 EDP 平台从金蝶云星空取原料「数量」与「单价」的完整口径与实现——数量走 WebAPI 实时只读（STK_Inventory 两仓合计 + PUR_PurchaseOrder 未到货），单价走自建版本化价格库（不取 ERP 采购价）。覆盖字段选择、单位换算、年度过滤、覆盖校验、fail-closed、凭据来源与七个必踩的坑。当要在本平台取/核对原料库存吨数与单价、排查库存或价格对不上、或接入新 ERP 物料时使用。
whenToUse: 用户要看/核对原料当前库存吨数、采购未到货、安全库存缺口、原料单价或成本核算取价；或库存同步任务报错、页面数字与 ERP 不符、新增原料没进清单时。
---

# ERP 原料数量与单价：EDP 平台的取数口径

一句话结论：**数量信 ERP（实时只读），单价不信 ERP（自建版本化价格库）。**

这不是随手的选择，是从两个真实故障里得出的：

- ERP 采购价是"某一次成交价"，单笔急采、促销、包装规格差异都会带偏，直接拿去算成本会让毛利剧烈跳动；
- 采购价目表在多数账套没启用（`PUR_PriceList` / `PUR_SupplierPrice` 常见"业务对象不存在"），拿不到稳定价。

所以本平台只从 ERP 取**数量事实**（库存、未到货），价格由成本模块自己维护成**带生效日的版本化价格库**，两者在核算时才相遇。

配套的通用金蝶接口知识（登录、`ExecuteBillQuery`、字段坑）见技能 `kingdee-k3cloud-readonly`；本文只写 EDP 这一层的口径。

---

## 一、两条链路一览

| | 数量 | 单价 |
|---|---|---|
| 数据源 | 金蝶 WebAPI（只读） | 本机 SQLite 价格库 |
| 表单/表 | `STK_Inventory` + `PUR_PurchaseOrder` | `data/cost-center/costs.sqlite3` → `batches` |
| 更新方式 | 每天 09:00 计划任务自动拉 | 人工录入 + 提交（带生效日） |
| 口径 | 两仓合计、kg→吨 | 含税元/kg、按生效日回放 |
| 代码 | `kingdee_inventory_webapi.py` → `erp_inventory_sync.py` → `erp_purchase_incoming.py` → `kingdee_inventory_sync_job.py` | `cost_center.py` |

连接参数（硬编码在 `kingdee_inventory_webapi.py`，换账套必须改）：

```
BASE_URL = https://changlian.ik3cloud.com/K3Cloud
ACCOUNT_ID = 5c20de882b6156     # 账套，拼错就是登录失败且不提示原因
```

---

## 二、数量：库存怎么取

### 查询字段（原样照抄，顺序敏感）

```python
FORM_ID = "STK_Inventory"
FIELD_KEYS = (
    "FMaterialId.FNumber", "FMaterialId.FName", "FMaterialId.FSpecification",
    "FStockId.FName", "FBaseUnitId.FName", "FBaseQty", "FStockOrgId.FName",
)
```

`FilterString` 传**空字符串**（拉全量），`OrderString="FMaterialId.FNumber ASC"`，`Limit=2000` 翻页到不足一页为止。

### 三个过滤条件，缺一个数字就错

```python
TARGET_WAREHOUSES = {"硅基原料仓", "硅基车间仓"}   # 只认这两个仓
KILOGRAM_UNITS    = {"kg", "千克"}                # 只认 kg 计量
# 物料编码非空
```

- **两仓是"合计"，不是"取其一"**：入库进硅基原料仓、领用调拨到硅基车间仓，同一个物料编码会在两仓各有一行。`stock_kg_by_code[code] += 库存量` 累加后再 `/1000` 转吨。
- 其它部门仓（不良品仓、外购仓…）**一律不计**，否则库存会虚高。
- 单位不是 kg 的行**直接跳过**（不是换算、不是猜）——因为"个/米/套"根本没法折成吨。

### 吨换算与精度

```
当前库存(吨) = Σ(两仓 kg) / 1000        # 保留 6 位小数
安全库存(吨) 来自物料主数据（本地维护）
库存状态 = 安全库存 > 当前库存 ? "低于安全库存" : "充足"
```

**库存为 0 的物料不能删**：清单是"已纳入台账的物料"，归零只代表这阵子用完了。删掉会让历史对比断档，也会让覆盖校验误判。

### 采购未到货（在途量）

```python
FORM_ID = "PUR_PurchaseOrder"
FILTER = ("FDocumentStatus='C' and FCancelStatus='A' "
          "and FCloseStatus='A' and FMRPCloseStatus='A' and FMrpTerminateStatus='A' "
          "and FDate>='2026-01-01' and FDate<'2027-01-01'")
```

- 五个状态位缺一不可：已审核、未作废、未整单关闭、业务未关闭、未终止。少一个就会把作废单、关闭单的余量算进在途。
- **未到货 = max(基本单位订单数量 − 基本单位已到货数量, 0)**，字段名 `FBaseUnitQty` / `FBaseReceiveQty`。
- 只统计**当年**采购订单（`PURCHASE_YEAR = 2026`，硬编码在 `erp_purchase_incoming.py`）；**跨年必须改这个常量**，否则 1 月 1 日会把去年陈单算成在途。
- 单位换算：`kg/千克/公斤 → /1000`；`t/吨 → 原值`；**其它单位直接抛 `KINGDEE_PURCHASE_UNIT_UNSUPPORTED`**，不许静默跳过（跳过就等于漏掉一笔在途）。

### 两个数不能混用

```
当前库存缺口   = max(订单需求 − 当前库存, 0)
到货后净缺口   = max(订单需求 − 当前库存 − 采购未到货, 0)
```

在途是"还没进仓的货"，页面和采购建议里必须分开显示，不能把在途当现货。

### 新物料自动发现（策略 `20261030-two-warehouse-material-discovery-v1`）

每天同步时会顺手发现清单外的新原料，入册条件（全部满足）：

1. 两仓有库存记录，且**合计 > 0**；或合计 ≥ 0 且**有采购未到货**
2. ERP 主档（`BD_MATERIAL`）为**外购**、`FDocumentStatus` 已审核、`FForbidStatus` 未禁用、单位 kg
3. 物料分组 ∈ {105 硅胶, 201 主要材料}（两个组织分组可不同，但型号/名称/规格等身份字段须一致）

同型号对应多个 ERP 编码、分组未知、主档冲突 → **进待核报告，不猜**。新增或待核报告落在 `outputs/erp-inventory-sync/material-discovery-history/`。

---

## 三、单价：价格库怎么取

### 存储：版本化批次，不是"一张价格表"

```sql
batches(id INTEGER PK, request_id TEXT UNIQUE, digest TEXT,
        effective TEXT,      -- 生效日 YYYY-MM-DD
        created TEXT, actor TEXT,
        payload TEXT)        -- JSON：{prices:[{materialCode,unitPrice,kind}], parameters:[...]}
```

`payload.prices[]` 每条：`materialCode`（已规范化）、`unitPrice`（**含税元/kg**）、`kind ∈ {purchase, internal}`。

### 取"某天有效价"：按 (effective, id) 顺序回放

```python
rows = SELECT * FROM batches WHERE effective <= :as_of ORDER BY effective, id
state = {}                       # 后面的批次覆盖前面的同名物料
for row in rows: apply(state, json.loads(row['payload']), row['id'])
```

由此得到三个语义边界：

- **价格按生效日回放**，不是"最新一批通吃"——查 9 月的成本就用 `as_of=2026-09-30`。
- 同一物料改价 → 新批次覆盖，旧批次仍在库（可对账、可回溯）。
- `state['priceBasis'] = '含税元/kg'` 是写死的口径，展示时必须一起给出，否则会被当成不含税价。

### 自制料必须用内部成本价

```python
SELFMADE = {'S530','S550','S570-1','S570-2','S570-3','S580'}
# 校验：code in SELFMADE 时 kind 必须是 internal，否则整批提交报错
```

核算时自制基料**递归**：`canonical_product_key(code)` 能在配方索引里找到 → 用下级配方的 `totalCost`，不看价格库；找不到才回落到价格库的 `internal` 价。缺价进 `issues`，**绝不按 0 计算**（按 0 会让毛利虚高）。

### 幂等与并发

- 每个提交带 `requestId` + `revision`；`request_id` 已存在且 `digest` 相同 → 返回原版本（重试安全），内容不同 → `Conflict`。
- `revision` 必须等于当前 `MAX(id)`，否则 `价格库已被其他人更新，请重新预览`（乐观锁）。
- 每次发布前自动 `sqlite3 backup` 到 `data/cost-center/backups/`。

### 成本公式（价格在这里和数量相遇）

```
单原料成本/吨 = 用量占比 × 单价
材料成本/吨   = Σ 单原料成本 × 损耗系数
总成本/吨     = 材料成本 + 八项费用合计/1000
八项费用 = 包材·人工·折旧·电费·机物料·维修·管理费·运费（逐项必填，零也要写 0）
```

注意费用是**元/吨**、单价是**元/kg**，`/1000` 这个换算每年都被漏一次。

---

## 四、校验与失败姿势：宁可停更，不许发假数

同步任务的 fail-closed 顺序（任一不满足就不切换快照，保留上一版）：

| 关卡 | 阈值 | 触发后的行为 |
|---|---|---|
| 行数下限 | `≥ 100` 行 | `KINGDEE_INVENTORY_ROW_COUNT_TOO_LOW` |
| 目标仓物料非空 | 至少 1 个编码 | `KINGDEE_TARGET_WAREHOUSE_ROWS_EMPTY` |
| 覆盖率 | 上一版非零库存物料 ∩ 本次 ≥ **0.8** | `KINGDEE_INVENTORY_COVERAGE_TOO_LOW` |
| 记录数一致 | 必须等于物料台账条数 | `ERP_INVENTORY_RECORD_COUNT_MISMATCH` |
| 日期不倒退 | `business_date >= snapshotDate` | `STALE_ERP_INVENTORY` |
| 读回校验 | 哈希/条数/来源标记全对 | `ERP_INVENTORY_READBACK_FAILED` → **自动回滚** |

执行顺序：备份 → 写临时文件 → 原子替换 → 读回比对 → 失败则还原快照与运营中心快照。

排障时先看这三个文件，不猜：

```
outputs/erp-inventory-sync/<业务日期>.json           # 成功结果
outputs/erp-inventory-sync/<业务日期>-failed.json    # 失败原因
outputs/erp-inventory-sync/<业务日期>-public-failed.json  # 本地成功、推公网失败
```

`status: duplicate` 是正常结果（同日期同哈希不重复写），不要当成没跑。

---

## 五、凭据放哪

| 场景 | 来源 |
|---|---|
| 生产（本机计划任务） | Windows 凭据管理器，目标名 `EDP/Kingdee/InventoryRead`（generic） |
| 读取方式 | 优先 `win32cred.CredRead`；pywin32 不可用时走 `ctypes` 调 `Advapi32.CredReadW`（密码按 UTF-16LE 解码） |
| 开发/临时 | 环境变量 `EDP_KINGDEE_USERNAME` / `EDP_KINGDEE_PASSWORD` |

密码**不落代码、不落仓库、不进日志**。读不到凭据时明确抛 `KINGDEE_CREDENTIAL_NOT_CONFIGURED`，不要退化到空密码重试。

---

## 六、七个必踩的坑

1. **`FBaseQty` 在库存表存在，在采购订单表不存在**。库存用 `FBaseQty`，采购用 `FBaseUnitQty`；跨表单照搬必报"元数据中标识为 FBaseQty 的字段不存在"。（通用技能里说"FBaseQty 不存在"指的是采购单，别搞混。）
2. **两处单位集合不一致**：`erp_inventory_sync.KILOGRAM_UNITS = {kg, 千克}`，而 `erp_purchase_incoming.KILOGRAM_UNITS = {kg, 千克, 公斤}`。库存侧**不含"公斤"**——如果哪天 ERP 把某物料主单位写成"公斤"，它的库存会被静默丢掉，只会被覆盖率 0.8 那道关拦住。改单位集合时两处一起改。
3. **同一物料编码多行是正常的**（多组织/多仓/多视图）。库存侧要按编码**求和**，采购侧要按单据行**逐行累加**，都不是"取第一条"。
4. **`FStockOrgId.FName` 是库存组织，不是仓库**。按组织过滤会把别的仓一起带进来；过滤仓必须用 `FStockId.FName`。
5. **未到货只统计当年**（`PURCHASE_YEAR` 硬编码）。跨年第一天的第一件事就是改它。
6. **在途不能当现货**。页面同时给"当前库存缺口"和"到货后净缺口"，混用一个数会让采购判断失准。
7. **覆盖率校验是防"接口半残"的**。金蝶偶发只返回部分行（超时截断、权限变更），没有覆盖率校验就会用"少了 30 个物料"的数据覆盖掉好快照。

---

## 七、最小可跑脚本

`scripts/erp-material-probe.py`：读凭据 → 登录 → 拉库存 + 采购 → 按本口径汇总 → 打印吨数与在途，用于核对与排障。

```powershell
python scripts/erp-material-probe.py                 # 全量（约 8 万行，30–90 秒）
python scripts/erp-material-probe.py --limit 50      # 只取前 50 行，验证登录与字段
python scripts/erp-material-probe.py --top 20        # 只看库存最多的 20 个物料
python scripts/erp-material-probe.py --as-of 2026-09-30 --price-db <costs.sqlite3>   # 顺带查当期有效价
```

脚本只调 `ValidateUser` 与 `ExecuteBillQuery` 两个接口，**零写操作**。

## 八、验证过的真实基线（2026-11-21，硅基账套）

| 项 | 值 |
|---|---|
| `STK_Inventory` 全量行数 | **79,598** 行 |
| `PUR_PurchaseOrder` 过滤后行数 | **459** 行 |
| 两仓 kg 计量物料数（全量） | **1,098** 个 |
| 台账口径物料数 | **154** 个 |
| 台账库存合计 | **632.384577 吨** |
| 台账在途合计 | **215.705000 吨**（13 个物料有在途） |
| 台账外的非 kg/吨 采购行 | **169 行**（米 / 个 / 平方米），按设计跳过 |

**口径一致性验证（最硬的一条）**：取当天 09:00 任务落盘的原始行
`data/sources/erp-inventory-webapi/<日期>/金蝶WebAPI即时库存与采购未到货_<日期>.json`，
用本文口径离线复算 → 库存 632.384577、在途 215.705000，**与平台快照逐物料 0 差异**。

**同一天 11:00 再实时查一次，得到 608.500 / 213.575 —— 差 23.9 吨。这不是口径错，是库存本身是实时数**：两小时里生产一直在领料。由此两条硬规矩：

1. 对账必须**用同一份原始行复算**，不能拿"现在查的数"去比"早上的快照"；
2. 任何展示库存的地方都必须带 `snapshotDate`，否则会被当成"此刻的实时库存"。

## 九、自检清单（改完代码/换账套后逐条过）

- [ ] 库存行数 > 我预期的数量级（不是 100 行那种"半截"数据）
- [ ] 目标仓命中的物料数与上一版台账相当（覆盖率 ≥ 0.8）
- [ ] Σ两仓 ÷ 1000 与业务方手里的库存表对得上（量级、不是精确值）
- [ ] 未到货只含本年、且状态位是五个都过滤后的
- [ ] 有采购未到货的物料，在途吨数 > 0 且带订单号/供应商证据
- [ ] 价格库里该物料的 `effectiveDate ≤ 核算日` 且 `priceBasis = 含税元/kg`
- [ ] 自制料（S530 等）走的是内部成本价而不是采购价
- [ ] 缺价物料出现在 `issues` 里，而不是被当成 0 元参与计算
- [ ] 展示库存时带了 `snapshotDate`，没有把历史快照当成实时数
- [ ] 对账用同一份原始行复算，而不是拿实时查询比旧快照
