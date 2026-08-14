---
name: silicone-rubber-process-diagnosis
description: Diagnose silicone rubber manufacturing process abnormalities and quality defects. Use when the user asks about silicone rubber defects, molding issues, vulcanization or curing problems, mold sticking, bubbles, flash, short shot, tearing, under-cure, over-cure, dimension drift, color difference, material batch variation, process parameter instability, or root-cause troubleshooting for silicone rubber production.
---

# Silicone Rubber Process Diagnosis

Use this skill to diagnose silicone rubber production defects and convert symptoms into a practical troubleshooting sequence.

## First collect facts

Ask only when critical data is missing. Otherwise proceed with assumptions clearly marked.

Collect or infer:

- Product, material grade, hardness, color, batch, storage time, and compound supplier.
- Process route: compression molding, transfer molding, injection molding, extrusion, secondary vulcanization, trimming, inspection, or assembly.
- Machine, mold number, cavity, operator, shift, start time, and abnormal start point.
- Parameters: temperature, pressure, curing time, exhaust/venting, feeding weight, mold release, cycle time, and first-piece result.
- Defect description: location, frequency, cavity concentration, trend, photos if available, and whether it appears after material, mold, machine, or operator change.

## Diagnosis logic

Use this order unless the symptom clearly points elsewhere:

1. Confirm defect pattern: single cavity, whole mold, single batch, single shift, single machine, or all lines.
2. Separate sudden change from chronic issue.
3. Check recent changes: material batch, mold maintenance, parameter adjustment, operator, machine, environment, and inspection standard.
4. Map the defect to likely source: material, mold, machine, method, manpower, measurement, or environment.
5. Propose fast containment first, then root-cause validation, then permanent correction.

## Common symptom map

- Bubbles or voids: trapped air, poor exhaust, excessive feeding, material moisture/volatiles, insufficient vacuum/degassing, low pressure, short curing, or dirty mold vent.
- Flash: excessive feeding, mold wear, poor clamping, pressure imbalance, parting-line damage, high material flow, or wrong hardness/batch.
- Short shot or缺胶: insufficient feeding, poor flow, low temperature, low pressure, blocked runner/vent, premature scorch, or operator feeding position issue.
- Under-cure: insufficient time, low mold temperature, unstable temperature control, wrong compound, expired material, or thick-section heat transfer issue.
- Over-cure/scorch: excessive temperature/time, material pre-scorch, long residence time, or delayed loading/unloading.
- Sticking mold: release system issue, mold surface contamination, over/under-cure, material formula change, insufficient cleaning, or surface damage.
- Dimension drift: shrinkage variation, temperature fluctuation, curing time drift, material hardness/batch change, post-cure condition, fixture, or measurement method.
- Tearing/demolding damage: under-cure, poor mold release, sharp mold edge, wrong demolding method, low tear strength material, or excessive flash trimming.
- Color difference/surface contamination: material mixing, pigment dispersion, mold contamination, transfer pollution, storage, or cleaning process.

## Output format

Use this format:

1. `初步判断`: top 1-3 likely causes, each tagged as fact or inference.
2. `先做的遏制`: immediate actions to protect delivery and customer quality.
3. `排查顺序`: step-by-step checks from fastest/highest-probability to slower checks.
4. `验证方法`: what evidence confirms or rejects each cause.
5. `临时措施`: parameter, inspection, sorting, or process controls for today.
6. `长期改善`: mold, material, equipment, standard work, training, poka-yoke, and data tracking.
7. `需要补充的数据`: only the data that materially changes the diagnosis.

## Quality bar

Be specific to silicone rubber production. Do not give vague textbook root causes. Prefer a practical sequence that a production director can assign to process, quality, equipment, and workshop owners.
