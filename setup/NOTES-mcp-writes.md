# MCP / SDK Write-Path Verification: Findings

Recorded 2026-07-29. Answers the build's #1 open risk: can SPEC.md §5 (structured
properties + documentation writes) be implemented against the local DataHub OSS
v1.5.0.6 quickstart? Every claim below was run against the live local GMS
(`http://localhost:8080`), not inferred from docs.

## Verdict

**Yes, with two required setup modifications, no protocol changes.** Both the write
paths SPEC.md §5 depends on, namely structured-property values (incl. `schemaField`-scoped)
and editable-description writes, work end-to-end against OSS quickstart, via both
the SDK and the official MCP server. The two modifications:

1. **Must launch `mcp-server-datahub` with `TOOLS_IS_MUTATION_ENABLED=true`.** Default
   is `false` (all mutation tools, including the two SPEC §5 needs, unregistered).
2. **Must pin/refresh to `mcp-server-datahub>=0.6.0`, not bare `uvx mcp-server-datahub`.**
   A stale `uv` package-index cache resolved bare `uvx mcp-server-datahub` to `0.4.0`
   in this environment, which has no mutation tools at all (not gated, not present in
   the code). `uvx mcp-server-datahub@latest` (or `--refresh`) resolved `0.6.0`, which
   has them. Mutation support arrived around v0.5.0, so `>=0.6.0` is a safe pin;
   verify pinning at demo time, don't trust a bare `uvx` invocation.

The one thing SPEC.md §5.1 flagged as unverified (MULTIPLE-cardinality `string`
property on both `dataset` and `schemaField`) registers and writes cleanly. No
protocol-level assumption in SPEC.md §5 was found to be wrong; §5.1's own "append vs
replace" ambiguity resolves to **replace** (see finding 4 below) and the skill design
must account for that explicitly.

## Task 1: property registration (`setup/register_properties.py`)

Registered `io.datahub.agentMemory.learnings` (string, MULTIPLE, entityTypes
`[dataset, schemaField]`) via `StructuredProperties.generate_mcps()` +
`graph.emit_mcp()`. Ran twice; second run produced identical output, confirmed
idempotent. No MCP tool exists for defining/registering a structured property (the
MCP mutation tool set only assigns *values* to already-defined properties), so this
step must stay on the SDK regardless of the runtime write path chosen below.

## Task 2: empirical write-path findings (SDK, throwaway scripts in scratchpad)

Scratch dataset: `urn:li:dataset:(urn:li:dataPlatform:postgres,scratch.agent_memory_write_test,PROD)`,
created via `datahub.sdk.dataset.Dataset(schema=[("amount", "number", ...), ("status", "string", ...)])`.

**2b: dataset-urn write + GraphQL round-trip.** Wrote the SPEC §3 `semantic_gotcha`
example (519-char JSON blob) via `Dataset.set_structured_property()` +
`client.entities.update()`. Read back via raw GraphQL (`structuredProperties.properties.values.stringValue`):
byte-identical to what was written; `json.loads()` of the readback matched the
original dict field-for-field. **Confirmed.**

**2c: schemaField-urn write.** The new high-level SDK (`datahub.sdk`) does **not**
support `schemaField` as an entity type yet: `client.entities.get(FIELD_URN)` raises
`SdkUsageError: Entity type schemaField is not yet supported`. The **low-level**
emitter does work: building a `StructuredPropertiesClass` aspect by hand and calling
`graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=FIELD_URN, aspect=...))`
succeeded with no exception, and GraphQL readback on the schemaField urn (queried as
`... on SchemaFieldEntity`) confirmed round-trip fidelity. **Confirmed working, but
only via the low-level MCP emitter, not the new high-level `datahub.sdk.Dataset` API.**
The MCP server's `add_structured_properties` tool (task 3) does not have this
limitation: it took the schemaField urn directly and worked without any low-level
fallback (see task 3 findings).

**2d: MULTIPLE cardinality: append or replace?** Tested empirically two ways:
- Naive second write (`set_structured_property(PROPERTY_URN, [blob_3])`, not
  including the first blob): result was `[blob_3]` only. **The first value was
  lost.** The SDK's `set_structured_property` (`datahub/sdk/_shared.py`) and the
  patch-builder's `add_structured_property`/`set_structured_property` both replace the
  entire values list for that `(propertyUrn, attributionSource)` key; the patch
  builder's own docstring says as much ("Currently equivalent to set_structured_property:
  overwrites all values"). This is **not** native list-append.
- Explicit read-modify-write (`existing_values + [blob_1]`, then write): produced
  `[blob_3, blob_1]`, both present, correct.
- **Conclusion: DataHub does not auto-append to MULTIPLE-cardinality property value
  lists. Every writer (SDK or MCP tool) must read the current value list, compute the
  merged list itself, and write the full list back.** SPEC.md §5.1's phrase "Adding a
  learning appends one value to the list" is accurate as an *outcome* the skill must
  implement, not a mechanism DataHub provides automatically. This should be called
  out explicitly in the skill implementation (recall-before-write, per §7 rule c,
  already forces the read step SPEC needs anyway, so no extra round trip is required
  in practice).

**2e: length limits.** Wrote one value at exactly 2,000 chars and one at exactly
10,000 chars (padded `evidence` field) to the dataset urn. Both wrote and read back
byte-identical with no truncation, no error, no size-related rejection. **No cap
encountered up to 10,000 chars**, comfortably above SPEC §4's guidance of keeping
blobs under ~700–800 chars, so v1's field-length guidance has generous headroom on
this GMS version. (Not tested beyond 10,000 chars: out of scope for SPEC's use case.)

**2f: editable-description read-modify-write.** Rendered the SPEC §5.2 marker block
(`<!-- agent-memory:begin -->` … `<!-- agent-memory:end -->`), wrote it via
`Dataset.set_description()` + `client.entities.update()` (markers absent → appended
after existing description with a blank-line separator, per rule 1). Re-fetched the
description, changed the rendered content, and re-applied the same split-on-markers
logic: **the second write replaced the block in place. One copy of the block, edited
content, zero duplication.** GraphQL readback confirmed exactly one `<!-- agent-memory:begin -->`
occurrence after the second write. **Confirmed the read-modify-write pattern SPEC
§5.2 rules 1–2 require works exactly as specified.**

## Task 3: MCP server write surface

Ran `uvx mcp-server-datahub@latest --transport stdio` (resolved `0.6.0`), env
`DATAHUB_GMS_URL=http://localhost:8080`, `TOOLS_IS_MUTATION_ENABLED=true`. No token
needed or configured: confirmed `is_cloud=False`, GMS accepted the unauthenticated
connection identically to direct GraphQL/SDK access (matches
`setup/NOTES-datahub-quickstart.md`'s auth findings). **No `.env`/`.env.example` was
created, not needed, since local OSS quickstart requires no token for this server
either.**

Full tool list (18 tools; 2 document-search tools were auto-filtered because the
instance has zero `Document` entities: `search_documents`, `grep_documents`):

Read-only (always registered):
| Tool | Description |
|---|---|
| `search` | Search across DataHub entities using structured full-text search. |
| `get_lineage` | Get upstream or downstream lineage for any entity, including datasets, schemaFields, dashboards, charts, etc. |
| `get_dataset_queries` | Get SQL queries associated with a dataset or column to understand usage patterns. |
| `get_entities` | Get detailed information about one or more entities by their DataHub URNs. |
| `list_schema_fields` | List schema fields for a dataset, with optional keyword filtering and pagination. |
| `get_lineage_paths_between` | Get detailed lineage path(s) between two specific entities or columns. |

Mutation (only registered when `TOOLS_IS_MUTATION_ENABLED=true`; default off):
| Tool | Description |
|---|---|
| `add_tags` / `remove_tags` | Add/remove tags on entities or their columns. |
| `add_terms` / `remove_terms` | Add/remove glossary terms on entities or their columns. |
| `add_owners` / `remove_owners` | Add/remove owners on entities. |
| `set_domains` / `remove_domains` | Set/remove domain assignment on entities. |
| `update_description` | Update description for an entity or its column (`operation`: replace / append / remove; `column_path` targets a schema field). |
| `add_structured_properties` | Add structured properties with values to multiple entities (`property_values: {propertyUrn: [values]}`, `entity_urns: [...]`). |
| `remove_structured_properties` | Remove structured properties from multiple entities. |
| `save_document` (separately gated, `SAVE_DOCUMENT_ENABLED`, was on by default in this build) | Save/update a standalone knowledge-base Document entity. |

**Direct answer to the two specific questions:**
- **(i) Structured-property value mutation: yes.** `add_structured_properties` /
  `remove_structured_properties`. Internally calls the GraphQL
  `upsertStructuredProperties` mutation (confirmed via server debug logs).
- **(ii) Entity documentation/description mutation: yes.** `update_description`,
  with a `column_path` parameter for schema-field-level descriptions.

**Empirical tool-call verification** (not just schema inspection: actually invoked
over stdio via `session.call_tool(...)`):
- `add_structured_properties` on the scratch **dataset** urn: `{"success":true,...}`,
  GraphQL readback matched exactly.
- `add_structured_properties` on the scratch **schemaField** urn (passed directly as
  an `entity_urns` entry, no special column parameter needed, unlike
  `update_description`): `{"success":true,...}`, GraphQL readback matched exactly.
  **This is the one write the low-level SDK needed a manual `emit_mcp` workaround
  for (2c above); the MCP tool has no such gap.**
- `update_description` with `operation="replace"` on the dataset urn: succeeded,
  GraphQL readback showed the new description verbatim (and, as expected for
  `replace`, it *overwrote* the SDK-written marker block from task 2f rather than
  merging, confirming the skill must do its own read-modify-write around this tool,
  same as the SDK path).

## Recommended write path for the skill (MCP vs. SDK-fallback question)

**Use the MCP server as the primary write path; no SDK fallback is needed for
mutation.** Both structured-property and documentation writes work through it against
this OSS quickstart, on both dataset and schemaField urns, with no gap the SDK
plugs. Requirements for the skill/runtime to get this right:

1. Launch/configure the MCP server with `TOOLS_IS_MUTATION_ENABLED=true` (and pin
   `mcp-server-datahub>=0.6.0`, see verdict above on the stale-cache trap).
2. Because DataHub does not append to `MULTIPLE`-cardinality values automatically
   (finding 2d), the retain workflow (SPEC §7) must fetch the entity's current
   `io.datahub.agentMemory.learnings` values (via `get_entities` or `search`), compute
   the new full list client-side (append/replace-one-entry/dedupe per SPEC §7–§8),
   and call `add_structured_properties` with the complete resulting list, never a
   single new value alone, or prior learnings are silently lost.
3. Same read-modify-write discipline for `update_description`: fetch current
   description, apply the SPEC §5.2 marker-block splice logic client-side, call
   `update_description(operation="replace", description=<full new text>)`. Do not use
   `operation="append"` for the learnings block: it does raw string concatenation
   and would violate SPEC §5.2 rule 2 (replace in place, never duplicate).

**SDK stays in play for exactly one thing:** one-time structured-property
*definition* registration (`setup/register_properties.py`), since no MCP tool
registers property definitions: only assigns values to properties that already
exist. This matches the repo's setup-tooling vs. skill split; no change needed.

## Cleanup

Scratch dataset soft-deleted: `datahub delete --urn "urn:li:dataset:(urn:li:dataPlatform:postgres,scratch.agent_memory_write_test,PROD)" --soft -f`
→ `Soft deleted 1 entities (impacts 1 versioned rows and 0 timeseries aspect rows)`.
Confirmed via GraphQL: `status.removed = true`. No manual UI cleanup needed.

## Files touched

- `pyproject.toml`: added `acryl-datahub` dependency.
- `setup/register_properties.py`: new, permanent deliverable (task 1).
- `setup/NOTES-mcp-writes.md`: this file.
- No `.env` / `.env.example` created: no token was required at any point.
- All throwaway test scripts stayed in the session scratchpad dir, not the repo.
