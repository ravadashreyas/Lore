<!--
This file is a byte-for-byte copy of `editableProperties.description` read back via
GraphQL from the real fct_orders dataset urn
(urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.fct_orders,PROD))
after running the retain workflow's doc-block step (skill/datahub-memory/SKILL.md
Workflow 2 Step 4 / protocol/SPEC.md §5.2): render every current table-level learning
from the structured property, splice it between the `<!-- agent-memory:begin/end -->`
markers. This was the first-ever write on this entity (description was previously
null), so the splice logic appended the whole block with no separator needed.
Produced by demo-seed/wave4 on 2026-07-29. Everything below this comment is exactly
what a viewer sees rendered as the dataset's description in the DataHub UI.
-->

<!-- agent-memory:begin -->
## Agent learnings

_Distilled by agents via the agent-memory protocol. Machine-generated — do not hand-edit; edits will be overwritten on the next write._

### `metric_definition` — `table` (confidence: high)
**Claim:** 'Revenue' = status='completed' orders only (excludes cancelled and refunded), amount/100, summed by order_date.
**Evidence:** Cross-checked against finance dashboard for 3 distinct months; all three matched within $1.
**Learned by** `demo-seed/wave4` on 2026-07-29 — id `9c1d2e3f-5a6b-4c7d-8e9f-0a1b2c3d4e5f`

### `verified_query` — `table` (confidence: high)
**Claim:** Monthly revenue: SELECT SUM(amount)/100.0 FROM fct_orders WHERE status='completed' AND date_trunc('month', order_date)=:month
**Evidence:** June 2026 result ($38,604,332.17) matched finance dashboard export to the cent.
**Learned by** `demo-seed/wave4` on 2026-07-29 — id `b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e`
<!-- agent-memory:end -->
