# 交付与验收清单

每次改动上线前照着走，每一步都要**看到真实输出**，不能"应该没问题"。

---

## A. 代码检查（改完立刻跑）

```bash
npm run type:check          # tsc --noEmit，前后端并行（server + client 两个 project）
npm run eslint              # eslint . --quiet
npm run stylelint           # stylelint client/src/**/*.css --quiet
npm run build               # 完整构建（server + client）
```

Windows 上 `npm run lint` / `npm run type:check` 的子进程会报 EINVAL，直接跑等价命令：

```powershell
node node_modules/typescript/bin/tsc --noEmit --project tsconfig.node.json
node node_modules/typescript/bin/tsc --noEmit --project tsconfig.app.json
node node_modules/eslint/bin/eslint.js . --quiet
node node_modules/stylelint/bin/stylelint.mjs "client/src/**/*.css" --quiet
```

通过标准：0 error。warning 要么修，要么在提交说明里写清原因。

---

## B. 逻辑测试（纯函数优先）

计算引擎、解析器这类不依赖 IO 的逻辑，用 node 内置 test 跑：

```bash
node --test tests/*.test.mjs
```

成本核算台的两组测试值得抄格式：
- `cost-engine.test.mjs`：含缺价、零价、失效配方、损耗口径、毛利率 vs 成本加成率
- `formula-parser.test.mjs`：表头缺失、单位换算（kg/g）、错误单元格、超规模

原则：**边界值全部落在测试里**（0、null、负数、重复项），因为这些正是业务方会问"为什么算出来不对"的地方。

---

## C. 接口实测（浏览器优先）

- 依赖登录身份的接口：**用浏览器**打开页面点一遍，别用 curl（拿不到 user header）
- 不依赖身份的接口：curl 要带双提交 CSRF，且打**前端端口**

```bash
curl -H 'Cookie: suda-csrf-token=x' -H 'X-Suda-Csrf-Token: x' \
     http://localhost:<CLIENT_DEV_PORT><CLIENT_BASE_PATH>/api/cost/dashboard
```

- 每个写接口至少验：正常保存、版本冲突（409）、非法输入（400）、无权限（403）
- 手机端页面在 320 / 390 / 1280 三档宽度各看一遍：无横向溢出、底部导航不遮挡内容、切页后回到顶部

---

## D. 数据备份（动线上数据前必做）

```
backups/
├── <时间点>-before-import/      # 五张表 data / schema / export-result + manifest.json
└── <时间点>-after-delivery/     # 导入后同样一份，用于核对
```

`manifest.json` 至少记：表名、行数、内容哈希、导出时间、导出人。
验证方式：导出后重新读取比对哈希，确认 10 个文件都能校验通过。

---

## E. 发布三步（缺一步都不算成功）

```bash
git status                                   # 工作区必须干净
git add -A && git commit -m "feat: ..."
lark-cli apps +release-create --app app_xxx
lark-cli apps +release-status --app app_xxx     # 轮询
lark-cli apps +db-diff --app app_xxx --from dev --to main
```

放行判据：

| 检查项 | 通过标准 |
|---|---|
| release-status | `status: finished`，`error_logs: []`，`commit_id` 与本地 `git rev-parse HEAD` 一致 |
| db-diff | `changes: []` |
| 线上 URL | `https://<tenant>.feishuapp.com/app/app_xxx` 能打开并完成登录 |
| 结构差异 | 有 `CREATE_TABLE/ALTER_TABLE` 残留 → 补 DDL 后重新 diff |

发布是异步的：`publishing` 只代表已受理。

---

## F. 触发器验收（如果这次动了自动化）

按顺序，一个都不能跳：

1. `CREATE` → 确认状态（默认 `inactive`）
2. `ENABLE` → `GET` 回读 `Active=true`
3. 确认代码已**发布**（触发器只打线上版本）
4. 等一轮真实投递（或请用户在自动化面板点"测试"）
5. 看投递结果：`trace_id`、`action_status: succeed`、业务计数（`checked/updated`）
6. 回读业务数据：时间戳、条数、关键字段是否按预期变化

判定标准示例（本项目首轮 cron）：

```json
{ "enabled": true, "cron": "7,37 * * * *", "timezone": "Asia/Shanghai",
  "firstCronRunTime": "2026-11-10T18:43:38+08:00",
  "traceId": "c609a4...", "actionStatus": "succeed",
  "checked": 2, "updated": 0 }
```

`updated: 0` 且 `checked: 2` 是**正常**的（源文件没变），不要当成失败。
"触发器创建了但没跑过"不能写成"已启用"。

---

## G. 证据留存

每个关键动作落一个 JSON 到 `analysis/`，命名即用途：

```
analysis/
├── release-create.json / release-status.json / db-diff-final.json
├── cloud-trigger.json / cloud-schedule-verification.json
├── source-states-verification.json          # 手动同步前后状态
├── ui-verification.json                     # 界面验收（分辨率、操作、结果）
├── db-diff-before.json                      # 建表语句原文（回滚参考）
└── seed.json / workbooks.json               # 导入源快照
```

写证据时**区分"已验证"与"未验证"**：开发态界面通过 ≠ 正式手机端通过；数据库回读通过 ≠ 用户实际点过按钮。状态文档里要写清是哪一种。

---

## H. 状态文档（项目根一份，长期维护）

`搭建状态与恢复.md` 至少要能回答：

- 当前 release id / commit / 线上入口 / 管理入口
- 数据规模（各表行数、配方条数、待完善项）
- 同步机制现状（cron 表达式、时区、最近成功时间、错误）
- 本轮改了什么、验了什么、没验什么
- 本地怎么恢复（启动脚本、端口、日志位置）
- 已知限制与待办

新条目写顶部，旧的往下沉，形成时间线。

---

## I. 交付前自查（打勾）

- [ ] typecheck / eslint / stylelint / build 全绿
- [ ] 逻辑测试含边界值且通过
- [ ] 三个聚合文件没有并发改动的痕迹
- [ ] `schema.ts` 与线上结构一致（db-diff 为空）
- [ ] 缺数据场景显示"待完善"而非 0
- [ ] 错误文案指向具体动作
- [ ] 320 / 390 / 1280 三档无溢出、导航不遮挡
- [ ] 写操作 `retry: false`
- [ ] 触发器（若有）已 ENABLE 并回读
- [ ] 备份与证据 JSON 已落盘
- [ ] 状态文档已更新
