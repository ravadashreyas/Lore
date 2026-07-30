# Lore (plugin)

Tribal knowledge for AI agents, stored in DataHub. This plugin packages the
[Lore](https://github.com/ravadashreyas/Lore) agent-memory protocol's reference
implementation so any project can install it with two commands.

## What gets installed

- **Skill** (`skills/datahub-learnings/`): the recall/retain workflow. Recall reads a
  dataset's prior learnings (and one lineage hop upstream) before an agent touches it;
  retain writes back what the agent learned, as a structured property plus a rendered
  documentation block on the table's DataHub page.
- **Hook** (`hooks/enforce_recall.py`): a `PreToolUse` hook on `Bash` that blocks a
  command touching a cataloged table once per session until its unsurfaced learnings
  have been shown, then lets the retry through.
- **MCP server** (`.mcp.json`): `mcp-server-datahub@latest`, configured with
  `TOOLS_IS_MUTATION_ENABLED=true` so the skill can write learnings back, not just read
  them.

## Prerequisites

- A reachable DataHub instance (defaults to `http://localhost:8080`; set `LORE_GMS_URL`
  if yours lives elsewhere).
- The `io.datahub.agentMemory.learnings` structured property registered once on that
  instance. See `skills/datahub-learnings/SKILL.md`'s Setup section for the script link.

## The hook's behavior

- Fires before every `Bash` tool call, and only acts on commands that mention a
  cataloged table name.
- Blocks once per (session, table) with the unseen learnings on stderr, then allows the
  identical retry through.
- **Fails open**: DataHub unreachable, a timeout, a malformed response, or any
  unexpected error all resolve to "allow the command," never to a stuck shell.

## Double-loading note

This plugin's skill is a copy of the one that lives at `skill/datahub-learnings/` in the
[Lore repo](https://github.com/ravadashreyas/Lore) itself, and its hook is a copy of
`hooks/enforce_recall.py` there. Plugin components merge with a project's own `.claude/`
config rather than overriding it. If you are working inside a checkout of the Lore repo,
that repo's own `.claude/skills/datahub-learnings/` and `hooks/enforce_recall.py` are
already the canonical originals: do not also install this plugin there, or you will see
the skill listed twice (harmless, just redundant).

Everywhere else, the repo copies are the source of truth and this plugin tracks them;
if the two ever drift, treat `skill/`, `hooks/`, `.mcp.json`, and `.claude/` in the Lore
repo as correct.

## Uninstall

`/plugin uninstall lore` (or remove it from your plugin config). This does not touch
any learnings already written to DataHub: they live in the metadata graph, not in the
plugin.
