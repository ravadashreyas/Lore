# Demo harness: Agent A / B / C / D scenario

Everything needed to run the video's demo live, or to reproduce it for a retake:
Act 1 (Agent A, no memory), Act 2 (Agent B, recall from a single dataset),
Act 3 (Agent C, lineage-aware recall through an upstream hop), and Act 4
(Agent D, a denied mutation that becomes retained knowledge). The scenario is
described in the root `README.md` ("The demo scenario is constructed").
See `protocol/SPEC.md` for the mechanism it's demonstrating.

## Prerequisites

Run `uv run python setup/doctor.py` any time to check all of the below in one shot, with a fix for whatever fails.

1. **DataHub OSS quickstart running** (`docker ps` should show
   `datahub-datahub-gms-quickstart-1` and `datahub-frontend-quickstart-1` healthy).
   Bring it up with `datahub docker quickstart` if it isn't. UI: `http://localhost:9002`
   (`datahub`/`datahub`). GMS: `http://localhost:8080` (unauthenticated).
2. **Demo Postgres warehouse running**: `docker compose -f demo/docker-compose.yml up -d`
   → `dhmem-demo-postgres` on host port **5434**
   (`postgresql://demo:demo@localhost:5434/demo_warehouse`).
3. **The 4 demo datasets ingested into DataHub.** If the UI at `http://localhost:9002`
   doesn't show `fct_orders`, `dim_customers`, `dim_products`, `features_customer_ltv`
   under platform `postgres`, run the ingestion recipe (`setup/ingest_postgres.yml`). See
   `setup/NOTES-datahub-quickstart.md` §Ingestion for the exact command.
   `features_customer_ltv` is a real SQL view (`setup/seed_warehouse.py`) over
   `fct_orders` + `dim_customers`; the postgres source's SQL-parsed view lineage
   (`include_view_lineage`, on by default) gives it a genuine 1-hop-upstream lineage
   edge to both, with no extra lineage-seeding step required.
4. **The `io.datahub.agentMemory.learnings` structured property registered.** One-time:
   `uv run python setup/register_properties.py` (idempotent, safe to re-run).
5. **`uv`/`uvx` available.** On this dev machine the WinGet install isn't always on
   `PATH`; fall back to
   `$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\`
   if `uvx` isn't found.
6. **Claude Code opened at the repo root**, so it picks up `.mcp.json` (the `datahub`
   MCP server: `uvx mcp-server-datahub@latest`, `TOOLS_IS_MUTATION_ENABLED=true`)
   automatically. No manual MCP setup needed per session.
7. **`lore-permissions.json` present at the repo root** (committed, so it is unless
   you deleted it). It makes all four demo tables read-only to agents, which Act 4
   depends on. Deleting the file turns the permissions layer off entirely;
   `hooks/README.md` documents the format.
8. **Approve the project's hooks and MCP server when Claude Code asks.** Both are
   defined by this repo (`.claude/settings.json`, `.mcp.json`) and Claude Code
   requires a one-time per-project approval before running them. If the enforced-recall
   hook never fires or the `datahub` MCP tools never appear, the approval prompt is
   the first thing to check. Verified empirically: in a session without the approval,
   the hook silently never executes (fail-open at the harness level, by design).

## How the skill gets loaded

The protocol and workflow live in `skill/datahub-learnings/` (the repo-facing copy,
this is what gets proposed upstream to `datahub-project/datahub-skills`, and what
`protocol/SPEC.md` and the rest of this repo point to). That path is **not** where
Claude Code looks for skills automatically.

Claude Code auto-discovers project skills at **`.claude/skills/<skill-name>/SKILL.md`**
relative to the repo root. Confirmed against the current Claude Code Skills
documentation, no other mechanism (no `settings.json` key for an arbitrary skills
directory, no plugin/marketplace install) makes an arbitrary path auto-load. So this
repo carries a second copy: **`.claude/skills/datahub-learnings/`**, byte-identical to
`skill/datahub-learnings/` at the time it was copied. Any fresh Claude Code session
opened in this repo picks it up with no extra step.

**Consequence for anyone editing the skill**: `skill/datahub-learnings/` is the source of
truth (and the thing under review for the upstream PR); if you change it, re-copy it
into `.claude/skills/datahub-learnings/` or the running demo will use a stale copy. There
is no symlink here. Windows symlinks need elevated privileges/dev mode, and a plain
copy is simpler for judges to reason about.

## Demo flow

1. **Reset**: `uv run python demo/reset_demo.py`: wipes any learnings from a prior
   take so Agent A starts from a clean slate. Idempotent; prints what it removed (or
   confirms there was nothing to remove).
2. **Agent A session**: open a fresh Claude Code session at the repo root, paste the
   prompt from `demo/prompts/agent_a.md`. Watch it: search DataHub for the right
   table, query Postgres directly, get a suspiciously large naive number, investigate,
   land on the correct $38.6M figure, then invoke the datahub-learnings skill's retain
   workflow to write 3 learnings back to `fct_orders`.
3. **Show DataHub UI**: open `http://localhost:9002` (login `datahub`/`datahub`),
   navigate to `fct_orders`, show the `io.datahub.agentMemory.learnings` structured
   property values and the rendered `## Agent learnings` block now sitting in the
   dataset's Documentation tab.
4. **Agent B session**: open a **second, brand-new** Claude Code session (do not
   reuse Agent A's context, and do not re-run reset in between), paste the prompt
   from `demo/prompts/agent_b.md`. Watch it recall first: it should apply the cents
   conversion and completed-only filter on the first query, no rediscovery.
5. **Agent C session, lineage-aware recall**: open a **third, brand-new** Claude
   Code session (same rule: don't reset in between), paste the prompt from
   `demo/prompts/agent_c.md`. It asks about `features_customer_ltv` (a downstream
   ML feature view that has no learnings of its own). Watch recall walk 1 lineage hop
   upstream (SPEC.md §6 default scope) to `fct_orders`, inherit its cents and
   completed-only learnings, and report them as feature-pipeline risks. This is the
   beat that demonstrates recall actually using lineage, not just a single dataset's
   own learnings.
6. **Agent D session, the governance beat**: open a **fourth, brand-new** Claude
   Code session (don't reset), paste the prompt from `demo/prompts/agent_d.md`. It
   asks the agent to physically delete cancelled/refunded rows from `fct_orders`.
   Recall surfaces the verified status-filter pattern first; the `DELETE` itself is
   denied by `hooks/enforce_permissions.py` (the repo-root `lore-permissions.json`
   grants agents `read` only on the warehouse), with a denial message reminding the
   agent the learnings layer is still open. Watch it report the block, recommend the
   filter instead of the deletion, and retain a `caveat` — the beat that shows
   **data access is policy, sticky-note access never is**.

`examples/` holds a real, pre-captured run of step 2's retain output (`learnings-fct_orders.json`,
`doc-block-fct_orders.md`) for judges who don't run the demo themselves. See
`examples/README.md`.

## Rehearsal record (2026-07-30)

The full three-act scenario was executed end to end by fresh agent sessions before
any video was recorded, using the skill's documented GraphQL fallback (the
interactive MCP path loads only in a fresh Claude Code session). Outcomes:

- **Act 1 (Agent A, empty memory)**: naive June sum read as $4.67B, investigated,
  found the cents and completed-only landmines, answered $38,604,332.17 (correct),
  retained 3 learnings. 8 SQL queries.
- **Act 2 (Agent B, fresh session)**: recalled first; its **first analysis query**
  already applied the cents conversion and completed-only filter. Correct
  product-line breakdown summing exactly to the verified total. 2 SQL queries
  (vs Agent A's 8). Unprompted, it retained a 4th learning (the breakdown query)
  with a correct read-merge-write: nothing was lost.
- **Act 3 (Agent C, fresh session)**: recall walked 1 lineage hop upstream from
  `features_customer_ltv` and inherited `fct_orders`' learnings; verified the view
  honors them (100/100 rows recomputed identical). It then independently
  discovered the `customer_id` 47%-NULL join trap and an unplanted finding (3
  cold-start customers with NULL first/last-order dates that could break feature
  pipelines), and retained both.
- **Governance loop, live**: `tools/lint_learnings.py` caught a real violation in
  Act 3's output (a 290-character claim, over the spec's 280 cap). The claim was
  trimmed via read-merge-write and the catalog re-linted clean: 7 learnings, 0
  violations.

Run `demo/reset_demo.py` before a fresh take; the rehearsal's learnings are wiped
like any other state.

## Troubleshooting

- **Agent's MCP tool calls fail with "mutation tools not available" or it can't find
  `add_structured_properties`/`update_description`.** The MCP server resolved a stale
  cached build with no mutation tools, or `TOOLS_IS_MUTATION_ENABLED` didn't reach it.
  Confirm `.mcp.json` has `"TOOLS_IS_MUTATION_ENABLED": "true"` in `env` and the args
  are `["mcp-server-datahub@latest"]` (the `@latest` pin, not a bare `uvx
  mcp-server-datahub`, a bare invocation can resolve a stale `0.4.0` from `uv`'s
  package cache with no mutation tools at all). Fully quit and reopen the Claude Code
  session after editing `.mcp.json`: it's read at session start, not hot-reloaded.
- **Agent B doesn't seem to recall anything.** Check `demo/reset_demo.py` wasn't run
  between Agent A and Agent B (it wipes what Agent A just wrote). Also confirm
  Agent A's session actually completed its retain step: check `fct_orders` in the UI
  at `http://localhost:9002` for its structured property values directly.
- **Agent C doesn't inherit `fct_orders`'s learnings.** Same root cause as the Agent B
  case (reset ran too late, or Agent A never retained) plus one more: confirm
  `features_customer_ltv` actually shows `fct_orders` as 1-hop upstream in the DataHub
  UI's Lineage tab. If it doesn't, ingestion likely ran before `include_views: true`
  was set in `setup/ingest_postgres.yml`, or ran against a stale seed. Re-run
  `setup/seed_warehouse.py` then `setup/ingest_postgres.yml`'s ingestion command.
- **Skill doesn't trigger / Claude Code doesn't seem to know about it.** Confirm
  `.claude/skills/datahub-learnings/SKILL.md` exists (not just `skill/datahub-learnings/`)
  and the session was opened fresh after it was added. See "How the skill gets
  loaded" above.
- **DataHub UI shows the property as unrecognized / writes fail with an unknown
  property error.** `io.datahub.agentMemory.learnings` isn't registered yet: run
  `uv run python setup/register_properties.py`.
- **Postgres queries fail to connect.** Confirm `dhmem-demo-postgres` is up
  (`docker ps`) and listening on host port `5434`, not the default `5432` (that port
  may be taken by an unrelated container on the demo machine).
- **Windows console errors / mojibake from the `datahub` CLI.** Set
  `PYTHONIOENCODING=utf-8` before invoking `datahub`: its success banner uses a
  unicode checkmark that the default Windows codepage can't encode; this is cosmetic,
  not a real failure (see `setup/NOTES-datahub-quickstart.md`).
