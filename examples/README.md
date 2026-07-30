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
