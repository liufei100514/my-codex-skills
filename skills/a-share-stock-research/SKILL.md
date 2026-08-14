---
name: a-share-stock-research
description: Analyze individual China A-share listed companies for investment or trading decisions. Use when the user provides an A股代码/股票名称 and asks for 个股研究, 基本面, 财报, 估值, 公告解读, 催化剂, 技术位置, 买卖计划, 风险, or whether to watch/buy/hold/sell.
---

# A-share Stock Research

## Workflow

1. Normalize the security identifier. Confirm exchange prefixes for Shanghai, Shenzhen, Beijing, ETFs, and convertible bonds when needed.
2. Gather current evidence before making a call:
   - Latest price, market cap, turnover, recent performance, valuation snapshot.
   - Business segments, revenue/profit trend, margin, cash flow, debt pressure.
   - Recent announcements: earnings preview/report, dividend, buyback, reduction, refinancing, litigation, regulatory letters.
   - Sector context: industry cycle, policy exposure, theme relevance, peer valuation.
3. Build the thesis:
   - Core business quality.
   - Main upside driver.
   - Main downside risk.
   - What the market may already price in.
4. Translate research into action:
   - Suitable style: value, growth, event-driven, theme trade, rebound, or avoid.
   - Entry conditions, invalidation point, stop-loss logic, and position cap.
   - Catalysts and dates to monitor.
5. Mark evidence clearly:
   - "已验证" for current-turn data or files.
   - "来自公告/财报" when sourced from filings.
   - "我的判断" for valuation, sentiment, and trading interpretation.

## Output Shape

Use this structure unless the user requests another format:

1. 一句话结论
2. 公司与业务
3. 财务与估值
4. 公告/事件
5. 股价与资金面
6. 投资逻辑
7. 风险与失效条件
8. 操作计划

## Data Source Preference

Use the `a-share-data` plugin or local scripts where available. For filings, prefer official exchange, 巨潮资讯, or company announcements over reposted summaries. For volatile data such as price, volume, valuation, and rankings, verify live if possible.

## Guardrails

Do not present a single target price as certainty. Do not recommend full-position buying. Separate long-term fundamental conclusions from short-term trade setups. When data is missing, state the gap and avoid overfitting a thesis from price movement alone.
