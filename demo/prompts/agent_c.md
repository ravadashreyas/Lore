# Agent C prompt (paste into a THIRD, FRESH Claude Code session)

Run this only after Agent A's session (`demo/prompts/agent_a.md`) has finished and
retained its learnings on `fct_orders` — do not reset the demo in between. Agent C
demonstrates **lineage-aware recall**: the target dataset here (`features_customer_ltv`)
has no learnings of its own, but it's a downstream view built on `fct_orders`, so
recall should walk 1 lineage hop upstream and inherit what Agent A already learned.
Open a brand new Claude Code session (new window/tab, empty context) in the repo
root so `.mcp.json` picks up the DataHub MCP server automatically.

Paste the following as the first message:

---

I'm about to retrain our customer LTV model. Before I do, check
`features_customer_ltv` and its upstream data for anything already known that
could bite the model — use the datahub-memory skill to recall, then summarize
the risks.

---

## Expected outcome

`features_customer_ltv` has no learnings of its own (it's a new view). Recall's
lineage step (`get_lineage(upstream=true, max_hops=1)`, SPEC.md §6) finds
`fct_orders` and `dim_customers` exactly one hop upstream, and picks up
`fct_orders`'s existing learnings: `amount` is in cents, and revenue must
exclude cancelled/refunded orders (`status != 'completed'`). The agent should
report these as **feature-pipeline risks** — e.g. "if `features_customer_ltv`
or a consumer of it ever recomputes revenue from raw `fct_orders.amount`
without dividing by 100, or without the completed-only filter, LTV values will
be off by 100x or inflated by non-revenue orders" — and can confirm, by reading
`setup/seed_warehouse.py`'s view definition, that the view already applies both
correctly. So the story this beat tells is **"the inherited learnings confirm
the view was built right, and warn whoever touches it next"**, not that a bug
was found. This is 1 hop of recall (`features_customer_ltv` -> `fct_orders`),
consistent with SPEC.md §6's default scope — nowhere does this claim to reach
a downstream `customer_ltv_model` (that would be a second hop and is out of
scope for this beat).
