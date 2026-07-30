# Agent Memory on DataHub — Protocol Specification v1

Status: draft, hackathon submission. This document defines the protocol precisely enough
that an independent implementation — a different skill, a different agent framework, a
different language — can read and write compatible learnings against a DataHub instance
without reference to any other file in this repo.

Key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are used as defined in RFC 2119.

## 1. Motivation

Agents that work with data are goldfish. Every session starts with an empty context
window. The same tribal knowledge gets re-derived from scratch, at cost, every time:
`amount` is in cents, cancelled orders need filtering, the real join key is
`customer_key` because `customer_id` is half-null legacy cruft. None of this is written
down anywhere an agent looks by default, so it is paid for again and again — sometimes
silently wrong, because nobody re-derives it *correctly* every time either.

The reason schemas don't help is that schemas describe structure, not semantics. A
column named `amount` typed `bigint` is fully self-consistent and fully misleading. The
gap between what a table's structure says and what it actually means — the traps, the
verified-safe queries, the caveats a human would mention in Slack — is exactly the
knowledge this protocol captures. It defines how an agent turns a costly, one-off
discovery into a durable fact attached to the data itself, so the next agent (or human)
reads it before acting instead of re-discovering it the hard way.

## 2. Concepts & terminology

- **Learning** — a single typed, structured claim about a DataHub entity, derived from
  direct investigation (querying, sampling, cross-checking), not restated from schema or
  existing docs. The unit of storage and retrieval in this protocol.
- **Subject** — the DataHub entity a learning is about: a dataset, or a specific column
  (schema field) within a dataset. Every learning has exactly one subject.
- **Recall** — the read-side workflow: before acting on a dataset, an agent fetches and
  applies existing learnings for that dataset and its near lineage. Defined in §6.
- **Retain** — the write-side workflow: after acting on a dataset, an agent distills what
  it learned and writes new learnings back to DataHub, subject to the judgment rules in
  §7. Defined in §7.
- **Provenance** — the record of who produced a learning and when (`learned_by`,
  `learned_at`). Provenance in v1 is a plain claim, not a cryptographic guarantee — see
  §9.
- **Confidence** — an honest, three-level self-assessment of how well-supported a
  learning is: `high` (verified against ground truth), `medium` (strong inference, not
  independently verified), `low` (hypothesis). Defined precisely in §4.

## 3. Learning types

Every learning has exactly one `kind`, from a fixed set of five. An agent MUST NOT
invent new kinds in v1 (see §9).

### `semantic_gotcha`

A fact about what a column or table's values actually mean, where that meaning is not
recoverable from the schema alone.

- **Use when**: a value's unit, encoding, or scope differs from what its name/type
  implies.
- **Example**: subject `fct_orders.amount` — "Values are stored in cents, not dollars;
  divide by 100 to get a dollar amount." Evidence: `SUM(amount)` for completed June 2026
  orders returned 3,860,433,217 against a finance dashboard total of $38,604,332 —
  ratio exactly 100.

### `verified_query`

A specific SQL pattern that is known, by direct verification, to produce a correct
result for a common question against this subject.

- **Use when**: getting a correct answer required combining several non-obvious fixes
  (unit conversion, filters, join keys) and re-deriving that combination is expensive.
- **Example**: subject `fct_orders` — "Monthly revenue: `SELECT SUM(amount)/100.0 FROM
  fct_orders WHERE status = 'completed' AND date_trunc('month', order_date) = :month`."
  Evidence: result for June 2026 ($38,604,332.17) matched the finance dashboard export
  to the cent.

### `join_path`

The correct (or incorrect) way to join this subject to another entity, where the naive
choice is wrong or misleading.

- **Use when**: two plausible join keys exist and one of them is broken, deprecated, or
  silently drops/duplicates rows.
- **Example**: subject `dim_customers` — "Join on `customer_key`, not `customer_id`;
  `customer_id` is a legacy column, NULL for 47% of rows post-2024 migration." Evidence:
  `SELECT count(*) FILTER (WHERE customer_id IS NULL) * 1.0 / count(*) FROM
  dim_customers` = 0.47.

### `caveat`

A limitation, quality issue, or scope restriction on the subject that isn't a semantic
mismatch or a join problem, but would still mislead someone who didn't know it.

- **Use when**: the data is correct as far as it goes but incomplete, stale, or
  restricted in a way that matters for typical use.
- **Example**: subject `fct_orders` — "Table only contains orders from the `us-east`
  region; international orders live in `fct_orders_intl` and are not unioned here."
  Evidence: `SELECT DISTINCT region FROM fct_orders` returned a single value (`us-east`)
  against 300 rows sampled.

### `metric_definition`

The verified, agreed definition of a named business metric as computed from this
subject, when the naive computation is ambiguous or wrong.

- **Use when**: a metric name (revenue, active users, churn) has more than one
  plausible SQL definition and one has been confirmed correct against a trusted source.
- **Example**: subject `fct_orders` — "'Revenue' excludes cancelled and refunded orders
  (status = 'completed' only) and is measured in dollars (amount / 100), summed by
  `order_date`, not `created_at`."
  Evidence: cross-checked against finance dashboard for 3 distinct months; all three
  matched within $1.

## 4. The learning record schema

A learning is a flat record with the following fields. Field names are the wire format
used in the JSON serialization defined in §5.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string (UUID4) | required | Assigned once at creation by the writer; MUST NOT change for the life of the learning. Used to target updates and to reference learnings from conflict records (§8). |
| `kind` | enum | required | One of `semantic_gotcha`, `verified_query`, `join_path`, `caveat`, `metric_definition` (§3). |
| `subject_urn` | string (DataHub URN) | required | The dataset entity the learning is about, e.g. `urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.fct_orders,PROD)`. |
| `subject_field` | string | optional | Schema field (column) name within `subject_urn`, if the learning is column-scoped, e.g. `amount`. Omitted for table-level learnings. |
| `claim` | string | required | The distilled insight, in plain language. MUST be 1–2 sentences and SHOULD stay under 280 characters. Longer claims usually mean two learnings, not one. |
| `evidence` | string | required | Concrete, checkable support for the claim: a query and its result, a specific count, a comparison against a named ground truth. SHOULD stay under 500 characters. MUST NOT be a vague assertion ("seems right", "probably correct"). |
| `confidence` | enum | required | `high`, `medium`, or `low` — see definitions below. |
| `learned_by` | string | required | `<agent-name>/<session-id>`, e.g. `analytics-agent/session-7f3a`. |
| `learned_at` | string (ISO 8601 date) | required | `YYYY-MM-DD`, e.g. `2026-07-29`. |
| `status` | enum | optional, default `active` | `active`, `disputed`, or `conflict` — lifecycle state used by conflict handling (§8). |
| `conflicts_with` | string (UUID4) | optional | Present only when `status = conflict`; the `id` of the existing learning this record contradicts. |

**Confidence — honest definitions (MUST be applied as written, not inflated):**

- **`high`** — verified against ground truth: the claim was checked against an
  independent, trusted source (a dashboard, a second query path, a known-correct
  total) and matched.
- **`medium`** — strong inference: the evidence is internally consistent and
  compelling (a suspicious ratio, a plausible pattern across samples) but was not
  cross-checked against an independent source.
- **`low`** — hypothesis: a plausible explanation was formed but not tested. Rare in
  practice — a learning this weak is often not worth writing (§7 rule a note).

## 5. Storage mapping to DataHub

Each learning is stored in two places on the subject entity, kept in sync by the
writer: a **structured property** (machine-readable, the source of truth) and a
**documentation block** (human-readable, a rendered projection of it). There is no
separate database — the DataHub graph itself is the store.

### 5.1 Structured property definition (chosen approach)

v1 defines a single structured property:

```yaml
- id: io.datahub.agentMemory.learnings
  qualifiedName: io.datahub.agentMemory.learnings
  type: string
  cardinality: MULTIPLE
  entityTypes:
    - dataset
    - schemaField
  displayName: Agent memory learnings
  description: >
    One JSON-serialized agent-memory learning record (see protocol/SPEC.md §4) per
    list value. Written and read by the recall/retain skill; not hand-edited.
```

Each value in the property's value list is one learning, serialized as a single-line
JSON object with exactly the fields in §4 (omitting absent optional fields).

**Write semantics (critical).** DataHub's structured-property write replaces the
property's *entire* value list — it does not append (verified against OSS v1.5.0.6:
both the SDK and the MCP `add_structured_properties` tool overwrite all values). A
writer MUST therefore: (1) read the property's current values, (2) merge the change
client-side — add the new learning, or replace/update exactly one existing element —
and (3) write the complete merged list back. A write containing only the new value
destroys every existing learning on the entity and MUST never be issued.

Table-level learnings (`subject_field` absent) are written to the dataset's own urn.
Column-level learnings are written to the corresponding schema field urn, e.g.
`urn:li:schemaField:(urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.fct_orders,PROD),amount)`,
using the same property definition (hence `schemaField` in `entityTypes`).

**Why one JSON-blob-per-value instead of one property per field.** DataHub structured
properties are flat, entity-scoped key → value-list pairs; there is no native
nested/object type. A learning has eight-plus fields that must travel together as one
unit. Modeling each field as its own `MULTIPLE`-cardinality property (`kind[]`,
`claim[]`, `evidence[]`, `confidence[]`, ...) would require every reader and writer to
reconstruct a record by matching array indices (or an embedded id) across several
independently-mutable properties — one partial write, one out-of-order update, and the
arrays silently desync with no error. That is exactly the fragile, hard-to-review state
CLAUDE.md's write-less-code rules warn against. Packing one whole learning into a
single JSON string value, and using the property's native `MULTIPLE` cardinality to
hold "list of learnings," keeps every record atomic: one list entry is one complete,
self-consistent learning; an append is a single-value insert; an update or removal
targets exactly one element and cannot corrupt the rest. The cost is that DataHub's
structured-property search UI cannot facet on a sub-field (e.g. "show datasets with a
`high`-confidence learning") since each value is opaque JSON to DataHub's own indexer
— acceptable for v1 because the human-facing surface for that is the documentation
block (§5.2), not structured-property search facets.

**Alternative, not chosen.** A hybrid — the JSON blob as above, plus a few duplicated
scalar properties (e.g. `agentMemory.kinds`, `agentMemory.confidences`, both `MULTIPLE`
string, index-aligned to the blob list) purely to make coarse filtering facetable in
DataHub search — would recover that filtering at the cost of the same synchronization
risk described above, scoped down to a couple of fields; a v2 could adopt it if
facet search proves valuable.

**Verified against DataHub OSS v1.5.0.6 (quickstart)**: a `string`-typed property with
`MULTIPLE` cardinality registers and applies to both `dataset` and `schemaField`
entity types; values round-trip byte-identical; 2,000- and 10,000-character values
wrote and read back without truncation, so §4's length guidance (~700–800 characters
per serialized learning) has ample headroom. Writes work via both the Python SDK
(schemaField requires the low-level `MetadataChangeProposalWrapper` path) and the
DataHub MCP server's `add_structured_properties` tool (server >= 0.6.0, launched with
`TOOLS_IS_MUTATION_ENABLED=true`). See the write-semantics warning above — the
full-list-replace behavior is the one empirically confirmed sharp edge.

### 5.2 Documentation block format

On every retain write, the writer MUST re-render the entity's (or schema field's)
*entire* set of current, non-superseded learnings from the structured property (the
source of truth) into a fixed markdown block, and MUST replace that block in place in
the entity's description — never appending a second copy. The block is delimited by
exact HTML-comment markers so it can be found and replaced idempotently regardless of
what else is in the description:

```markdown
<!-- agent-memory:begin -->
## Agent learnings

_Distilled by agents via the agent-memory protocol. Machine-generated — do not hand-edit; edits will be overwritten on the next write._

### `semantic_gotcha` — `amount` (confidence: high)
**Claim:** Values are stored in cents; divide by 100 for a dollar amount.
**Evidence:** SUM(amount) for completed June 2026 orders = 3,860,433,217 vs. finance dashboard $38,604,332; ratio exactly 100.
**Learned by** `analytics-agent/session-7f3a` on 2026-07-29 — id `3f9a2b1c-4d5e-4f60-8a11-9b2c3d4e5f60`

### `verified_query` — table (confidence: high)
**Claim:** Monthly revenue query: `SELECT SUM(amount)/100.0 FROM fct_orders WHERE status = 'completed' AND date_trunc('month', order_date) = :month`.
**Evidence:** June 2026 result ($38,604,332.17) matched finance dashboard export to the cent.
**Learned by** `analytics-agent/session-7f3a` on 2026-07-29 — id `9c1d2e3f-5a6b-4c7d-8e9f-0a1b2c3d4e5f`
<!-- agent-memory:end -->
```

Rules for the block:

1. If the markers are absent from the current description, the writer MUST append the
   whole block (including markers), preceded by a blank line, to the end of the
   existing description. Content before the markers is never touched.
2. If the markers are present, the writer MUST replace everything between them
   (inclusive of the markers) and MUST NOT modify any text outside them.
3. Entries are ordered by `learned_at` descending, ties broken by `kind` alphabetical.
4. One `###` heading per learning: `` `kind` — `field-or-"table"` (confidence: level) ``.
5. Learnings with `status: disputed` or `status: conflict` MUST be rendered with the
   status made visible, e.g. `(confidence: medium, DISPUTED — see id ...)`, per §8.
6. Because the block is fully regenerated from the structured property on every write,
   the documentation block is idempotent by construction: writing the same learning
   set twice produces byte-identical block content.

## 6. The recall workflow

An agent MUST perform recall before the first query or modification that touches a
given dataset in a session, and before relying on a cached recall result older than
the current session.

**Scope.** Recall MUST fetch learnings for: (a) the target entity itself, at both the
table level and, if specific columns are already known to be relevant, the column
level; and (b) every entity exactly one lineage hop upstream of the target (its direct
input tables/views, via DataHub lineage). Recall MUST NOT by default expand beyond one
upstream hop — this bounds cost and noise. An agent MAY deliberately recall a second
hop when the task explicitly concerns a multi-hop join or transformation, but this is
non-default and MUST be a conscious choice, not automatic.

**Mechanics.** For each in-scope entity, read the `io.datahub.agentMemory.learnings`
structured property values, parse each as JSON per §4, and discard (with a logged
warning, not a crash) any value that fails to parse — a malformed entry MUST NOT block
recall of the rest.

*Implementation note (non-normative, as of `mcp-server-datahub` 0.6.0 / OSS
v1.5.0.6): the MCP server's `get_entities` returns structured-property values for
dataset urns, but no MCP tool returns them for schemaField urns, even though writes
to schemaField urns succeed. Column-scoped recall therefore currently requires a raw
GraphQL query (`... on SchemaFieldEntity { structuredProperties { ... } }`) — see the
skill's tool reference for the exact query. This is a read-path gap in the MCP server,
not in DataHub's storage; it is a candidate upstream contribution.*

**Applying confidence.**

- **`high`** — the agent MUST apply the claim directly (e.g. use the verified query
  pattern, apply the unit conversion) without re-deriving it from scratch.
- **`medium`** — the agent MUST apply the claim provisionally, and SHOULD perform a
  cheap, targeted check (a single aggregate query, a small sample) before relying on it
  for a consequential answer. It is not to be treated as unverified from zero, nor as
  fully proven.
- **`low`** — the agent MUST NOT apply the claim as fact. It MAY use it as a hint for
  where to investigate first, and MUST independently verify before treating it as true.

If any in-scope learning has `status: disputed` or a corresponding `conflict` entry
exists, the agent MUST surface that conflict rather than silently picking one side
(§8).

## 7. The retain workflow

After completing a task against a dataset, an agent SHOULD distill what it learned and
write it back, subject to the following testable rules. A candidate learning that
fails any rule below MUST NOT be written.

**(a) No secrets or row-level data.** A learning MUST NOT contain credentials, API
keys, tokens, individual PII (names, emails, addresses, ids that identify a person),
or row-level/record-level data of any kind. Evidence MUST be aggregate or statistical
(counts, sums, ratios, schema facts), never an exported row or a specific customer's
record. Test: if evidence would let a reader reconstruct a real record, it fails.

**(b) No restating the schema.** A learning MUST NOT communicate something already
fully evident from the column name, type, or existing documentation. "`amount` is a
bigint column" is not a learning; "`amount` is a bigint but the unit is cents, not
dollars" is. Test: would a competent reader of the schema and current docs already
know this? If yes, don't write it.

**(c) Dedupe before writing.** Before writing, the agent MUST run recall (§6) against
the intended subject and check for an existing learning of the same `kind`, same
subject, and a semantically equivalent claim. If one exists and is unchanged in
substance, the agent MUST NOT write a duplicate. Exception: if the only change is
independently reverifying an existing claim and thereby strengthening its confidence
(e.g. `medium` → `high`) or refreshing its evidence, the agent MAY update that existing
record's `confidence`/`evidence`/`learned_at` in place — this is not the overwrite
prohibited by rule (e), because the claim itself is unchanged.

**(d) Honest confidence, concrete evidence.** `confidence` MUST match the definitions
in §4 exactly — do not mark `high` without an independent check performed. `evidence`
MUST be concrete and checkable (a query, a number, a named comparison), never a vague
assertion. Test: could a second agent re-run the evidence and get the same result?

**(e) Never overwrite on contradiction.** If a new observation contradicts an existing
active learning for the same subject and kind, the agent MUST NOT edit or delete the
existing record's claim, evidence, or confidence. It MUST instead follow the conflict
procedure in §8 — a contradiction may mean the underlying data genuinely changed,
which is itself information worth keeping, not an error to be silently corrected.

**(f) About the data, not the task.** A learning MUST describe a property of the data
itself — its semantics, quality, structure, or a verified way to query it — and MUST
NOT describe the requesting task, user, or session ("the user asked for June revenue"
is not a learning; "revenue queries must exclude cancelled orders" is). Test: would
this claim remain true and useful regardless of who asked, or why?

## 8. Conflict handling

A conflict arises when retain (§7 rule e) finds a new observation that contradicts an
existing `active` learning of the same `kind` for the same subject. The agent MUST
handle it as two writes, never one edit:

1. **Mark the existing record disputed.** Update only the existing learning's `status`
   field to `disputed` (its `claim`, `evidence`, and `confidence` are left untouched).
2. **Write a new conflict record**, using the same schema as any learning (§4), with:
   - `status: conflict`
   - `conflicts_with`: the `id` of the disputed record
   - `claim`: states the contradiction plainly, referencing both observations, e.g.
     "Contradicts prior learning: `amount` now appears to already be in dollars, not
     cents, for orders after 2026-07-01."
   - `evidence`: the new observation's concrete support.
   - its own new `id`, `learned_by`, `learned_at`, and honest `confidence`.

Both records remain in the structured property list and both are rendered in the
documentation block (§5.2 rule 5), with the disputed one visibly marked.

**Consumer guidance.** An agent or human performing recall (§6) on a subject with an
unresolved conflict MUST NOT silently prefer one record over the other by default. It
MUST surface the conflict to whoever/whatever is consuming the recall result — display
both claims and both evidence strings, and let a human, or an explicit task-level
policy, decide. If a decision must be made automatically under time pressure, the
default policy is: prefer the record with higher `confidence`; if tied, prefer the
more recent `learned_at`; but the fact that a conflict existed MUST still be disclosed
in the agent's output, not silently resolved. Conflicts are not deleted or archived in
v1 — resolving one requires a human (or a future protocol version) to retire one side
explicitly; the protocol has no automated resolution.

## 9. Limits & non-goals of v1

- **No automated expiry or TTL.** Learnings persist indefinitely once written; nothing
  in the protocol ages them out. Staleness is only ever surfaced via the conflict
  mechanism (§8) when a contradicting observation happens to be made — there is no
  background process checking whether old learnings still hold.
- **No cryptographic provenance.** `learned_by` is a plain, unverified string. Nothing
  prevents a malicious or buggy writer from misattributing a learning; provenance in
  v1 is a convention, not a guarantee.
- **No cross-instance sync.** Learnings live in exactly one DataHub instance's graph.
  Federation, replication, or merging learnings across separate DataHub deployments is
  out of scope.
- **No automated dedupe algorithm.** Dedup (§7 rule c) is a judgment call an agent
  makes by reading existing learnings, not a hash- or embedding-based automatic
  matching system. v1 accepts that near-duplicate learnings with differently-phrased
  claims may occasionally both get written.
- **No learning-kind extensibility.** The five kinds in §3 are fixed for v1. Adding a
  new kind requires a protocol version bump, not a per-deployment config option.
  (Consistent with CLAUDE.md's rule against speculative extensibility.)
- **No per-learning access control.** Learnings inherit whatever read/write permissions
  DataHub already enforces on the subject entity; the protocol defines no separate
  visibility or redaction layer.
- **No enforced recall.** The protocol defines what recall must do when performed
  (§6), but does not — and in v1 cannot — technically force an agent to perform it
  before acting. Compliance is a property of the skill/agent implementation, not of
  DataHub itself.
- **No conflict auto-resolution.** As noted in §8, a conflict, once written, stays
  open until a human (or a later protocol version) resolves it explicitly.
