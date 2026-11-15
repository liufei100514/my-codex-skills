# 后端写法（NestJS + Drizzle）

从成本核算台 5 个业务文件里抽出来的模式，可直接套。

---

## 1. 模块四件套

```
server/modules/<name>/
├── <name>.module.ts
├── <name>.controller.ts     # HTTP 层，薄
├── <name>.service.ts        # 业务 + 数据层，厚
├── <name>.dto.ts            # class-validator 入参
├── <name>.automation.ts     # 有定时/事件任务才加
└── （复杂模块可拆 <name>-sync.service.ts 之类，但业务入口仍是 service）
```

```ts
// <name>.module.ts
@Module({
  imports: [HttpModule],                                   // 调外部 HTTP 才需要
  controllers: [CostController],
  providers: [CostService, CostSyncService, CostAutomation],
})
export class CostModule {}
```

注册到 `server/app.module.ts`：

```ts
@Module({
  imports: [
    PlatformModule.forRoot(),
    CostModule,          // ← 业务模块加在这里
    ViewModule,          // ⚠️ fallback 路由，必须最后
  ],
  providers: [{ provide: APP_FILTER, useClass: GlobalExceptionFilter }],
})
```

---

## 2. Controller：薄、只做绑定和身份

```ts
@Controller('api/cost')
@NeedLogin()
export class CostController {
  constructor(
    private readonly service: CostService,
    private readonly syncService: CostSyncService,
  ) {}

  @Get('dashboard') dashboard() { return this.service.dashboard(); }

  @Patch('materials/:id')
  updateMaterial(@Param('id') id: string, @Body() body: MaterialUpdateDto, @Req() req: Request) {
    return this.service.updateMaterial(id, body, req.userContext.userId!);
  }

  @Post('materials')
  createMaterial(@Body() body: MaterialCreateDto, @Req() req: Request) {
    return this.service.createMaterial(body, req.userContext.userId!);
  }
}
```

- 路径前缀 `api/`（内部）或 `openapi/`（对外，鉴权规则不同）
- 静态路由写动态路由前面（`/search` 在 `/:id` 前）
- Controller 里**不 catch**，抛出去给全局过滤器
- `@Param` 一律 string，需要数字在 controller 里 `Number(id)`

---

## 3. DTO：class-validator + shared 的取值

```ts
export class MaterialUpdateDto implements MaterialUpdate {
  @IsInt() @Min(1) version!: number;
  @IsOptional() @IsNumber() @Min(0) price!: number | null;
  @IsString() @MaxLength(80) categoryId!: string;
  @IsString() @MaxLength(160) displayName!: string;
  @IsString() @MaxLength(2000) notes!: string;
}
```

- 类上 `implements <SharedInterface>`，字段名与 shared 完全一致
- 固定取值：`@IsIn(SCOPES)` 引用 shared 数组；字段类型写内联字面量联合（`'precipitated' | 'fumed'`），不要写 shared 别名
- 嵌套用 `@ValidateNested({ each: true })` + `@Type(() => FeeDto)`
- 列表/筛选用 `@Query() dto`，数字字段 `@Type(() => Number)`；「全部」的空串用 `@Transform` 转 `undefined`，否则 `@IsIn` 会 400

---

## 4. Service：数据访问 + 业务规则

```ts
@Injectable()
export class CostService {
  constructor(@Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase) {}
```

### 聚合读（一次查询拿全量面）

```ts
const [rawMaterials, categories, rawSettings, rawSources] = await Promise.all([
  this.db.select().from(costMaterials).orderBy(costMaterials.code),
  this.db.select().from(costCategories).orderBy(costCategories.name),
  this.db.select().from(costSettings),
  this.db.select().from(costSources),
]);
```

然后把 DB 行**映射成接口类型**（这一步是关键，DB 的 snake_case / string 数字都在这里洗掉）：

```ts
const materials: Material[] = rawMaterials.map((row) => {
  if (!isCostScope(row.scope)) throw new BadRequestException('原料类别数据无效');   // 用 shared 守卫收窄
  return {
    ...row,
    scope: row.scope,
    price: row.price === null ? null : Number(row.price),
    updatedAt: row.updatedAt.toISOString(),
  };
});
```

JSONB 字段（如 `fees`、`formulas`）用 **zod 解析**，不 `as any`：

```ts
const feeSchema = z.array(z.object({ label: z.string(), amount: z.number().finite().nonnegative() }));
const fees = feeSchema.parse(row.fees);
```

### 乐观锁写（防并发覆盖）

```ts
const rows = await this.db.update(costMaterials)
  .set({
    price: price === null ? null : String(price),      // numeric 列写字符串
    updatedBy: actor,
    updatedAt: new Date(),
    version: sql`${costMaterials.version} + 1`,
  })
  .where(and(eq(costMaterials.id, id), eq(costMaterials.version, input.version)))
  .returning({ id: costMaterials.id });
if (!rows.length) throw new ConflictException('该原料已被修改，请刷新后重试，当前输入尚未保存');
```

### 幂等插入（同步补壳 / 防重复）

```ts
const rows = await this.db.insert(costMaterials)
  .values({ id: randomUUID(), scope, code, ... })
  .onConflictDoNothing()
  .returning({ id: costMaterials.id });
if (!rows.length) throw new ConflictException('该类别中已有相同原料代号，请编辑现有原料');
```

### 唯一性预检（给出人话错误，而不是让数据库报 23505）

```ts
const duplicate = await this.db.select({ id: costCategories.id })
  .from(costCategories).where(eq(costCategories.name, name.trim()));
if (duplicate.some((row) => row.id !== id)) throw new ConflictException('已有同名类别');
```

### 审计查询

```ts
return this.db.select({
  id: costAudit.id, entityType: costAudit.entityType, entityId: costAudit.entityId,
  changedAt: costAudit.changedAt, before: costAudit.before, after: costAudit.after,
}).from(costAudit).orderBy(desc(costAudit.changedAt)).limit(50);
```

---

## 5. 异常与错误码

| 层 | 做法 |
|---|---|
| Service | 抛 `BadRequestException`（400，输入/规则）、`ConflictException`（409，版本冲突、重复）、`NotFoundException`（404） |
| Controller | 不处理 |
| 全局 | `GlobalExceptionFilter` 统一成 `{ error: { code, message, details?, fieldErrors?, timestamp } }` |

前端只读 `error.response.data.error.message`，取不到再看 `fieldErrors` 第一条，**不读 axios 的 `error.message`**（那是英文 `Request failed with status code 400`）。

错误文案原则：给用户看得懂的下一步，不输出代码黑话。
- ✅「该原料已被修改，请刷新后重试，当前输入尚未保存」
- ✅「飞书应用的下载文件权限尚未生效，请检查应用身份权限并发布」
- ❌「Error: 23505 duplicate key value」

---

## 6. 日志

```ts
private readonly logger = new Logger(CostSyncService.name);
this.logger.warn(`Source sync failed: ${source.id}; ${message}`);
```

- 后端用 `@nestjs/common` 的 `Logger`（**没有 `info`**，用 `log`）
- 最后一个 string 参数会被当 context；对象自己 `JSON.stringify`
- 禁止 `console.*`；错误日志带堆栈

---

## 7. 外部 HTTP（@nestjs/axios）

```ts
import { HttpModule } from '@nestjs/axios';
import { firstValueFrom } from 'rxjs';

const res = await firstValueFrom(this.http.get<ArrayBuffer>(url, {
  headers: { Authorization: `Bearer ${token}` },
  responseType: 'arraybuffer',
  timeout: 18000,
  maxContentLength: 12 * 1024 * 1024,
}));
```

- 超时、最大体积都要显式设，防止一个坏文件卡死任务
- 错误先判定 `isAxiosError`，把 `response.status` / `response.data.code` 翻成人话（见 `external-sync.md`）

---

## 8. 启动期约束

`bootstrap` / `constructor` / `onModuleInit` / `onApplicationBootstrap` 都在就绪关键路径上：

- ✅ 只做装配、内存初始化、配置校验
- ❌ DDL、下载大文件、全量同步、批量迁移、长轮询
- 「声明成 async」或「`void promise` 甩出去」都不算移出启动流程 —— 要用平台触发器或独立异步任务

---

## 9. 计算结果放在 shared（前后端共用）

```ts
// shared/engine.ts：纯函数，不 import db / axios / DOM
export function calculateCost(formula: Formula, prices: MaterialPrice[], setting: CostParameters | null): CostResult
```

后端一次算全量返回；前端在"用户改参数、还没保存"时用同函数做本地预览。这样口径只有一份，不会出现"预览 18.7、保存后 18.5"。
