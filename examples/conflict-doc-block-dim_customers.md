<!--
This file is a byte-for-byte copy of `editableProperties.description` read back
via GraphQL from the real dim_customers dataset urn
(urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.dim_customers,PROD))
after actually executing the conflict procedure (protocol/SPEC.md S8,
skill/datahub-memory/SKILL.md Conflict Procedure) end-to-end: a real backfill
migration changed the underlying NULL rate from 47% to 0%, the prior join_path
learning was marked disputed (status field only -- claim/evidence/confidence
untouched), and a new conflict record was written referencing it via
conflicts_with. The block below is the full regeneration described in
protocol/SPEC.md S5.2, rendered by re-running Workflow 2 Step 4 -- note the
DISPUTED and CONFLICT markers required by S5.2 rule 5. The environment was
restored after this was captured (warehouse re-seeded, dim_customers' learnings
and doc block cleared) -- see examples/README.md for full provenance.
Produced by demo-seed/conflict-example on 2026-07-29. Everything below this
comment is exactly what a viewer saw rendered as the dataset's description in
the DataHub UI at capture time.

Errata (capture kept verbatim): the CONFLICT heading below says "supersedes id
...", wording chosen by the renderer before the spec pinned the phrasing. The
protocol now requires "contradicts id ..." (SPEC.md S5.2 rule 5) because a
conflict does not resolve or replace the disputed record -- neither side is
preferred until a human retires one. The capture is preserved as-is rather than
edited, since it is a byte-for-byte readback.
-->

<!-- agent-memory:begin -->
## Agent learnings

_Distilled by agents via the agent-memory protocol. Machine-generated — do not hand-edit; edits will be overwritten on the next write._

### `join_path` — `table` (confidence: medium, CONFLICT — supersedes id dbe03649-6067-4b30-818a-298105a65f46)
**Claim:** customer_id was backfilled from customer_key on 2026-07-29; now 0% NULL — prior join guidance may be stale, but backfill correctness is unverified
**Evidence:** SELECT count(*) FILTER (WHERE customer_id IS NULL)::float / count(*) FROM ecommerce.dim_customers = 0.0 (0 of 100 rows NULL), after UPDATE ecommerce.dim_customers SET customer_id = customer_key WHERE customer_id IS NULL affected 47 rows
**Learned by** `demo-seed/conflict-example` on 2026-07-29 — id `0ca7654e-4966-4b49-9392-9fcab10ff7e6`

### `join_path` — `table` (confidence: high, DISPUTED — see id 0ca7654e-4966-4b49-9392-9fcab10ff7e6)
**Claim:** Join on customer_key, not customer_id; customer_id is legacy and 47% NULL
**Evidence:** SELECT count(*) FILTER (WHERE customer_id IS NULL)::float / count(*) FROM ecommerce.dim_customers = 0.47 (47 of 100 rows NULL)
**Learned by** `demo-seed/conflict-example` on 2026-07-29 — id `dbe03649-6067-4b30-818a-298105a65f46`
<!-- agent-memory:end -->
