# 金蝶云星空 API 手册（实测版）

所有样例来自真实账套的实测响应，不是文档抄写。

---

## 1. 登录

```
POST {base}/Kingdee.BOS.WebApi.ServicesStub.AuthService.ValidateUser.common.kdsvc
Content-Type: application/x-www-form-urlencoded
```

请求体：

```
acctID=5c20de882b6156&username=张三&password=***&lcid=2052
```

响应（成功）：

```json
{ "LoginResultType": 1, "IsSuccessByAPI": true, "Context": { ... } }
```

响应（失败）：

```json
{ "LoginResultType": 0, "IsSuccessByAPI": false, "Message": "用户名或密码错误" }
```

要点：
- `lcid=2052` 简体中文；不传可能返回英文错误文案
- 用户名可以是中文（`刘飞`），表单编码再 URL 编码，不要手动拼字符串
- 响应头 `Set-Cookie` 可能有多个，全部拼进后续 `Cookie` 头
- 会话有效期一般 20~30 分钟，缓存 25 分钟就重登一次

---

## 2. ExecuteBillQuery

```
POST {base}/Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.ExecuteBillQuery.common.kdsvc
Content-Type: application/x-www-form-urlencoded
Cookie: <登录 Cookie>

data={"FormId":"BD_MATERIAL","FieldKeys":"FNumber,FName","FilterString":"","OrderString":"FNumber ASC","TopRowCount":0,"StartRow":0,"Limit":2000}
```

响应（成功）：

```json
[
  ["0001", "D437", ""],
  ["067C", "067C", ""],
  ["1050001", "液体硅胶浆", "LSR2150A"]
]
```

响应（字段不存在）：

```json
[[{"Result":{"ResponseStatus":{"ErrorCode":500,"IsSuccess":false,
  "Errors":[{"FieldName":null,"Message":"元数据中标识为FBaseQty的字段不存在","DIndex":0}],
  "SuccessEntitys":[],"SuccessMessages":[],"MsgCode":9}}}]]
```

注意响应结构会变：成功是 `[[...]]`，出错是 `[[{...}]]` —— 用类型判断（Array of scalars vs Array of object）区分，别用长度判断。

响应（表单不存在）：

```json
[[{"Result":{"ResponseStatus":{"ErrorCode":500,"IsSuccess":false,
  "Errors":[{"Message":"标识为“PUR_PriceList”的业务对象不存在，或者被删除。","DIndex":0}],
  "MsgCode":4}}}]]
```

---

## 3. 字段对照（实测）

### BD_MATERIAL 物料

| 字段 | 含义 | 备注 |
|---|---|---|
| `FNumber` | 物料编码 | **不是** `FMaterialId.FNumber` |
| `FName` | 名称 | 简单字段，多语言时另说 |
| `FSpecification` | 规格型号 | |

### PUR_PurchaseOrder 采购订单

| 字段 | 含义 | 备注 |
|---|---|---|
| `FBillNo` | 单号 | |
| `FDate` | 日期 | ISO 字符串，可直接排序 |
| `FMaterialId.FNumber` | 物料编码 | 订单里是嵌套写法 |
| `FSupplierId.FName` | 供应商 | |
| `FTaxPrice` | **含税单价** | 取价主力字段 |
| `FPrice` | 不含税单价 | |
| `FBaseUnitQty` | 数量（基本单位） | **不是** `FBaseQty` |
| `FBaseUnitId.FName` | 基本单位 | `kg` / `个` / `米` … |
| `FDeliveryDate` | 交货日期 | 订单有、申请单没有 |
| `FDocumentStatus` | 单据状态 | C=已审核 |
| `FCancelStatus` | 作废状态 | A=未作废 |

### PUR_Requisition 采购申请

| 字段 | 含义 |
|---|---|
| `FBillNo` / `FApplicationDate` | 单号 / 申请日期 |
| `FApplicationOrgId.FName` | 申请组织 |
| `FMaterialId.FNumber` | 物料编码 |
| `FReqQty` | 申请数量（**不是** `FBaseUnitQty`） |
| `FUnitID.FName` | 单位 |
| `FDocumentStatus` | 状态 |

---

## 4. 状态码

`FDocumentStatus`：`A` 创建/未审核 · `Z` 暂存 · `B` 审核中 · `C` 已审核
`FCancelStatus`：`A` 未作废
`FCloseStatus`：`A` 整单未关闭
`FMRPCloseStatus`：`A` 未业务关闭
`FMrpTerminateStatus`：`A` 未终止

取"真实生效的采购价"时的过滤条件：

```
FDocumentStatus='C' and FCancelStatus='A'
```

---

## 5. 分页

```
for page in 0..N:
    StartRow = page * 2000
    Limit = 2000
    rows = query(...)
    if len(rows) < 2000: break
```

- 设一个页数上限（比如 20 页 = 4 万行）防跑飞
- 排序键要带唯一性（`FDate DESC` 时同一时刻多行可能导致跨页重复/遗漏，必要时加 `FBillNo`）

---

## 6. 多组织重复

同一 `FNumber` 在 `BD_MATERIAL` 里可能返回多行（按组织/视图隔离）。实测 `ZC1367` 返回 3 行完全相同的记录。

处理：
- 按 `FNumber` 去重后再用
- 需要区分组织时，加 `FCreateOrgId.FName` 之类的字段并显式过滤

---

## 7. 单位换算

ERP 的单价是"元/<基本单位>"。要接到"元/kg"口径：

```
只接受 FBaseUnitId.FName ∈ { kg, 千克, 公斤, KG, Kg }
其它单位（个/米/升/卷）跳过，并在日志里记一行
```

**不要**自作聪明按密度换算 —— 没有可靠的密度主数据，猜出来的数会直接污染成本。

---

## 8. 一次性验通的最小清单

1. 登录 → 拿到 `LoginResultType=1`
2. `BD_MATERIAL` 查 5 条 → 确认 `FNumber/FName` 可读
3. 用第 2 步里某个 `FNumber` 反查 `PUR_PurchaseOrder` → 确认 `FTaxPrice` 可读
4. 确认返回里 `FBaseUnitId.FName` 是 kg（否则要过滤）
5. 确认同一物料多次采购的价格分布 → 决定取价口径

这 5 步过了，后面的同步只是工程量。
