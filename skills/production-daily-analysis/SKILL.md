---
name: production-daily-analysis
description: Analyze manufacturing production daily reports for production directors and operations managers. Use when the user provides or asks to create a daily production review involving output, plan attainment, yield, labor hours, machine downtime, scrap, rework, delivery risk, shift handover, or next-day production priorities, especially in silicone rubber manufacturing.
---

# Production Daily Analysis

Use this skill to turn raw production records into an actionable daily management report.

## Core workflow

1. Identify the reporting scope: date, workshop, product family, shift, line, machine group, order batch, and responsible supervisor.
2. Extract the core figures: planned output, actual output, attainment rate, good quantity, defective quantity, yield, labor hours, overtime, downtime, scrap, rework, WIP, and urgent orders.
3. Compare actuals against plan, yesterday, weekly average, and known target when available. If a benchmark is missing, state that it is not provided instead of inventing one.
4. Classify exceptions by impact: delivery, quality, efficiency, cost, safety, material, equipment, tooling, manpower, process, and coordination.
5. For every major exception, write a short cause hypothesis and mark it as `已验证`, `来自记录`, or `我的推断`.
6. Convert findings into actions: owner, deadline, expected effect, and verification method.
7. End with tomorrow's production focus and escalation needs.

## Silicone rubber focus

When the data involves silicone rubber production, check for recurring causes:

- Vulcanization or curing time, temperature, pressure, exhaust frequency, and mold temperature fluctuation.
- Mold issues: sticking, flash, wear, poor venting, cavity imbalance, cleaning gaps, and changeover delay.
- Material issues: compound batch variation, mixing uniformity, storage time, contamination, color change, hardness drift, and shortage.
- Process issues: feeding weight, trapped air, insufficient degassing, operator method variation, and unstable first-piece approval.
- Quality issues: bubbles, short shot, flash, tearing, scorch, under-cure, over-cure, dimension drift, color difference, and surface defects.

## Output format

Prefer this structure unless the user asks otherwise:

1. `一句话结论`: whether the day was controlled, risky, or abnormal.
2. `核心数据`: plan vs actual, attainment, yield, downtime, scrap/rework, manpower.
3. `主要异常`: list the top 3-5 issues by business impact.
4. `原因判断`: separate facts from assumptions.
5. `改善动作`: action, owner, deadline, validation.
6. `明日重点`: production, quality, equipment, materials, people.
7. `需要升级`: decisions or resources needed from senior management.

## Quality bar

Be concise, numbers-first, and operations-oriented. Do not write generic encouragement. If data is incomplete, still produce a usable report and clearly list missing fields.
