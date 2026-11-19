---
name: cost-workspace-runbook
description: 成本核算台（飞书妙搭 app_17hsmznx2jc）的总入口。遇到任何与核算台相关的问题——配方不更新、价格不对、页面打不开、桌面图标失效、同步报错——先看这里的故障速查表，再按索引跳到对应专项技能。也用于日常运维检查（触发器、数据源、价格漂移、备份）。不用于从零搭建新应用（那是 lark-apaas-app-builder）或纯经营分析（那是 cost-analysis）。
whenToUse: 用户提到成本核算台、配方关联、原料单价、ERP 同步、云端连接异常、桌面端打不开，或要做核算台的例行检查与维护。
---

# 成本核算台运行手册

一个飞书妙搭全栈应用，把飞书配方表 + 金蝶 ERP 采购价 + 本台维护的成本参数，合成配方成本核算。三类产品：沉淀胶、气相胶、液体胶。

**遇到问题先查本文的「故障速查」**，定位后再跳到专项技能。

## 一、关键坐标

| 项 | 值 |
|---|---|
| 应用 ID | `app_17hsmznx2jc` |
| 正式入口 | https://hcn82bpt6wbe.feishuapp.com/app/app_17hsmznx2jc |
| 管理后台 | https://miaoda.feishu.cn/app/app_17hsmznx2jc |
| 项目根 | `F:\codex工作区\01-生产研发与企业系统\成本核算台` |
| 源码 | `app/`（分支 `sprint/default`） |
| 状态文档 | `搭建状态与恢复.md`、`液体胶与ERP价格接入方案.md` |
| 本地开发 | `analysis/start-dev.cjs`，前端 8149 / Nest 3049 |

### 数据源

| 产品 | 飞书配方文件 token | 状态 |
|---|---|---|
| 沉淀胶 precipitated | `URHwbLNYIoyOgyx5rm2cm7UJnXb` | 在用 |
| 气相胶 fumed | `EfGdbidSaoGPETxxYY5ceMiqnwb` | 在用 |
| 液体胶 liquid | `cost_sources.liquid` 占位行 | **drive_token 待填** |

### 触发器（Asia/Shanghai）

| 名称 | cron | 作用 |
|---|---|---|
| `cost-formula-refresh` | `7,37 * * * *` | 每 30 分钟拉飞书配方 |
| `cost-erp-price-refresh` | `23 * * * *` | 每小时拉金蝶采购价 |

### 外部系统

- 金蝶云星空：`https://changlian.ik3cloud.com/K3Cloud`，账套 `5c20de882b6156`，凭据在 Windows 凭据管理器 `EDP/Kingdee/InventoryRead`
- 飞书自建应用：`cli_aa785689a83add07`（名称「成本台配方只读连接」），密钥在 `private/feishu-source.env`

## 二、业务口径（改代码前必须清楚）

- **配方只读**：来自飞书源表，本台不改源文件
- **本台维护**：原料价格与分类、加工费用、耗用系数、售价
- **核算公式**：核算产出 = 总投料 ÷ 耗用系数；原料每吨成本 = 批原料金额 ÷ 核算产出 × 1000；再加每吨加工费用
- **缺价不补零**：缺失单价或参数显示「待完善」，不用相近型号猜值
- **毛利率分母是售价**；旧表的「成本加成率」分母是成本，两者不要混
- **价格三层**：`erp_price`（ERP 原值，永远保留）/ `price`（生效价）/ `price_locked` + `price_source`（manual\|erp\|seed）。人工改价会把 `price_locked` 置 true，同步不再覆盖
- **取价口径**：已审核未作废的采购订单中，该物料最近一次成交含税价，统一元/kg；非 kg 计量跳过
- **同名型号**：只警告不阻止核算，卡片显示行号区分

## 三、故障速查

按症状找，先做「第一动作」，再看专项技能。

| 症状 | 第一动作 | 专项技能 |
|---|---|---|
| 某类配方不更新，卡片提示「没有该源文件的读取权限」 | 用应用身份直测下载该文件 | `feishu-app-drive-permission` |
| 页面顶部「云端连接异常」 | 查 `cost_sources.last_error`（SQL 见下） | `feishu-app-drive-permission` |
| 配方数变少/没变化 | 对比 `last_success_at` 与源文件修改时间 | — |
| ERP 价格不动 | 查触发器状态 + 金蝶登录是否成功 | `kingdee-k3cloud-readonly` |
| 某些原料价格突然大幅变动 | 查 `price_source` 与 `price_locked`，属正常同步；不对就锁定 | — |
| 桌面图标打不开、白屏转圈 | 确认快捷方式指向 Edge `--app` 而非独立 exe | 本文第五节 |
| 网页/工具全部打不开、一直转圈 | 查 `http_proxy` 环境变量指向的端口是否还活着 | 本文第五节 |
| 改了代码但界面没变 | 是否发布了 release？结构变了要跑 DB 迁移 | `lark-apaas-app-builder` |
| 数据库结构报错 | 检查 dev/online 是否都执行了 DDL | `miaoda-rd-data-lifecycle` |

### 查数据源状态

```bash
lark-cli apps +db-execute --app-id app_17hsmznx2jc --environment online \
  --sql 'SELECT id, last_error, checked_at, last_success_at FROM cost_sources ORDER BY id' --yes
```

### 查 ERP 同步状态

```sql
SELECT * FROM cost_erp_sync ORDER BY id DESC LIMIT 5;
SELECT erp_code, price, erp_price, price_source, price_locked, erp_synced_at
FROM cost_materials WHERE erp_code IS NOT NULL ORDER BY erp_synced_at DESC LIMIT 20;
```

## 四、日常运维清单

**每周**
- 看 `cost_sources.last_success_at` 是否在 1 小时内（两个源）
- 看 `last_error` 是否为空
- 看 ERP 价格变动超 ±10% 的物料，确认是真实行情还是脏数据

**每月**
- 备份五张核心表（`backups/` 目录，参考 `miaoda-rd-data-lifecycle`）
- 核对配方数与飞书源表行数是否一致
- 检查「待完善」清单（缺价原料、缺参数型号）是否在收敛

**改动后必做**
1. 本地 `analysis/start-dev.cjs` 起服务验证
2. typecheck / ESLint / build
3. 结构变更先跑 DDL（dev → `db-env-migrate` → online DML）
4. 发布 release，核对 commit SHA 与 DB diff 为空
5. 触发器 GET 回读确认 enabled

## 五、两个高频环境坑

### 1. 桌面端：用 Edge --app，不要用独立 exe

独立 WebView2 exe 是全新浏览器环境，需要重新扫码登录，而且登录页经常加载不出来（白屏转圈）。Edge `--app` 模式复用日常登录态，直接进。

快捷方式正确 targets：

```
目标: C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
参数: --app="https://hcn82bpt6wbe.feishuapp.com/app/app_17hsmznx2jc" --window-size=1400,900
```

### 2. 死代理：VPN 欠费后端口还在环境变量里

症状：所有网页和 CLI 都卡住转圈，报 `Connection refused 127.0.0.1:xxxxx`。

```powershell
# 查
[Environment]::GetEnvironmentVariable('https_proxy','User')
Test-NetConnection 127.0.0.1 -Port <该端口>

# 清
[Environment]::SetEnvironmentVariable('http_proxy',$null,'User')
[Environment]::SetEnvironmentVariable('https_proxy',$null,'User')
```

注意：DSH / 终端进程可能仍带着旧环境变量，需要重启才彻底干净。命令里临时清：`Remove-Item Env:http_proxy,Env:https_proxy`。

## 六、技能索引

| 要做的事 | 用哪个技能 |
|---|---|
| 加功能、改页面、发布上线 | `lark-apaas-app-builder` |
| 配方/成本台的端到端交付或跨模块修复 | `miaoda-rd-platform-delivery` |
| 数据迁移、备份、回滚、编号连续性 | `miaoda-rd-data-lifecycle` |
| 金蝶 ERP 取数、字段报错 | `kingdee-k3cloud-readonly` |
| 飞书文件读不了、权限 403 | `feishu-app-drive-permission` |
| 月度经营/毛利/成本分析 | `cost-analysis` |
| **遇到任何问题不知道从哪下手** | 本文 |

## 参考

- `references/system-map.md` —— 数据流图、表结构、代码模块位置
- `references/incident-log.md` —— 历史故障与处理记录（新的追加在后面）
