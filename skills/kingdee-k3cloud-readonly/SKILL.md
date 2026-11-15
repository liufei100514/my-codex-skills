---
name: kingdee-k3cloud-readonly
description: 通过金蝶云星空（K3Cloud / ik3cloud）WebAPI 只读拉取主数据与单据——物料、采购订单价格、采购申请、即时库存。覆盖登录与会话复用、ExecuteBillQuery 用法与字段坑、多组织重复去重、计量单位换算、取价口径选择、以及"只读不写"的安全边界。当用户要用 ERP 里的价格/数量喂给自有系统、把金蝶数据接进应用、或排查金蝶接口报错时使用。
whenToUse: 用户提到金蝶、K3Cloud、ik3cloud、账套、acctID、ExecuteBillQuery、ERP 物料/采购价/库存；或者要给成本核算、采购、库存类应用接 ERP 数据源。
---

# 金蝶云星空 WebAPI：只读取数

一个真实跑通的路径：把 ERP 采购价同步进自建成本核算应用（45 个物料、90 行价格、每小时自动跑），全程只调两个接口，零写操作。

## 一、先确认三件事

| 项 | 缺了会怎样 |
|---|---|
| WebAPI 入口 `https://<tenant>.ik3cloud.com/K3Cloud` | 拼错前缀会 404，不是 401 |
| 账套 `acctID`（形如 `5c20de882b6156`） | 拿不到就是登录失败，且报错不提示是账套问题 |
| 用户名 + 密码 | 只从凭据管理器 / 环境变量取，写进代码就是事故 |

安全边界（照抄）：**只用 `ValidateUser` 和 `ExecuteBillQuery`**。`Save` / `Submit` / `Audit` / `Push` 一律不碰 —— 生产账套没有测试标识，写错一张单就是真实业务数据。

## 二、登录

```bash
POST {base}/Kingdee.BOS.WebApi.ServicesStub.AuthService.ValidateUser.common.kdsvc
Content-Type: application/x-www-form-urlencoded

acctID=<账套>&username=<用户>&password=<密码>&lcid=2052
```

成功判据（任一成立即可，两个都给最稳）：

```json
{ "LoginResultType": 1, "IsSuccessByAPI": true }
```

**会话必须复用**：登录响应头里的 `Set-Cookie` 拼成 `Cookie: k1=v1; k2=v2`，后续每个请求都带上。不要每个查询都重新登录 —— 金蝶会限流，而且慢。内存缓存 25 分钟、提前失效重登即可。

## 三、查数据：ExecuteBillQuery

```bash
POST {base}/Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.ExecuteBillQuery.common.kdsvc
Content-Type: application/x-www-form-urlencoded
Cookie: <登录拿到的>

data={"FormId":"...","FieldKeys":"...","FilterString":"...","OrderString":"...","TopRowCount":0,"StartRow":0,"Limit":2000}
```

要点：

- `data` 是 **JSON 字符串**（表单编码时要再 URL 编码一层），不是对象
- 返回 `list of list`，内层元素顺序与 `FieldKeys` 完全对应 —— 自己建字段名映射，别指望它返回对象
- `Limit` 上限 2000；`StartRow` 累加翻页，直到某页返回行数 `< Limit`
- `FilterString` 语法接近 SQL WHERE：`FDocumentStatus='C' and FCancelStatus='A' and FMaterialId.FNumber in ('A','B')`
- 单次查询的 IN 列表别太长（45 个编码一次查没问题；上千个要分批）

## 四、已验证的字段（长联调前先读这张表）

**物料 `BD_MATERIAL`**

```
FNumber, FName, FSpecification
```

**采购订单 `PUR_PurchaseOrder`**

```
FID, FPOOrderEntry_FEntryid, FBillNo, FDate, FSupplierId.FName,
FMaterialId.FNumber, FBaseUnitId.FName, FBaseUnitQty, FBaseReceiveQty,
FDeliveryDate, FTaxPrice
```

状态字段：`FDocumentStatus`（C=已审核）、`FCancelStatus`（A=未作废）、`FCloseStatus`、`FMRPCloseStatus`、`FMrpTerminateStatus`

**采购申请 `PUR_Requisition`**

```
FID, FBillNo, FApplicationDate, FApplicationOrgId.FName,
FMaterialId.FNumber, FReqQty, FUnitID.FName, FDocumentStatus
```

## 五、五个会让你多花两小时的坑

1. **`FBaseQty` 不存在** → 订单里叫 `FBaseUnitQty`；申请单里叫 `FReqQty`。跨表单照搬字段必报"元数据中标识为 X 的字段不存在"。
2. **物料主数据用 `FNumber`，不是 `FMaterialId.FNumber`**。后者是"别的单据里引用物料"时的写法；直接查 `BD_MATERIAL` 会报字段不存在。
3. **采购申请不支持 `FDeliveryDate`**，订单支持。这个字段在两类单据上不对称。
4. **同一 `FNumber` 会返回多条**（多组织 / 多视图）。`ZC1367` 一次查出 3 行是正常的，按编码去重再处理，不要以为接口出错。
5. **单位不统一**：同一个物料可能以"个""千克""米"计量。要接到"元/kg"这种统一口径前，必须先按 `FBaseUnitId.FName` 过滤（只认 `kg/千克/公斤`），否则 79.1 元/个 会被当成 79.1 元/kg 直接污染成本。

错误长这样，按字面判断即可：

```
{"Result":{"ResponseStatus":{"ErrorCode":500,"IsSuccess":false,
 "Errors":[{"Message":"元数据中标识为FBaseQty的字段不存在"}]}}}
{"Result":{"ResponseStatus":{"ErrorCode":500,"IsSuccess":false,
 "Errors":[{"Message":"标识为“PUR_PriceList”的业务对象不存在，或者被删除。"}]}}}
```

## 六、取价口径：先问清楚，别默认

| 口径 | 规则 | 适用 |
|---|---|---|
| 最近一次成交价 | 按 `FDate DESC` 取该物料第一条 | 对行情最敏感；单笔急采会带偏 |
| 近 N 次加权平均 | 按 `FBaseUnitQty` 加权 | 平滑，适合成本核算；有滞后 |
| 采购价目表 | 查价目表表单 | 最稳定，但很多账套没启用（`PUR_SupplierPrice` / `PUR_PriceList` / `BD_PriceCategory` 可能全部"业务对象不存在"） |

实操：**先试价目表，不存在就退回最近成交价 + 人工可锁定**。落地时一定配"价格偏离告警"（比如与现价差 ±10% 标黄），避免 ERP 脏数据直接冲进成本。

## 七、凭据放哪

| 环境 | 来源 |
|---|---|
| 本机联调 | Windows 凭据管理器（`cmdkey /list` 里能看到目标名），用 `CredRead` 读，不进日志、不进仓库 |
| 服务端/云端 | 平台环境变量（本项目走 `lark-cli apps +env-set`，dev 与 online 各写一套） |

`scripts/kingdee-probe.ps1` 是一个可直接跑的最小实现：读凭据 → 登录 → 查物料 → 打印前几行，用来验证账套和权限。

## 八、接到自有系统时的最小结构

```
适配器（登录 + 会话 + 分页 + 去重 + 单位过滤）
   ↓ 产出 [{ erpCode, price, unit, billNo, date }]
同步服务（按本地编码匹配 → 写回 → 记账状态）
   ↓
定时触发器（每小时一次）
```

两个设计决定值得抄：

- **ERP 原值和生效值分开存**：`erp_price` 永远保留（对账用），`price` 才是参与计算的；`price_locked` 让业务方锁定个别不准的价，`price_source` 标明来源。不做这个分层，同步一跑人工修正就没了。
- **ERP 有、本地没有的物料不自动创建**，进 `unmatched` 列表让人判断。价格库被脏数据污染后，"缺价"统计就废了。

## 参考

- `references/api-cookbook.md` —— 每个接口的完整请求/响应样例、字段对照、错误码表
- `scripts/kingdee-probe.ps1` —— 最小可跑的登录 + 只读查询脚本
