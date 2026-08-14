---
name: a-share-daily-review
description: Produce A-share daily market reviews and next-session trading plans. Use when the user asks for A股复盘, 今日A股怎么看, 明日策略, 盘后总结, 指数/成交额/题材/涨跌停/风险信号, or a daily China A-share market decision brief.
---

# A-share Daily Review

## Workflow

1. Verify the trading date and market state. If the request is "today", use the current date and note whether it is intraday, post-close, weekend, or holiday.
2. Gather current evidence before analysis whenever possible. Prefer live data or user-provided files over memory.
3. Cover the core dashboard:
   - Major indices: 上证指数, 深证成指, 创业板指, 沪深300, 科创50 when relevant.
   - Liquidity: total turnover, change versus recent sessions, volume expansion/contraction.
   - Breadth: advancers/decliners, limit-up/limit-down count, high-board height, broken-board rate when available.
   - Themes: strongest sectors and concepts, leader stocks, sustainability, policy/news drivers.
   - Risk: weak sectors, crowding, failed breakouts, index resistance/support, event risk.
4. Separate fact from judgment:
   - Mark data as "已验证" when fetched or provided in the current turn.
   - Mark memory-derived items as "来自记忆".
   - Mark thesis-level conclusions as "我的判断".
5. End with an actionable next-session plan:
   - Market stance: aggressive, balanced, defensive, or wait-and-see.
   - Watchlist buckets: main-line continuation, low-position rotation, risk avoidance.
   - Triggers: what confirms the plan, what invalidates it.
   - Position discipline: suggested exposure range and stop conditions.

## Output Shape

Keep the answer concise and decision-oriented. Use this structure unless the user asks otherwise:

1. 今日结论
2. 市场状态
3. 主线与题材
4. 风险信号
5. 明日计划
6. 需要继续跟踪

## Data Source Preference

If available, use the `a-share-data` plugin or local scripts for market data. Otherwise use live web/API checks with approval when required. Do not present stale index prices, turnover, or sector rankings as current.

## Guardrails

Do not give guaranteed return language. Avoid generic "利好/利空" labels without explaining transmission path. For short-term trading plans, prioritize liquidity, theme strength, market breadth, and invalidation points over broad macro commentary.
