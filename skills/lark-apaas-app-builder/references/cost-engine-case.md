# 案例：配方成本核算（硅基材料）

这是 `lark-apaas-app-builder` 的完整业务样板。要搭"配方/工艺 → 成本"这类台账应用，把这里的概念映射、公式方向、缺数据口径照抄，把原料和产品换掉即可。

---

## 1. 业务长什么样

- 产品：**沉淀胶 / 气相胶** 两大类（`scope = precipitated | fumed`），每类下几十到上百个型号（`GG-2110`、`GG-7350YJ`…），共 166 个配方
- 配方：每个型号由若干**原料**按**投料重量**配成（一条配方 8~15 项原料，单批量级 kg 到几百 kg）
- 价格：原料单价**含税、元/kg**，且**沉淀与气相分别定价**（同一原料 S110：沉淀 13.8、气相 14.5）
- 费用：每个型号有**加工费用**（元/吨，可多项：加工费、包装费…）和**耗用系数**（损耗）
- 售价：部分型号有含税售价，用来算毛利
- 数据来源：配方在**飞书表格**里维护（业务方自己改），应用只读同步；价格/费用/分类在应用内维护

结论：**配方是只读外部数据，价格是应用内主数据，成本是算出来的派生数据**。三者分开存，不要混成一张表。

---

## 2. 概念 → 数据模型

| 业务概念 | 表 | 关键字段 | 唯一键 |
|---|---|---|---|
| 配方来源（一份飞书表） | `cost_sources` | `drive_token`、`current_hash`、`formulas jsonb`、`last_success_at`、`last_error` | `id`（= scope） |
| 配方（一个型号的投料清单） | 存在 `cost_sources.formulas` 里 | `model_key`、`product_model`、`ingredients[{materialCode, usageKg}]`、`source_row` | `(scope, modelKey)` |
| 原料价格 | `cost_materials` | `code`、`price numeric(18,6)`、`category_id` | `(scope, code)` |
| 核算参数 | `cost_settings` | `loss_multiplier`、`fees jsonb`、`fees_configured`、`selling_price` | `(scope, model_key)` |
| 原料分类 | `cost_categories` | `name` | `name` |
| 变更留痕 | `cost_audit` | `before/after jsonb` | 由触发器写入 |

关键设计判断：

- **配方不落成"配方行 + 组分行"两张表**，而是整份 JSONB 存进来源表。理由：配方只在同步时整体替换，不做行级编辑；拆表反而要处理"删掉的组分"这类麻烦
- **参数表独立于配方表**：飞书新增型号时自动补一条空参数（`loss_multiplier=null`、`fees=[]`、`fees_configured=false`），业务方在应用里补系数和费用
- **`fees_configured` 布尔字段必须有**：区分"还没配"和"明确配成 0 元"—— 这两者在成本上完全不是一个意思

---

## 3. 核算链条（公式方向最容易搞反）

```
① 投料总量     inputKg      = Σ usageKg
② 核算产出     outputKg     = inputKg / lossMultiplier        ← 除，不是乘
③ 批原料金额   batchAmount  = Σ (price_i × usageKg_i)
④ 原料每吨成本 rawCostPerTon = batchAmount / outputKg × 1000
⑤ 加工每吨费用 processing   = Σ fee.amount                      （单位：元/吨）
⑥ 总成本       totalCost    = rawCostPerTon + processing
⑦ 毛利率       grossMargin  = (sellingPrice − totalCost) / sellingPrice      ← 分母是售价
⑧ 成本加成率   costMarkup   = (sellingPrice − totalCost) / totalCost         ← 分母是成本
```

两个坑，写代码前必须和业务方确认方向：

**① 耗用系数是除不是乘。**
`lossMultiplier = 1.02` 的含义是"投 1.02 吨才产出 1 吨"（损耗 2%），所以 `outputKg = inputKg / 1.02`。
写成 `inputKg * 1.02` 会让成本凭空低 4%，且没人能一眼看出来。

**② 毛利率和成本加成率是两个数，不能混用。**
同一个售价 16800、总成本 15439.44：毛利率 8.10%、成本加成率 8.81%。原表用的是"成本加成率"，销售习惯说"毛利率"，**界面上两个都显式标注分母**，不要让用户猜。

---

## 4. 黄金算例（可直接当回归测试基线）

配方 `GG-2110`（沉淀）：

| 原料 | 用量 kg | 单价 元/kg | 金额 |
|---|---|---|---|
| S001 | 2.8 | 18.5 | 51.80 |
| S002 | 2.8 | 13.5 | 37.80 |
| S110 | 400 | 13.8 | 5520.00 |
| F717 | 125 | 6.2 | 775.00 |
| S005 | 6 | 24.5 | 147.00 |
| S006-1 | 1.7 | 32.3 | 54.91 |
| S180 | 150 | 15.6 | 2340.00 |
| KM-1M | 120 | 17.5 | 2100.00 |

参数：`lossMultiplier = 1.02`，`fees = [{加工费用: 1525}]`，`sellingPrice = 16800`

期望结果（精确到 1e-7）：

```
inputKg        = 808.3
outputKg       = 792.4509803921569      (808.3 / 1.02)
batchAmount    = 11026.51
rawCostPerTon  = 13914.4379562044       (11026.51 / 792.4509... × 1000)
processing     = 1525
totalCostPerTon= 15439.4379562044
grossMargin    = 0.080985...            (16800 − 15439.44) / 16800
costMarkup     = 0.0881225111726866     (16800 − 15439.44) / 15439.44
```

原表复现验证过的另一组：`GG-7350YJ` 两条同名配方按源表 32 / 34 行分别计算，得 `18.7743926220` 和 `18.5833274614` 元/kg（即 18774.39 / 18583.33 元/吨）。

---

## 5. 计算引擎的五条硬规则

```ts
export function calculateCost(formula, prices, setting): CostResult
```

| 规则 | 做法 | 为什么 |
|---|---|---|
| 缺价不算 0 | 匹配不到价格 → `price = null`、进 `missingMaterials`、`rawCostPerTon = null` | 按 0 算会让成本虚低，业务方拿去做报价直接亏 |
| 零价可用 | `price = 0` 是合法值，正常算出 0 | "明确免费/内部调拨"和"不知道多少钱"必须区分 |
| 同名型号只警告 | `warnings: ['存在相同型号，按各自配方核算']`，`issues` 不含它 | 业务上确实存在同名不同配方的历史数据，阻断会让老数据全废 |
| 真异常才阻断 | 用量 ≤0、投料总重无效、重复价格、未配费用 → 进 `issues`，总成本 `null` | 这些一定会算错，宁可不给数 |
| 售价 0 不算利润 | `sellingPrice = 0` 或 null → `grossMargin = null` | 不虚构利润数字 |

`rawCostPerTon` 的计算条件要写严：**`outputKg` 非空 且 `missingMaterials` 为空 且 `issues` 为空**。任何一项不满足就返回 `null`，不给"部分成本"这种半成品数字。

---

## 6. 代号规范化（脏数据的第一道闸）

飞书表格里同一个原料会写成 `S006`、`S006-1`、` S006 `；型号会有全角括号和连字符差异。解析前统一规范化：

```ts
// 型号：NFKC + 去空格/连字符/破折号/下划线 + 大写
export function normalizeModelKey(v: string): string {
  return v.normalize('NFKC').replace(/[\s\-—_]/g, '').toUpperCase();
}
// 'GG-2120N（特调）' → 'GG2120N(特调)'   ← NFKC 把全角（）转半角

// 原料代号：NFKC + 去所有空白 + 大写 + 别名表
export function canonicalMaterialCode(v: string): string {
  const code = v.normalize('NFKC').replace(/\s/g, '').toUpperCase();
  const aliases = {
    'DMF-1000': 'KM-1M', 'HS-300': 'F300', 'HS-200': 'F772',
    'S006': 'S006-1', 'H50(718)': 'F718', 'H50': 'F718',
    'S112(45万)': 'S112(45)', 'S112(60万)': 'S112(60)',
  };
  return aliases[code] ?? code;
}
```

别名表来自**原成本表已核实的写法**，一条一条列出来并注释来源，不要用模糊匹配。
`'S112（45万）'` 这种全角括号 + 中文单位的，NFKC 后是 `S112(45万)`，再靠别名表映射到 `S112(45)`。

---

## 7. 两套价格必须独立

沉淀和气相的同一原料价格不同（S110：13.8 / 14.5），任何查询都必须带 `scope`：

```ts
prices.filter((p) => p.scope === formula.scope && canonicalMaterialCode(p.code) === canonicalMaterialCode(item.materialCode))
```

表上也要用 `unique(scope, code)` 兜底，防止有人插了一条没 scope 的价格。
**验收方式**：给 S110 在沉淀改价，气相型号的成本必须一点都不动（测试里有这条）。

---

## 8. 单位口径：内部元/吨，展示元/kg

- **内部计算统一用"元/吨"**：配方投料是 400kg、125kg 这种量级，单批金额上万，元/吨是万级整数，浮点误差和可读性都好
- **界面按用户习惯切换**：默认 `元/kg`，除以 1000，显示 4 位小数（`18.7744`）；切到 `元/吨` 显示 2 位
- 加工费用字段本身就是元/吨，不要转换
- 前端切换单位只改除数，不改数据：

```ts
const divisor = unit === 'kg' ? 1000 : 1;
money(cost.totalCostPerTon / divisor, unit === 'kg' ? 4 : 2)
```

小数位由业务精度决定（这里原料价 3~6 位、成本 4 位），写进格式化函数，别各处 `toFixed`。

---

## 9. 界面上的缺数据提示（业务信任的基础）

| 情况 | 卡片显示 | 详情页 |
|---|---|---|
| 缺原料价格 | `待补价` + `N 项原料待补价` | 明细里该行标"待补价/参数" |
| 缺耗用系数 | `补齐后核算` | 提示"待设置耗用系数" |
| 未配加工费用 | `补齐后核算` | 提示"待设置加工费用"，并说明"当前无加工费用，保存即明确按 0 元/吨计入" |
| 同名型号 | `可核算` + 黄字提示 + `源表第 N 行` | 提示共用参数、按本行配方计算 |
| 配方异常 | `补齐后核算` | 红字列出 issues |

顶部分组统计："可核算 N / 待完善 M"，点数字直接筛选 —— 业务方一进页面就知道还差多少活。

---

## 10. 换行业怎么套

**保留不动**（这套骨架跟行业无关）：
- 概念三层：外部只读源 / 应用内主数据 / 派生计算值
- 同步链路：hash 幂等 → 解析失败整表拒绝 → 新条目补空壳
- 缺数据用 null 不用 0，界面显式区分"待补 / 已配 0"
- 计算引擎放 `shared/`，前后端同一份
- 乐观锁 + 审计触发器
- 单位/di 内部精度与展示精度分离

**要改的**：
- `cost-engine.ts` 里的公式（换成你的成本构成：材料+人工+能耗+折旧…）
- 参数表的字段（`loss_multiplier` → 你的"收率/工时/能耗单耗"）
- 规范化别名表
- 界面单位与小数位

**新行业落地前的三个确认**（这三条错了，代码全白写）：
1. 损耗/收率是"除"还是"乘"？基数是投料还是产出？
2. 毛利类指标的分母是售价还是成本？原表用的是哪个？
3. 缺数据时业务方希望看到"待完善"还是"按 0 估算"？（成本类应用一律选前者）
