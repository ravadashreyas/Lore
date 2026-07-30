# clients/recall.py

A standalone, stdlib-only Python recall client for the Agent Memory on DataHub
protocol, built from **`protocol/SPEC.md` alone**. No other file in this repo was
read to write it.

## What this proves

The protocol spec claims that "an independent implementation — a different skill, a
different agent framework, a different language — can read and write compatible
learnings against a DataHub instance without reference to any other file in this
repo." This client is that proof for the read side: every design decision in
`recall.py` — the structured-property id (`io.datahub.agentMemory.learnings`), the
learning record's JSON shape (SPEC §4), the recall scope (table + schemaField, one
lineage hop upstream, SPEC §6), skip-and-warn parsing of malformed entries (SPEC §6),
and surfacing `disputed`/`conflict` status instead of silently picking a side (SPEC
§8) — is traceable to a specific section of `SPEC.md`. The exact GraphQL shapes
(`entity(urn)`, `... on Dataset { structuredProperties }`, `... on SchemaFieldEntity`,
`searchAcrossLineage`) were derived from public DataHub GraphQL API knowledge and
confirmed by introspecting the live GMS — not from reading the skill's implementation.

## What this deliberately doesn't do

- **No write path (retain).** SPEC §7's retain workflow — distilling and writing new
  learnings, the dedupe check, the read-merge-write semantics for structured
  properties — is out of scope. This client is read-only by design, to keep the proof
  minimal and because the task requires no writes to DataHub.
- **No documentation-block rendering** (SPEC §5.2). Only the structured-property
  values are read; the human-readable markdown block on the entity description is not
  parsed or rendered.
- **No automatic conflict resolution.** Per SPEC §8's consumer guidance, conflicting
  learnings are always shown side by side with their status flagged; the client never
  picks a "winning" side.
- **No caching, retries, or auth.** One request per entity, no session state. Add an
  `Authorization` header yourself if your GMS requires a token.

## Usage

```
python clients/recall.py <dataset-urn> [--gms http://localhost:8080] [--upstream]
```

## Real output

Against a local DataHub OSS instance (`http://localhost:8080`, unauthenticated):

```
$ python clients/recall.py 'urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.features_customer_ltv,PROD)' --upstream

=== urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.features_customer_ltv,PROD) (0 learnings) ===
  (none)

=== dim_customers (upstream of urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.features_customer_ltv,PROD)) (0 learnings) ===
  (none)

=== fct_orders (upstream of urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.features_customer_ltv,PROD)) (3 learnings) ===

-- confidence: high --
[metric_definition] table
  claim:    'Revenue' = status='completed' orders only (excludes cancelled and refunded), amount/100, summed by order_date.
  evidence: Cross-checked against finance dashboard for 3 distinct months; all three matched within $1.
  by demo-seed/wave4 on 2026-07-29  (id 9c1d2e3f-5a6b-4c7d-8e9f-0a1b2c3d4e5f)
[verified_query] table
  claim:    Monthly revenue: SELECT SUM(amount)/100.0 FROM fct_orders WHERE status='completed' AND date_trunc('month', order_date)=:month
  evidence: June 2026 result ($38,604,332.17) matched finance dashboard export to the cent.
  by demo-seed/wave4 on 2026-07-29  (id b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e)
[semantic_gotcha] amount
  claim:    Values are stored in cents, not dollars; divide by 100 for a dollar amount.
  evidence: SUM(amount) for completed June 2026 orders = 3,860,433,217 vs. finance dashboard $38,604,332; ratio exactly 100.
  by demo-seed/wave4 on 2026-07-29  (id 3f9a2b1c-4d5e-4f60-8a11-9b2c3d4e5f60)
```

`features_customer_ltv` itself has no learnings yet, but `--upstream` correctly walks
one lineage hop and recalls `fct_orders`' two table-level learnings plus its
column-scoped `amount` learning (fetched via the `SchemaFieldEntity` GraphQL path,
SPEC §6's implementation note) — exactly the scenario SPEC §6 describes: an agent
about to query `features_customer_ltv` inherits the unit-conversion gotcha from its
upstream source table without re-deriving it. `dim_customers` is also one hop
upstream of `features_customer_ltv` and is included automatically by the lineage
query; its learning count fluctuated between test runs (2 disputed/conflict
learnings in one run, 0 in another) because another agent was concurrently writing
to it during this test — expected, and out of scope for this client's own testing.

Plain dataset-level + column-scoped recall, no lineage walk:

```
$ python clients/recall.py 'urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.fct_orders,PROD)'

=== urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.fct_orders,PROD) (3 learnings) ===

-- confidence: high --
[metric_definition] table
  claim:    'Revenue' = status='completed' orders only (excludes cancelled and refunded), amount/100, summed by order_date.
  evidence: Cross-checked against finance dashboard for 3 distinct months; all three matched within $1.
  by demo-seed/wave4 on 2026-07-29  (id 9c1d2e3f-5a6b-4c7d-8e9f-0a1b2c3d4e5f)
[verified_query] table
  claim:    Monthly revenue: SELECT SUM(amount)/100.0 FROM fct_orders WHERE status='completed' AND date_trunc('month', order_date)=:month
  evidence: June 2026 result ($38,604,332.17) matched finance dashboard export to the cent.
  by demo-seed/wave4 on 2026-07-29  (id b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e)
[semantic_gotcha] amount
  claim:    Values are stored in cents, not dollars; divide by 100 for a dollar amount.
  evidence: SUM(amount) for completed June 2026 orders = 3,860,433,217 vs. finance dashboard $38,604,332; ratio exactly 100.
  by demo-seed/wave4 on 2026-07-29  (id 3f9a2b1c-4d5e-4f60-8a11-9b2c3d4e5f60)
```

An earlier test run against `dim_customers` (encountered only as an upstream entity,
not as a primary test target) happened to catch it mid-conflict, which is a good
illustration of SPEC §8 in action — both sides of a contradiction rendered, neither
silently preferred:

```
-- confidence: high --
[join_path] table  [DISPUTED -- a conflicting learning exists for this subject/kind]
  claim:    Join on customer_key, not customer_id; customer_id is legacy and 47% NULL
  evidence: SELECT count(*) FILTER (WHERE customer_id IS NULL)::float / count(*) FROM ecommerce.dim_customers = 0.47 (47 of 100 rows NULL)
  by demo-seed/conflict-example on 2026-07-29  (id dbe03649-6067-4b30-818a-298105a65f46)

-- confidence: medium --
[join_path] table  [CONFLICT -- contradicts id dbe03649-6067-4b30-818a-298105a65f46]
  claim:    customer_id was backfilled from customer_key on 2026-07-29; prior join guidance may be stale, but backfill correctness is unverified
  evidence: SELECT count(*) FILTER (WHERE customer_id IS NULL)::float / count(*) FROM ecommerce.dim_customers = 0.0 (0 of 100 rows NULL), after UPDATE ... affected 47 rows
  by demo-seed/conflict-example on 2026-07-29  (id 0ca7654e-4966-4b49-9392-9fcab10ff7e6)
```

## Error handling

```
$ python clients/recall.py '<urn>' --gms http://localhost:9999
error: could not reach DataHub GMS at http://localhost:9999: <urlopen error [WinError 10061] No connection could be made because the target machine actively refused it>
$ echo $?
1
```
