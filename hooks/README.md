# hooks/ -- enforced recall + data permissions

Two independent `PreToolUse` hooks on `Bash`:

- `enforce_recall.py` -- blocks a command touching a cataloged table once per session
  until its unsurfaced learnings have been shown (first section below).
- `enforce_permissions.py` -- grants an agent read/update/write per table and per
  column of the actual data, while the learnings layer (the sticky notes) stays
  accessible no matter what (second section).

## Enforced recall

`protocol/SPEC.md` SS9 admits a hole: "The protocol defines what recall must do when
performed (SS6), but does not -- and in v1 cannot -- technically force an agent to
perform it before acting. Compliance is a property of the skill/agent implementation,
not of DataHub itself." An agent that skips the `datahub-learnings` skill's recall step
(forgets, gets distracted mid-task, or is a different agent entirely that never loaded
the skill) queries a landmine table with zero friction and re-derives -- or silently
gets wrong -- exactly what a prior agent already paid to learn.

`enforce_recall.py` is a Claude Code **PreToolUse hook** that turns recall from
etiquette into infrastructure. It doesn't live in agent judgment; it runs outside the
model entirely, before every `Bash` tool call, and the shell itself is the enforcement
point.

## The block-once-with-knowledge pattern

1. The agent's Bash command is intercepted before it runs.
2. The hook extracts cataloged DataHub table names that appear as whole words in the
   command (`SELECT ... FROM fct_orders`, a `psql` one-liner, a Python DB-API call --
   anything, because it matches on the table name itself, not on "looks like SQL").
3. For each matched table, it runs the same recall query shape as `clients/recall.py`:
   table-level + schemaField-level learnings, plus every entity exactly one lineage hop
   upstream (SPEC SS6's scope), with `disputed`/`conflict` status surfaced rather than
   silently resolved (SPEC SS8).
4. If any of that is non-empty and hasn't been shown yet this session, the hook
   **blocks the command once** (exit code 2) and puts the learnings on stderr. Claude
   Code feeds stderr back to the model as the reason the tool call was denied.
5. The agent reads the learnings and retries the same command. This time the table is
   marked seen for this session, so the hook allows it through (exit code 0).

The command never silently succeeds ignorant of a landmine, and it never loops forever
either -- exactly one block per (session, table), then it's out of the way.

## Wiring (`.claude/settings.json`)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run python hooks/enforce_recall.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

Claude Code sends the tool-call JSON (`session_id`, `tool_name`, `tool_input.command`,
`cwd`) on stdin and reads exit code + stderr per the contract above. The script is
stdlib-only, so `uv run python ...` and a plain `python hooks/enforce_recall.py` behave
identically -- `uv` is not a hard dependency of the hook itself, only how this repo's
`settings.json` happens to invoke it.

Environment variables:

- `LORE_GMS_URL` -- DataHub GMS base URL. Defaults to `http://localhost:8080`.
- `TMP` / `TEMP` -- base directory for the catalog cache and session markers (under a
  `lore_hook/` subdirectory). Falls back to `tempfile.gettempdir()`.

## Fail-open guarantees

A broken guardrail must never break the user's shell. The hook exits 0 (allow, no
stderr) whenever it cannot confidently say "block":

- stdin isn't valid JSON, or isn't a `Bash` tool call.
- DataHub GMS is unreachable, times out (internal HTTP calls are capped at 5s), or
  returns a GraphQL error -- covers the catalog fetch and every learnings/lineage
  query.
- The command references no cataloged table name.
- A matched table (and its upstream hop) has zero learnings, or every learning for it
  was already surfaced this session.
- A structured-property value fails to parse as JSON (skipped, not fatal, per SPEC
  SS6's "discard with a logged warning, not a crash" -- the hook drops the warning
  entirely on non-blocking runs so it never writes to stderr except when it blocks).
- Any other unexpected exception, caught at the top level.

Only one path exits non-zero without blocking: a `sys.exit(2)` with the learnings
message. Every other outcome is `sys.exit(0)`.

## Honest limits

- **Word-boundary name matching, not SQL parsing.** The hook has no idea whether a
  command is actually a query. It just checks whether a cataloged table name shows up
  as a whole word (`\btable_name\b`, case-insensitive) anywhere in the command string.
  This deliberately catches `psql`, raw Python DB-API calls, and anything else that
  mentions the table, at the cost of also matching in places that aren't really a query
  (a comment, a filename). Accepted tradeoff: SPEC SS9 already concedes recall
  enforcement can't be perfect, and false positives are a free extra nudge, not a
  correctness problem the way a false negative would be.
- **Catalog is a snapshot, cached up to 5 minutes.** A table registered in DataHub in
  the last few minutes may not be recognized yet. Refreshes automatically after the TTL
  or if the cache file is missing/corrupt.
- **`Bash`-tool only.** A different tool (a hypothetical direct-Postgres MCP tool, a
  notebook cell) that queries the same table bypasses this hook entirely; the
  `PreToolUse` matcher would need a second entry to cover it.
- **Session markers are per (session_id, table) in a temp directory**, not in DataHub
  and not shared across machines. They survive only as long as the temp dir does, and
  a table is marked "seen" only under the name the agent used to reach it -- if a
  command names `features_customer_ltv` (surfacing `fct_orders`' learnings via the
  upstream hop) and a *later* command in the same session names `fct_orders` directly,
  the hook will show those same learnings again, because the marker was written for
  `features_customer_ltv`, not for `fct_orders` itself.
- **No retry loop protection beyond one block.** If the agent's retry still contains
  the same table name, it passes (the marker was written before the block was raised),
  but this hook has no way to confirm the agent actually *applied* the learnings --
  only that it saw them.

## Data permissions (`enforce_permissions.py`)

Recall governs what an agent *knows* before touching data; this hook governs what it
may *do* to the data. The design mirrors the protocol's core asymmetry: an agent's
access to row data is a policy decision that varies by agent and task, but its access
to the learnings layer never is. An agent locked out of a table can still read its
sticky notes (recall) and still write new ones (retain) -- being denied a query is
itself often worth retaining.

### Toggling permissions

The toggle is a JSON file: `lore-permissions.json` in the project root (or wherever
`LORE_PERMS_FILE` points). **No file = the feature is off** and every command passes.
Copy [`permissions.example.json`](permissions.example.json) there and edit to enable:

```json
{
  "default": ["read", "update", "write"],
  "tables": {
    "fct_orders": { "allow": ["read"] },
    "dim_customers": {
      "allow": ["read"],
      "columns": { "name": [] }
    }
  }
}
```

- `default` -- operations allowed on any cataloged table not listed under `tables`.
- `tables.<name>.allow` -- operations allowed on that table's data.
- `tables.<name>.columns.<column>` -- override for one column; `[]` means no access
  at all. Columns not listed inherit the table's `allow`.

The three operations, judged from SQL verbs appearing as whole words in the command:

| Operation | Verbs that require it |
|---|---|
| `read` | anything that mentions the table with no mutating verb (`SELECT`, `psql`, a DB-API call...) |
| `update` | `UPDATE` |
| `write` | `INSERT`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `CREATE`, `COPY`, `MERGE`, `GRANT`, `REVOKE` |

### The sticky-notes exemption

Commands aimed at the metadata layer are never blocked, whatever the config says:
anything containing `agentMemory`, `structuredProperty`, or `/api/graphql` (the
GraphQL fallback path for recall/retain). MCP structured-property tools aren't `Bash`
calls at all, so they never pass through this hook either. Every denial message
reminds the agent of this: if it learned something before being blocked, it can and
should still retain it.

### Denial semantics

Unlike recall's block-once pattern, a denial here is deterministic: the same command
is blocked with exit 2 every time until the config changes. One deliberate exception
to the repo's fail-open stance: a **malformed** `lore-permissions.json` fails
*closed* (every command blocked with a fix-it message) -- an access-control file the
operator wrote deliberately must never degrade silently to allow-everything. A
*missing* file, an unreachable DataHub (config-listed tables are still enforced;
only `default` coverage of unlisted cataloged tables needs the catalog), or any
unexpected error still fail open, same as the recall hook.

### Honest limits

Same word-boundary matching as the recall hook, same tradeoffs: it matches table and
column names anywhere in the command string, so a command mentioning a locked column
name in a comment or filename is also denied (false positives are friction, not
data loss), and it is a guardrail against agent mistakes, not a security boundary
against an adversarial agent -- real row-level security belongs in the database's
own GRANTs.
