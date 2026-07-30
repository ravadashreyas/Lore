# hooks/ -- enforced recall

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
