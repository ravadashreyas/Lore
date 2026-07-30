# Agent B prompt (paste into a SECOND, FRESH Claude Code session)

Run this only after Agent A's session (`demo/prompts/agent_a.md`) has finished and
retained its learnings. Do not reset the demo in between: Agent B is meant to
inherit what Agent A wrote back to DataHub. Open a brand new Claude Code session
(new window/tab, empty context) in the repo root so `.mcp.json` picks up the
DataHub MCP server automatically.

Paste the following as the first message:

---

I need a breakdown of **June 2026 revenue by product line**.

Before you query anything, use the datahub-memory skill to recall what's already
known about this data, then run the query.
