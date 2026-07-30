# Lore

**Tribal knowledge for AI agents, stored where your data lives.**

Agents that work with data are goldfish. Every session starts with an empty context window, and the same tribal knowledge gets re-derived from scratch, at cost, every time: `amount` is in cents, cancelled orders need filtering, the real join key is `customer_key` because `customer_id` is half-null legacy cruft. Schemas describe structure, not semantics, so none of this is written down anywhere an agent looks by default — it gets paid for again and again, and it's silently wrong just as often as it's re-derived correctly.

Lore is a protocol and a Claude Code skill that make **DataHub the shared long-term memory for agents**. When an agent investigates a dataset and figures something out, it writes what it learned back to the metadata graph as structured properties plus a rendered documentation block. The next agent — and every human looking at the same dataset in the DataHub UI — inherits it instead of re-discovering it the hard way.

```mermaid
flowchart LR
    subgraph A["Agent A — today"]
        A1["investigates fct_orders,<br/>hits the landmines"] --> A2["retain:<br/>distill learnings"]
    end
    subgraph DH["DataHub metadata graph"]
        FO["fct_orders<br/>learnings: structured property<br/>+ rendered doc block"]
        FV["features_customer_ltv"] -->|"lineage (1 hop)"| FO
    end
    subgraph B["Agent B — later, fresh context"]
        B1["recall<br/>before acting"] --> B2["correct on<br/>first try"]
    end
    A2 -->|"MCP: add_structured_properties,<br/>update_description"| FO
    FO -->|"MCP: get_entities,<br/>get_lineage"| B1
```

## Why this matters

The gap Lore targets isn't a missing feature of any single agent — it's structural. Schemas describe types and names; they don't and can't describe that a `bigint` is secretly in cents, or that a `status` column has three values but only one means "real revenue." A human analyst learns this once, from a teammate or a Slack thread, and it sticks. An agent learns it once per session and forgets it the moment the context window closes, because there's nowhere in the data platform itself to put the answer. DataHub already has search, lineage, structured properties, and documentation on every entity — the primitives for durable knowledge already exist. Lore is the protocol and workflow that actually uses them for this: a fixed record shape, a read-before-act / write-after-act discipline, and a conflict rule that treats contradictions as signal instead of letting one agent silently clobber another's finding. The payoff compounds — every agent that runs the retain workflow makes every subsequent agent (and every human) faster and more correct on the same data, for free.

## How it works

A **learning** is a typed record attached to a DataHub entity (a dataset, or a specific column within one): one of five kinds (`semantic_gotcha`, `verified_query`, `join_path`, `caveat`, `metric_definition`), a plain-language `claim`, concrete checkable `evidence`, an honest `confidence` (`high` = verified against ground truth, `medium` = strong inference, `low` = hypothesis), and provenance (`learned_by`, `learned_at`):

```yaml
kind: semantic_gotcha
subject_urn: urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.fct_orders,PROD)
subject_field: amount
claim: "Values are stored in cents, not dollars; divide by 100 for a dollar amount."
evidence: "SUM(amount) for completed June 2026 orders = 3,860,433,217 vs. finance dashboard $38,604,332; ratio exactly 100."
confidence: high
learned_by: analytics-agent/session-7f3a
learned_at: 2026-07-29
```

- **Recall** (read before acting) — before touching a dataset, an agent fetches learnings for that entity and every entity exactly one lineage hop upstream (bounded on purpose, to keep cost and noise down). It applies `high`-confidence claims directly, spot-checks `medium` ones with one cheap query, and treats `low` ones only as a hint to investigate, not as fact.
- **Retain** (write after acting) — after finishing a task, the agent distills candidate learnings and runs each through a judgment-rule checklist before writing anything: (a) no secrets or row-level data, evidence must be aggregate/statistical only; (b) not a restatement of the schema; (c) deduped against existing learnings (recall is re-run first); (d) honest confidence backed by concrete, re-runnable evidence; (e) never an overwrite on contradiction; (f) about the data, not the requesting task. A candidate that fails any item doesn't get written.
- **Read-merge-write, always** — DataHub replaces a structured property's whole value list on write; it does not append. Every write reads the entity's current values, merges in the change client-side, and writes the complete list back — skipping this step silently destroys every prior learning on that entity. The human-readable side (a rendered `## Agent learnings` block in the entity's documentation) is regenerated in full from the structured property and spliced in place between fixed `<!-- agent-memory:begin/end -->` HTML-comment markers on every write, so re-running retain twice produces byte-identical output — never a growing pile of appended text.
- **Conflicts, never edits** — if a new observation contradicts an existing active learning, the agent never edits the old record's claim, evidence, or confidence. It's always two writes: mark the existing one `status: disputed` (untouched otherwise), and write a new record with `status: conflict` and `conflicts_with` referencing it. Both stay visible in the graph and in the rendered doc block; nothing is silently overwritten, because a contradiction may mean the underlying data genuinely changed.

The normative spec is [`protocol/SPEC.md`](protocol/SPEC.md) — precise enough that an independent implementation, in a different framework or language, could read and write compatible learnings without any other file in this repo. The reference implementation is the [`datahub-memory` skill](skill/datahub-memory/), which runs recall and retain against the DataHub MCP server from Claude Code.

### Why one JSON blob per value, not one property per field

DataHub structured properties are flat, entity-scoped key -> value-list pairs with no native nested/object type, but a learning has eight-plus fields that must travel together atomically. Modeling each field as its own `MULTIPLE`-cardinality property (`kind[]`, `claim[]`, `evidence[]`, ...) would require every reader and writer to reconstruct a record by matching array indices across several independently-mutable properties — one partial write and the arrays silently desync with no error. Packing one whole learning into a single JSON string value keeps every record atomic: an append is a single-value insert, an update or removal targets exactly one list element, and nothing else can be corrupted in the process. The cost — DataHub's structured-property search can't facet on a sub-field like confidence — is paid for by the documentation block, which is the human-facing surface for that. Full reasoning in [`protocol/SPEC.md` §5.1](protocol/SPEC.md).

## What's real / verified

Every claim below was checked against a live local DataHub OSS `v1.5.0.6` quickstart, not inferred from documentation. Full write-up in [`setup/NOTES-mcp-writes.md`](setup/NOTES-mcp-writes.md).

| Claim | Status |
|---|---|
| `MULTIPLE`-cardinality `string` structured property registers and applies to both `dataset` and `schemaField` entities | Verified — values round-trip byte-identical, up to 10,000 characters with no truncation |
| Structured-property writes **replace** the entire value list; they do not append | Verified (empirically reproduced the data-loss case: a naive second write left `[new_value]` where `[old_value, new_value]` was expected) — every writer must read-merge-write |
| Documentation-block splice (`<!-- agent-memory:begin/end -->` markers) is idempotent across repeated writes | Verified — a splice-twice test leaves exactly one marker pair with the second write's content, never two copies |
| DataHub MCP server (`mcp-server-datahub`) mutation tools work against OSS quickstart: `add_structured_properties`, `remove_structured_properties`, `update_description`, plus tag/term/owner/domain tools | Verified, server `>= 0.6.0`, launched with `TOOLS_IS_MUTATION_ENABLED=true` (18 tools registered; unregistered by default) — the default `uvx mcp-server-datahub` (no version pin) can resolve a stale cached `0.4.0` with no mutation tools at all |
| schemaField-scoped structured-property **writes** | Verified — `add_structured_properties` takes a schemaField urn directly with no extra handling. The high-level `datahub.sdk.Dataset` API cannot target schemaField urns at all (`SdkUsageError`); the MCP tool has no such gap |
| schemaField-scoped structured-property **reads** via MCP | **Not available.** `get_entities` and `list_schema_fields` return no structured-property values for schemaField urns as of `mcp-server-datahub` 0.6.0, even though the write to that same urn succeeded. Column-scoped recall requires a raw GraphQL query (`... on SchemaFieldEntity { structuredProperties { ... } }`) as a workaround. This is a read-path gap in the MCP server, not in DataHub's storage, and is a candidate upstream contribution — see the skill's [`references/mcp-tools-reference.md`](skill/datahub-memory/references/mcp-tools-reference.md) for the exact query. |

## Quickstart (reproduce from a clean machine)

Tested on Windows 11 / PowerShell + Git Bash, DataHub OSS `v1.5.0.6`, `acryl-datahub` CLI `1.6.0.16`, `uv` `0.11.32`.

**Prerequisites**: Docker Desktop, [`uv`](https://docs.astral.sh/uv/) (installs both `uv` and `uvx`), Claude Code.

> **Windows gotchas**
> - `datahub docker quickstart` can exit with code 1 and print a `UnicodeEncodeError` traceback on a fully successful run — its final success banner uses a `✔` character the default `cp1252` console codepage can't encode. Verify success with `docker ps` / the health checks below, not the CLI's exit code. Set `PYTHONIOENCODING=utf-8` before invoking `datahub` to avoid the cosmetic failure entirely.
> - `uv`/`uvx` may not be on `PATH` right after install without a shell restart; winget places the shims under `%LOCALAPPDATA%\Microsoft\WinGet\Links\`, the standalone installer under `%USERPROFILE%\.local\bin\`.

1. **Bring up DataHub OSS** (~7 min cold start — image pulls, container health):
   ```
   PYTHONIOENCODING=utf-8 datahub docker quickstart
   ```
   Verify with `docker ps` (or don't trust the CLI's own exit code — see the gotcha above): `http://localhost:9002` (UI, login `datahub`/`datahub`) and `http://localhost:8080/health` should both return healthy.

2. **Bring up the demo Postgres warehouse**:
   ```
   docker compose -f demo/docker-compose.yml up -d
   ```
   Postgres is now at `postgresql://demo:demo@localhost:5434/demo_warehouse` (port 5434, chosen to avoid colliding with DataHub's own Postgres/MySQL or other local containers).

3. **Install dependencies and seed the warehouse** (deterministic, seed 42, plants the 3 landmines described below — `fct_orders` 500 rows, `dim_customers` 100, `dim_products` 40, plus a `features_customer_ltv` SQL view over the first two, which gives the catalog a real lineage edge):
   ```
   uv sync
   uv run python setup/seed_warehouse.py
   ```
   Idempotent — drops and recreates the `ecommerce` schema on every run.

4. **Ingest the demo warehouse into DataHub** (3 tables + the view; DataHub's SQL parser derives the view's lineage automatically — no manual lineage wiring):
   ```
   PYTHONIOENCODING=utf-8 uvx --from "acryl-datahub[postgres]==1.6.0.16" datahub ingest -c setup/ingest_postgres.yml
   ```
   Expect 0 failures. Confirm `fct_orders`, `dim_customers`, `dim_products`, and `features_customer_ltv` are searchable under platform `postgres` in the UI at `http://localhost:9002`, each at urns of the form `urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.<table>,PROD)`, and that `features_customer_ltv`'s lineage tab shows `fct_orders` and `dim_customers` upstream.

5. **Register the structured property definition** (idempotent, safe to re-run):
   ```
   uv run python setup/register_properties.py
   ```
   Creates `io.datahub.agentMemory.learnings` (string, `MULTIPLE` cardinality, applicable to `dataset` and `schemaField`) via the SDK — the MCP server has no tool for defining a property, only for assigning values to one that already exists.

6. **Open the repo in Claude Code.** `.mcp.json` at the repo root auto-configures the DataHub MCP server (`uvx mcp-server-datahub@latest`, `TOOLS_IS_MUTATION_ENABLED=true`) — no manual setup. The `datahub-memory` skill is preinstalled at `.claude/skills/datahub-memory/` (a byte-identical copy of `skill/datahub-memory/`, which is the source of truth and the candidate for an upstream PR to `datahub-project/datahub-skills`) and triggers automatically on prompts that query or analyze a cataloged dataset. Fully quit and reopen Claude Code after any `.mcp.json` edit — it's read at session start, not hot-reloaded.

If something doesn't come up cleanly, `demo/README.md`'s Troubleshooting section covers the failure modes actually hit while building this (stale MCP tool cache resolving to a mutation-less server build, the property showing as unrecognized, Postgres port collisions).

## Run the demo

The full two-agent walkthrough is in [`demo/README.md`](demo/README.md):

1. `uv run python demo/reset_demo.py` — wipes any learnings from a prior take.
2. **Agent A** (fresh Claude Code session, prompt in `demo/prompts/agent_a.md`): asked for last month's revenue, has no memory, finds `fct_orders`, writes the naive query, gets a suspiciously large number, investigates, lands on the correct figure — then retains 3 learnings back to the graph.
3. Open the UI at `http://localhost:9002`, view `fct_orders` — the learnings are visible as structured-property values and as a rendered block in the Documentation tab.
4. **Agent B** (a second, brand-new Claude Code session — not a continuation of Agent A's context, prompt in `demo/prompts/agent_b.md`): asked to break down revenue by product line, recalls first, applies the cents conversion and completed-only filter on the first query, no rediscovery.
5. **Agent C** (third fresh session, prompt in `demo/prompts/agent_c.md`): an ML engineer about to retrain a customer-LTV model asks what's already known about `features_customer_ltv` and its inputs. Recall walks the lineage edge one hop upstream and surfaces `fct_orders`' learnings — knowledge earned by an analytics agent reaches an ML workflow through the graph, with neither agent knowing about the other.

[`examples/`](examples/) holds a real, pre-captured run of Agent A's retain output — `learnings-fct_orders.json` and `doc-block-fct_orders.md` — for judges who want to inspect the output without running the demo themselves.

## Repo layout

```
protocol/
  SPEC.md                     normative protocol spec — learning schema, recall/retain, conflicts

skill/datahub-memory/         reference implementation, the candidate upstream PR to datahub-skills
  SKILL.md                    operational workflow: setup, recall, retain, worked examples
  references/                 condensed protocol reference + empirically-verified MCP tool calls
  templates/                  JSON learning-record shape, markdown doc-block shape

setup/                        one-shot, idempotent setup scripts
  seed_warehouse.py           deterministic demo data + 3 planted landmines + LTV feature view
  register_properties.py      registers io.datahub.agentMemory.learnings on DataHub
  ingest_postgres.yml         ingestion recipe: demo Postgres -> DataHub (incl. view lineage)
  doctor.py                   one-command environment check — run this if anything misbehaves
  NOTES-datahub-quickstart.md raw findings: versions, ports, auth, Windows quirks
  NOTES-mcp-writes.md         raw findings: structured-property + description write-path verification

demo/                         the three-act scenario, runnable end-to-end
  docker-compose.yml          demo Postgres warehouse (port 5434)
  reset_demo.py               wipes learnings between takes
  prompts/                    agent_a.md, agent_b.md, agent_c.md — exact prompts used in the video
  README.md                   full walkthrough + troubleshooting

clients/                      independent implementation, written from the spec alone
  recall.py                   stdlib-only recall client — proves SPEC.md's interoperability claim

examples/                     real captured output, no run required to inspect it
  learnings-fct_orders.json   the 3 learnings, read back from DataHub's structured property
  doc-block-fct_orders.md     the rendered documentation block, read back byte-for-byte
  conflict-*.md / *.json      the section-8 conflict procedure, executed via a real migration

protocol/, skill/, setup/, demo/, examples/ are all referenced above; CLAUDE.md and PLAN.md
(repo root) are the internal working docs — project rules and build plan, not judge-facing.
```

## The demo scenario is constructed

The e-commerce warehouse in `demo/` is seeded, not real production data: 500 orders, 100 customers, 40 products, deterministic (seed 42), with three landmines planted on purpose:

| Landmine | Detail | Effect on naive revenue query |
|---|---|---|
| `fct_orders.amount` is in cents | `bigint`, no unit indicated by name or type | Off by 100x if not divided down |
| `fct_orders.status` includes cancelled/refunded orders | 80.8% completed / 14.4% cancelled / 4.8% refunded | Inflates revenue if not filtered to `status = 'completed'` |
| `dim_customers.customer_id` is legacy and 47% NULL | Real join key is `customer_key`, always populated | Silently drops or misjoins ~half of customers |

A naive query (no filter, no unit conversion) returns **4,668,271,415** ("$4.67B"); the correct query returns **$38,604,332.17**. Agent A is meant to walk into these landmines. That framing device — a controlled scenario built to force a costly discovery — is staged, and we say so here rather than presenting it as production footage.

What isn't staged is the mechanism. Every artifact in `examples/` is a genuine readback from a live local DataHub instance, written by the actual retain workflow through the actual MCP server, not hand-authored JSON. The structured-property round-trips, the read-merge-write requirement, the doc-block splice idempotency, and the schemaField read-path gap are all empirical findings from `setup/NOTES-mcp-writes.md`, reproduced against DataHub OSS `v1.5.0.6`. The scenario is a demonstration; what it demonstrates is real.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
