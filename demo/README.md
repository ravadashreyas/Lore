# Demo harness — Agent A / Agent B / Agent C scenario

Everything needed to run the video's demo live, or to reproduce it for a retake:
Act 1 (Agent A, no memory) and Act 2 (Agent B, recall from a single dataset) per
`PLAN.md` §5, plus Act 3 (Agent C, lineage-aware recall through an upstream hop).
See `protocol/SPEC.md` for the mechanism it's demonstrating.

## Prerequisites

1. **DataHub OSS quickstart running** (`docker ps` should show
   `datahub-datahub-gms-quickstart-1` and `datahub-frontend-quickstart-1` healthy).
   Bring it up with `datahub docker quickstart` if it isn't. UI: `http://localhost:9002`
   (`datahub`/`datahub`). GMS: `http://localhost:8080` (unauthenticated).
2. **Demo Postgres warehouse running**: `docker compose -f demo/docker-compose.yml up -d`
   → `dhmem-demo-postgres` on host port **5434**
   (`postgresql://demo:demo@localhost:5434/demo_warehouse`).
3. **The 4 demo datasets ingested into DataHub.** If `http://localhost:8080` doesn't
   show `fct_orders`, `dim_customers`, `dim_products`, `features_customer_ltv` under
   platform `postgres`, run the ingestion recipe (`setup/ingest_postgres.yml`) — see
   `setup/NOTES-datahub-quickstart.md` §Ingestion for the exact command.
   `features_customer_ltv` is a real SQL view (`setup/seed_warehouse.py`) over
   `fct_orders` + `dim_customers`; the postgres source's SQL-parsed view lineage
   (`include_view_lineage`, on by default) gives it a genuine 1-hop-upstream lineage
   edge to both, with no extra lineage-seeding step required.
4. **The `io.datahub.agentMemory.learnings` structured property registered.** One-time:
   `uv run python setup/register_properties.py` (idempotent — safe to re-run).
5. **`uv`/`uvx` available.** On this dev machine the WinGet install isn't always on
   `PATH`; fall back to
   `$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\`
   if `uvx` isn't found.
6. **Claude Code opened at the repo root**, so it picks up `.mcp.json` (the `datahub`
   MCP server: `uvx mcp-server-datahub@latest`, `TOOLS_IS_MUTATION_ENABLED=true`)
   automatically. No manual MCP setup needed per session.

## How the skill gets loaded

The protocol and workflow live in `skill/datahub-memory/` (the repo-facing copy —
this is what gets proposed upstream to `datahub-project/datahub-skills`, and what
`protocol/SPEC.md` and the rest of this repo point to). That path is **not** where
Claude Code looks for skills automatically.

Claude Code auto-discovers project skills at **`.claude/skills/<skill-name>/SKILL.md`**
relative to the repo root — confirmed against the current Claude Code Skills
documentation, no other mechanism (no `settings.json` key for an arbitrary skills
directory, no plugin/marketplace install) makes an arbitrary path auto-load. So this
repo carries a second copy: **`.claude/skills/datahub-memory/`**, byte-identical to
`skill/datahub-memory/` at the time it was copied. Any fresh Claude Code session
opened in this repo picks it up with no extra step.

**Consequence for anyone editing the skill**: `skill/datahub-memory/` is the source of
truth (and the thing under review for the upstream PR); if you change it, re-copy it
into `.claude/skills/datahub-memory/` or the running demo will use a stale copy. There
is no symlink here — Windows symlinks need elevated privileges/dev mode, and a plain
copy is simpler for judges to reason about.

## Demo flow

1. **Reset**: `uv run python demo/reset_demo.py` — wipes any learnings from a prior
   take so Agent A starts from a clean slate. Idempotent; prints what it removed (or
   confirms there was nothing to remove).
2. **Agent A session**: open a fresh Claude Code session at the repo root, paste the
   prompt from `demo/prompts/agent_a.md`. Watch it: search DataHub for the right
   table, query Postgres directly, get a suspiciously large naive number, investigate,
   land on the correct $38.6M figure, then invoke the datahub-memory skill's retain
   workflow to write 3 learnings back to `fct_orders`.
3. **Show DataHub UI**: open `http://localhost:8080` (or `:9002` for the full UI),
   navigate to `fct_orders`, show the `io.datahub.agentMemory.learnings` structured
   property values and the rendered `## Agent learnings` block now sitting in the
   dataset's Documentation tab.
4. **Agent B session**: open a **second, brand-new** Claude Code session (do not
   reuse Agent A's context, and do not re-run reset in between), paste the prompt
   from `demo/prompts/agent_b.md`. Watch it recall first — it should apply the cents
   conversion and completed-only filter on the first query, no rediscovery.
5. **Agent C session — lineage-aware recall**: open a **third, brand-new** Claude
   Code session (same rule: don't reset in between), paste the prompt from
   `demo/prompts/agent_c.md`. It asks about `features_customer_ltv` — a downstream
   ML feature view that has no learnings of its own. Watch recall walk 1 lineage hop
   upstream (SPEC.md §6 default scope) to `fct_orders`, inherit its cents and
   completed-only learnings, and report them as feature-pipeline risks. This is the
   beat that demonstrates recall actually using lineage, not just a single dataset's
   own learnings.

`examples/` holds a real, pre-captured run of step 2's retain output (`learnings-fct_orders.json`,
`doc-block-fct_orders.md`) for judges who don't run the demo themselves — see
`examples/README.md`.

## Troubleshooting

- **Agent's MCP tool calls fail with "mutation tools not available" or it can't find
  `add_structured_properties`/`update_description`.** The MCP server resolved a stale
  cached build with no mutation tools, or `TOOLS_IS_MUTATION_ENABLED` didn't reach it.
  Confirm `.mcp.json` has `"TOOLS_IS_MUTATION_ENABLED": "true"` in `env` and the args
  are `["mcp-server-datahub@latest"]` (the `@latest` pin, not a bare `uvx
  mcp-server-datahub` — a bare invocation can resolve a stale `0.4.0` from `uv`'s
  package cache with no mutation tools at all). Fully quit and reopen the Claude Code
  session after editing `.mcp.json` — it's read at session start, not hot-reloaded.
- **Agent B doesn't seem to recall anything.** Check `demo/reset_demo.py` wasn't run
  between Agent A and Agent B (it wipes what Agent A just wrote). Also confirm
  Agent A's session actually completed its retain step — check
  `http://localhost:8080` for `fct_orders`'s structured property values directly.
- **Agent C doesn't inherit `fct_orders`'s learnings.** Same root cause as the Agent B
  case (reset ran too late, or Agent A never retained) plus one more: confirm
  `features_customer_ltv` actually shows `fct_orders` as 1-hop upstream in the DataHub
  UI's Lineage tab. If it doesn't, ingestion likely ran before `include_views: true`
  was set in `setup/ingest_postgres.yml`, or ran against a stale seed — re-run
  `setup/seed_warehouse.py` then `setup/ingest_postgres.yml`'s ingestion command.
- **Skill doesn't trigger / Claude Code doesn't seem to know about it.** Confirm
  `.claude/skills/datahub-memory/SKILL.md` exists (not just `skill/datahub-memory/`)
  and the session was opened fresh after it was added — see "How the skill gets
  loaded" above.
- **DataHub UI shows the property as unrecognized / writes fail with an unknown
  property error.** `io.datahub.agentMemory.learnings` isn't registered yet — run
  `uv run python setup/register_properties.py`.
- **Postgres queries fail to connect.** Confirm `dhmem-demo-postgres` is up
  (`docker ps`) and listening on host port `5434`, not the default `5432` (that port
  may be taken by an unrelated container on the demo machine).
- **Windows console errors / mojibake from the `datahub` CLI.** Set
  `PYTHONIOENCODING=utf-8` before invoking `datahub` — its success banner uses a
  unicode checkmark that the default Windows codepage can't encode; this is cosmetic,
  not a real failure (see `setup/NOTES-datahub-quickstart.md`).
