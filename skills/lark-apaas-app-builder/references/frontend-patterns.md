# 前端写法（React 19 + tailwind + shadcn/ui）

成本核算台的业务前端只有 5 个文件，其余是平台模板（`business-ui` / `ui`）。这套结构够用且好维护，直接抄。

```
client/src/
├── app.tsx                      # 路由（聚合文件，串行改）
├── api/index.ts                 # 唯一请求出口（聚合文件，串行改）
├── pages/<name>/
│   ├── index.tsx                # 页面（可含多个"页签"，按 pathname 切）
│   ├── use-<name>.ts            # useQuery / useMutation / 格式化函数
│   ├── <Name>Editor.tsx         # 行内编辑弹窗
│   ├── <Name>Detail.tsx         # 详情弹窗
│   └── <name>.css               # 页面样式（少量，其余走 tailwind）
└── lib/api-error.ts             # 统一错误文案提取
```

---

## 1. 路由：一个页面多个入口页签

移动端现场用，底部导航比多级页面好。三个路由指向同一个页面组件，用 `location.pathname` 切页，比拆三个文件更省事、切换无白屏。

```tsx
// app.tsx
<Routes>
  <Route element={<Layout />}>
    <Route index element={<CostPage />} />
    <Route path="materials" element={<CostPage />} />
    <Route path="sources" element={<CostPage />} />
  </Route>
  <Route path="*" element={<NotFound />} />
</Routes>
```

```tsx
// 页面内
const { pathname } = useLocation();
const page = pathname.endsWith('materials') ? 'materials'
           : pathname.endsWith('sources') ? 'sources' : 'products';
```

底部导航用 `NavLink`（自动 active），切换时顺手重置筛选状态：

```tsx
<nav className="bottom-nav" aria-label="主导航">
  <NavLink to="/" end onClick={reset}><Calculator /><span>成本</span></NavLink>
  <NavLink to="/materials" onClick={reset}><FlaskConical /><span>原料</span></NavLink>
  <NavLink to="/sources"><Link2 /><span>关联</span></NavLink>
</nav>
```

禁令：禁止 `React.lazy`、禁止 `window.location.href` 跳转（用 `NavLink`/`useNavigate`）、分享链接必须 `resolveAppUrl()`。

---

## 2. 请求出口与 hook

```ts
// api/index.ts
const request = async <T,>(method: string, path: string, data?: unknown): Promise<T> => {
  const r = await axiosForBackend({ url: `/api/cost/${path}`, method, data });
  if (r.status >= 400) throw new Error(r.data?.error?.message ?? '请求失败，请重试');
  return r.data;
};
export const getDashboard = (): Promise<DashboardResponse> => request('GET', 'dashboard');
export const updateMaterial = (id: string, data: MaterialUpdate) =>
  request('PATCH', `materials/${encodeURIComponent(id)}`, data);
```

```ts
// use-<name>.ts
export const useCostData = () => useQuery({
  queryKey: ['cost-dashboard'],
  queryFn: getDashboard,
  refetchInterval: 15000,            // 看板类页面 15s 轮询，够实时又不吵
  refetchIntervalInBackground: false,
  retry: 1,
});

export const useCostSave = (done?: () => void) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (task: () => Promise<unknown>) => task(),   // 把写请求包成 thunk，复用一套保存逻辑
    retry: false,                                           // 平台默认会重发写请求 → 必须关
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['cost-dashboard'] });
      toast.success('已保存，相关成本已重新计算');
      done?.();
    },
    onError: (e: unknown) => toast.error(errorMessage(e)),
  });
};
```

要点：
- `axiosForBackend` 是**函数**，不是实例：`axiosForBackend({url, method, data})`，写 `.get()` 会 TypeError
- 禁止 `fetch`、禁止 mock 数据、禁止硬编码 `user_xxx` 这类占位 ID
- 写操作一律 `retry: false`；成功后 `invalidateQueries` 而不是手动 setState

---

## 3. 统一错误文案

```ts
// lib/api-error.ts
export function getApiErrorMessage(error: unknown, fallback = '操作失败，请稍后重试'): string {
  const body = (error as { response?: { data?: ApiErrorBody } }).response?.data;
  const detail = body?.error;
  if (typeof detail?.message === 'string' && detail.message.trim()) return detail.message;
  for (const messages of Object.values(detail?.fieldErrors ?? {})) {
    const first = messages?.find((m) => typeof m === 'string' && m.trim());
    if (first) return first;
  }
  return fallback;
}

// 403 统一口吻
if (status === 403) return '无操作权限，请检查登录账号和应用访问范围';
```

页面错误态、`toast.error`、catch 全用这一个函数，不在每个文件重写。

---

## 4. 三态渲染（必做）

```tsx
{query.isLoading ? (
  <div className="loading-layout">
    <Skeleton className="h-32 w-full rounded-xl" />
    <Skeleton className="h-12 w-full rounded-xl" />
    <Skeleton className="h-48 w-full rounded-xl" />
  </div>
) : query.isError ? (
  <div className="empty-state" role="alert">
    <AlertCircle /><h2>数据暂时未能加载</h2>
    <p>{errorMessage(query.error)}</p>
    <Button onClick={() => query.refetch()}>重新加载</Button>
  </div>
) : query.data && (
  <>...</>
)}
```

- 首屏依赖远程数据 → 骨架屏按最终布局占位（卡片/列表/表格），别用转圈
- 本地轻量数据 → 直接条件渲染
- 空结果给"没有匹配的型号，试试缩短关键词"这种**下一步提示**，不要只写"暂无数据"

---

## 5. 编辑弹窗（受控 + 本地预览）

```tsx
export function MaterialEditor({ material, scope, categories, onClose }: Props) {
  const [price, setPrice] = useState(material?.price == null ? '' : String(material.price));
  const save = useCostSave(onClose);

  const submit = () => {
    if (!name.trim() || !code.trim()) { toast.error('请填写原料代号和名称'); return; }
    const value = price.trim() === '' ? null : Number(price);     // 空=缺价，0=明确为零
    if (value !== null && (!Number.isFinite(value) || value < 0)) { toast.error('单价请输入不小于 0 的数字'); return; }
    save.mutate(() => material
      ? updateMaterial(material.id, { ...payload, version: material.version })
      : createMaterial({ ...payload, scope, code: code.trim(), erpCode: '' }));
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !save.isPending) onClose(); }}>
      <DialogContent className="cost-dialog">
        <DialogTitle>{material ? '编辑原料' : '新增原料'}</DialogTitle>
        <DialogDescription>{SCOPE_LABELS[scope]}价格库 · 修改后立即更新关联产品成本</DialogDescription>
        <label className="field">含税单价（元/kg）
          <Input inputMode="decimal" value={price} placeholder="未填表示缺价，0 表示明确为零"
                 onChange={(e) => setPrice(e.target.value)} />
        </label>
        <Button className="primary-action" onClick={submit} disabled={save.isPending}>
          {save.isPending ? '保存中…' : '保存并重算'}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
```

- 弹窗用 `Dialog`，禁止 `alert`/`confirm`/`prompt`
- 输入框用 shadcn `Input`/`Textarea`/`Select`，禁止原生标签
- 数字用 `inputMode="decimal"` + 手动校验（`Number.isFinite`、`< 0`）
- 空值与 0 必须区分：`''` → `null`（缺数据），`'0'` → `0`（真实为零）
- `isPending` 时禁用按钮并改文案，防止重复提交

---

## 6. 详情弹窗内做即时计算

```tsx
const parsed = useMemo(() => ({
  lossMultiplier: factor.trim() ? Number(factor) : null,
  fees: fees.map((f) => ({ label: f.label, amount: f.amount.trim() ? Number(f.amount) : NaN })),
}), [factor, fees]);

const cost = useMemo(() => calculateCost(product, materials, parsed), [product, materials, parsed]);
```

`calculateCost` 来自 `@shared/cost-engine` —— 和后台同一份函数。用户拖一个系数，成本数字实时变，保存后后台算的结果完全一致。

---

## 7. 数字与时间格式化

```ts
export const money = (v: number | null, digits = 2): string =>
  v === null ? '待完善' : v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const dateTime = (v: string | null): string => v
  ? new Date(v).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  : '尚未同步';
```

- `null` 一律显示"待完善/未填"，**绝不显示 0**
- 单位在界面上写清：元/kg 显示 4 位小数，元/吨显示 2 位
- 时区固定 `Asia/Shanghai`，别用浏览器本地时区

---

## 8. 移动端布局（底部导航贴底，别再用悬浮）

真实踩过的坑：底部导航做成悬浮覆盖，会挡住列表最后一行，且和平台浮标打架。

```css
.cost-app { display: flex; flex-direction: column; height: 100dvh; }   /* 用 dvh 不用 vh */
.cost-main { flex: 1; overflow-y: auto; overscroll-behavior: contain; } /* 主区独立滚动 */
.bottom-nav {
  flex: none;
  display: grid; grid-template-columns: repeat(3, 1fr);
  padding-bottom: env(safe-area-inset-bottom);                          /* 避开安全区 */
  border-top: 1px solid hsl(var(--border));
  background: hsl(var(--background));
}
```

- 应用容器 `100dvh` 纵向 flex，主区独立滚动，导航占独立空间 —— 不覆盖内容
- 页面切换时主区回到顶部（`<main key={page}>`）
- 验收宽度：320 / 390 / 1280 三档，检查无横向溢出、切换后不被导航遮挡
- 断网/登录失效时给明确文案 + 重试按钮，不要空白

---

## 9. 无障碍（读屏和自动验收都靠它）

- 纯图标按钮必须 `aria-label`，写清动作：`aria-label="刷新数据"`、`aria-label={`编辑原料${m.code}`}`
- 可切换的按钮/页签用 `aria-pressed`，可选中卡片用 `role="radio"` + `aria-checked`
- 能点的东西用 `Button`/`Link`，不要给 `div` 加 `onClick`
- 图片 `alt` 要能区分同类项，装饰图 `alt=""`
- 表单字段用 `label` 关联，错误文案贴在字段下方

---

## 10. 组件与样式边界

- `components/ui/*`（shadcn）：功能照用，样式大胆改
- `components/business-ui/*`（用户/部门）：**必须用**，禁止自拼头像/选人控件
- 图标只用 `lucide-react`
- 颜色用语义 token（`bg-primary`），禁 `bg-[--primary]`；arbitrary value 里空格写成下划线
- 禁止 Card 套 Card；`justify-between` 必须配 `gap`
- 顶部/分区容器加 `data-ai-section-type`（`card-stat` / `card-list` / `menu`），平台识别用
