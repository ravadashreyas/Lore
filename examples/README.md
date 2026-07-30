# examples/

Real output from the agent-memory protocol running against a live local DataHub OSS
v1.5.0.6 instance — not mocked, not hand-written JSON. These are what the video's
Agent A produces live when it retains what it learned about `fct_orders`; the files
here were produced the same way (same MCP tool calls, same skill workflow) ahead of
time so judges can inspect the output without running the demo themselves.

## Files

- **`learnings-fct_orders.json`** — the three learnings from `skill/datahub-memory/SKILL.md`'s
  Worked Example A (`semantic_gotcha` on the `amount` column, `metric_definition` and
  `verified_query` on the table), as read back from DataHub's
  `io.datahub.agentMemory.learnings` structured property after writing them via
  `add_structured_properties`. Proves the round-trip: what got written is exactly what
  comes back, on both the dataset urn and the `amount` schemaField urn.
- **`doc-block-fct_orders.md`** — the `fct_orders` dataset's `editableProperties.description`
  read back after the retain workflow's doc-block step, byte-for-byte. This is what a
  human sees in the DataHub UI's Documentation tab — the same content as the JSON
  above, rendered by the skill into the fixed markdown template
  (`skill/datahub-memory/templates/doc-block.template.md`) and spliced between the
  `<!-- agent-memory:begin/end -->` markers.
- **`learnings-fct_orders.json`**'s field-level entry (the `semantic_gotcha`) lives on
  the `amount` column's own structured property, not the dataset's — per
  `protocol/SPEC.md` §5.1, column-scoped learnings are written to the schemaField urn.
  Its own column-level description was intentionally left untouched in this pass, matching
  the tool calls shown in `SKILL.md`'s Worked Example A (which splices the doc block
  onto the dataset urn only); the structured property write to the schemaField urn is
  still real and reads back correctly.

## Provenance

Written by `demo-seed/wave4` on 2026-07-29, using the exact retain workflow
(`skill/datahub-memory/SKILL.md` Workflow 2, Steps 3–4: read-merge-write the
structured property, then re-render and splice the doc block) via the DataHub MCP
server (`uvx mcp-server-datahub@latest`, `TOOLS_IS_MUTATION_ENABLED=true`) called over
stdio — the same tool surface `references/mcp-tools-reference.md` documents and the
same one a live Claude Code session uses. Not a different code path than the video.

These learnings are live on the real `fct_orders` dataset and its `amount` column in
the local DataHub instance right now — open `http://localhost:8080` and search
`fct_orders` to see them in the UI, or run `demo/reset_demo.py` to confirm the reset
path removes them cleanly (it does; see `WORKLOG.md`) before re-running the demo.

## Conflict-handling example (`dim_customers`)

- **`conflict-learnings-dim_customers.json`** — the two `io.datahub.agentMemory.learnings`
  records left on `dim_customers` by a full run of `protocol/SPEC.md` §8's conflict
  procedure (`skill/datahub-memory/SKILL.md` Conflict Procedure): the original
  `join_path` record (now `status: disputed`, `claim`/`evidence`/`confidence`
  untouched, exactly as §8 rule 1 requires) and the new `join_path` record that
  contradicts it (`status: conflict`, `conflicts_with` pointing at the disputed
  record's `id`). Both `learnings` (parsed) and `raw_wire_values` (the exact
  single-line JSON strings DataHub stores) are included.
- **`conflict-doc-block-dim_customers.md`** — `dim_customers`' `editableProperties.description`
  read back after the matching doc-block re-render, showing both entries with the
  `DISPUTED` / `CONFLICT` markers `protocol/SPEC.md` §5.2 rule 5 requires.

### What was actually done to produce these (and why it's not live now)

Unlike the `fct_orders` artifacts above, this pair demonstrates the conflict
mechanism itself, which requires a learning to first be *contradicted* — so the
scenario needed a real change in the underlying data, not just a write. Every step
below was executed for real against the live local stack (DataHub OSS v1.5.0.6 at
`http://localhost:8080`, the demo Postgres warehouse at `localhost:5434`), then the
environment was restored. Nothing here is hand-authored or simulated:

1. **Verified the landmine.** `SELECT count(*) FILTER (WHERE customer_id IS NULL)::float / count(*) FROM ecommerce.dim_customers` against the live warehouse returned `0.47` (47 of 100 rows).
2. **Wrote a genuine `join_path` learning** on the `dim_customers` dataset urn via `add_structured_properties` — read-merge-write against a confirmed-empty starting list (verified via GraphQL before writing) — claiming `customer_id` is legacy and 47% NULL, `confidence: high`, evidence the exact query and result from step 1. Spliced the doc block via `update_description` per §5.2.
3. **Applied a real migration**: `UPDATE ecommerce.dim_customers SET customer_id = customer_key WHERE customer_id IS NULL` — 47 rows affected. Re-ran the step-1 query: `0.0`.
4. **Ran the conflict procedure exactly per §8**, as two separate read-merge-write calls to `add_structured_properties`, never one edit: (a) read the current list, changed only the disputed record's `status` field to `"disputed"`, wrote the full list back; (b) read again (confirming write (a) had landed), appended a brand-new record with `status: "conflict"`, `conflicts_with` set to the disputed record's `id`, an honest `confidence: "medium"` (the NULL-rate re-check is verified; whether downstream joins are now safe on the backfilled column is not), and evidence citing the re-run query plus the migration statement. Re-rendered and spliced the doc block, producing the `DISPUTED`/`CONFLICT` markers.
5. **Captured both artifacts** in this directory via a fresh GraphQL readback of `dim_customers` — the JSON and Markdown files above are that readback, not a transcription.
6. **Restored the environment.** Re-ran `uv run python setup/seed_warehouse.py` (deterministic fixed-seed reseed) — confirmed the NULL ratio was back to `0.47` and `fct_orders`' ground-truth numbers (500 orders, naive June 2026 revenue `4,668,271,415` cents, completed-only revenue `$38,604,332.17`) were unchanged. Then cleared **only** `dim_customers`' structured-property values (`add_structured_properties` with an empty list) and stripped **only** its doc block, scoped to that one urn — the full `demo/reset_demo.py` sweep was deliberately not run, because another agent was concurrently reading `fct_orders`' learnings during this work and `fct_orders` (and `features_customer_ltv`) had to stay untouched. Verified after cleanup: `dim_customers` has 0 learnings and an empty description; `fct_orders` still has its original 2 dataset-level learnings, its 1 `amount`-column learning, and its doc block, byte-for-byte unchanged throughout.

**Honesty note (per `CLAUDE.md`):** the conflict shown in these two files is **not**
sitting live in the DataHub instance right now — it was real when captured, and the
instance was deliberately returned to a clean state afterward so the demo scenario
stays re-runnable. These files are a snapshot of a real, fully-executed run of the
protocol's conflict mechanism, not a permanent fixture and not a mock. Re-running the
six steps above against the live stack reproduces the same shape of result (the
migration is deterministic; `learned_at`/`id` values would differ on a fresh run).
