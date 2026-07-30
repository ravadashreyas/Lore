# Agent A prompt (paste into a fresh Claude Code session)

Prerequisites: run `demo/reset_demo.py` first so this session starts from a clean
slate (see `demo/README.md`). Open Claude Code in the repo root so `.mcp.json` picks
up the DataHub MCP server automatically.

Paste the following as the first message:

---

You're a data analyst at an e-commerce company. I need to know: **what was our
revenue in June 2026?**

Use DataHub to find the right table (there's an ecommerce warehouse cataloged in
there). Then query Postgres directly to compute the number: connection string is
`postgresql://demo:demo@localhost:5434/demo_warehouse`.

Finance mentioned June was roughly **$38.6M**, so sanity-check your answer against
that before you give it to me. If you're way off, figure out why rather than just
reporting whatever the first query gives you.

Once you're confident in the answer, use the datahub-learnings skill to retain
whatever you learned along the way so the next person who has to do this doesn't
have to rediscover it.
