# 故障记录（新的追加在后面）

格式：日期 / 症状 / 根因 / 处理 / 教训

---

## 2026-11-15 · ERP 价格首次同步回来 11 行变动超 ±10%

**症状**：首轮 ERP 同步后，90 行可比对价格里 11 行变动超过 ±10%，最大 S102 气相 14.5→11.55（−20.3%）、P506 33→39（+18.2%）。

**根因**：ERP 里的是"最近一次成交价"，单笔急采或特价会带偏，不代表实际成本。

**处理**：属正常同步结果，不是 bug。对不代表实际成本的原料，在原料编辑弹窗里锁定（`price_locked=true`），后续同步只更新 `erp_price` 不再覆盖 `price`。

**教训**：ERP 原值和生效价必须分开存。只有一层价格的话，同步一跑人工修正就没了。

---

## 2026-11-18 · 沉淀胶配方读不了，气相正常

**症状**：配方关联页显示「飞书应用没有该源文件的读取权限，请添加只读协作者」，顶部「云端连接异常」。气相正常，沉淀停在 11/12 的成功数据。

**排查过程（走了弯路）**：
1. 先怀疑协作者缺失 → 对比两份文件成员列表，沉淀少一个 `view` 成员，补上 → **没解决**
2. 再怀疑应用权限没开 → 去开放平台开通 `drive:drive:readonly`，发布版本 1.0.1、1.0.2 → **没解决**
3. 换思路：拿 app_id + app_secret 取全新 tenant_access_token，**直接调下载接口** → 沉淀 403、气相 200 → 确认是文件级差异
4. 对比两份文件的 `permission.public`，唯一实质差异是 `security_entity`：沉淀 `only_full_access`、气相 `anyone_can_view`

**根因**：`security_entity: only_full_access` 会挡住 `tenant_access_token` 的读取，即使 `link_share_entity` 是 `tenant_readable`。

**处理**：
```powershell
# body 必须无 BOM
[System.IO.File]::WriteAllText($p,'{"security_entity":"anyone_can_view"}',(New-Object System.Text.UTF8Encoding($false)))
lark-cli drive permission.public patch --token URHwbLNYIoyOgyx5rm2cm7UJnXb --type file --data "@$p" --yes
```
改完直测下载：HTTP 200、755,822 字节。

**教训**：
- 报错文案会把人引向协作者，真正的根因在安全设置
- 判断"修没修好"要用应用身份直测，不要看服务端数据库状态（有 25min token 缓存 + 30min cron 周期）
- `lark-cli --data @file` 的 JSON 必须无 BOM

详见技能 `feishu-app-drive-permission`。

---

## 2026-11-18 · 桌面端图标打开白屏转圈

**症状**：双击「成本核算台」桌面图标，窗口出来了但一直是白屏 + 中间一个 logo，转很久进不去。

**根因**：当时快捷方式指向独立 WebView2 exe（`成本核算台.exe`）。它用独立 profile，等于一台没登录过的新电脑，需要重新飞书扫码；而扫码页在当前网络下加载不出来。

**处理**：把快捷方式改成 Edge `--app` 模式，复用日常 Edge 的登录态，直接进。

```
目标: C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
参数: --app="https://hcn82bpt6wbe.feishuapp.com/app/app_17hsmznx2jc" --window-size=1400,900
```

**教训**：内网/受控环境的 Web 应用，优先用现成浏览器的应用窗口模式，不要自己造一个独立浏览器环境——登录态复用不了，反而多一个故障点。

---

## 2026-11-18 · 所有网页和命令行都打不开，一直卡着

**症状**：Edge 打不开页面、curl 全部失败、git push 报 `Connection was reset`。

**根因**：VPN 欠费断流，代理客户端退出，但系统环境变量 `http_proxy` / `https_proxy` 还指向 `http://127.0.0.1:21081`。该端口已无监听，所有读环境变量的程序都卡在这里。

**处理**：
```powershell
Remove-Item Env:http_proxy,Env:https_proxy,Env:HTTP_PROXY,Env:HTTPS_PROXY -ErrorAction SilentlyContinue
[Environment]::SetEnvironmentVariable('http_proxy',$null,'User')
[Environment]::SetEnvironmentVariable('https_proxy',$null,'User')
```
清完直连：飞书 200、金蝶 200、GitHub 网页 200。但 **git 协议仍失败**（TLS 被重置），GitHub 的推送必须靠代理。

**教训**：
- 症状是"打不开"时，先分清三类原因：网站坏 / 网络坏 / **代理配置残留**
- 浏览器读系统代理设置（注册表 `ProxyEnable`），CLI 读环境变量——两者可以不一致
- 清完环境变量后，已启动的终端、DSH 进程仍带旧值，必须新开进程或重启应用
