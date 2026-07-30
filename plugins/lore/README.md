# Lore (plugin)

Tribal knowledge for AI agents, stored in DataHub. This plugin packages the
[Lore](https://github.com/ravadashreyas/Lore) agent-memory protocol's reference
implementation so any project can install it with two commands.

## What gets installed

- **Skill** (`skills/datahub-learnings/`): the recall/retain workflow. Recall reads a
  dataset's prior learnings (and one lineage hop upstream) before an agent touches it;
  retain writes back what the agent learned, as a structured property plus a rendered
  documentation block on the table's DataHub page.
- **Hooks** (`hooks/`): two `PreToolUse` hooks on `Bash`. `enforce_recall.py` blocks a
  command touching a cataloged table once per session until its unsurfaced learnings
  have been shown, then lets the retry through. `enforce_permissions.py` grants
  read/update/write per table and per column of the actual data, driven by a
  `lore-permissions.json` in your project root (no file = off; start from
  `hooks/permissions.example.json`), while recall/retain of the learnings themselves is
  always allowed.
- **MCP server** (`.mcp.json`): `mcp-server-datahub@0.6.0` (pinned to the version every
  claim in the Lore repo was verified against), configured with
  `TOOLS_IS_MUTATION_ENABLED=true` so the skill can write learnings back, not just read
  them.

## Prerequisites

- A reachable DataHub instance (defaults to `http://localhost:8080`; set `LORE_GMS_URL`
  if yours lives elsewhere).
- The `io.datahub.agentMemory.learnings` structured property registered once on that
  instance. See `skills/datahub-learnings/SKILL.md`'s Setup section for the script link.

## The hooks' behavior

- Both fire before every `Bash` tool call, and only act on commands that mention a
  cataloged (or permission-listed) table name.
- Recall blocks once per (session, table) with the unseen learnings on stderr, then
  allows the identical retry through. Permissions denials are deterministic: blocked
  every time until `lore-permissions.json` changes.
- **Fail open**: DataHub unreachable, a timeout, a malformed response, or any
  unexpected error all resolve to "allow the command," never to a stuck shell. The one
  deliberate exception: a *malformed* `lore-permissions.json` fails closed rather than
  silently allowing everything.

## Double-loading note

This plugin's skill is a copy of the one that lives at `skill/datahub-learnings/` in the
[Lore repo](https://github.com/ravadashreyas/Lore) itself, and its hooks are copies of
`hooks/enforce_recall.py` and `hooks/enforce_permissions.py` there. Plugin components merge with a project's own `.claude/`
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
