# Eval prompt templates

Two prompt templates for the with/without-memory eval (`eval/README.md`). The
orchestrator pastes one of these, with `{QUESTION}` substituted for one of the
six questions in `eval/ground_truth.json`, as the first message into a fresh
Claude Code session (empty context, no prior turns) in this repo. Each
question x condition pair gets its own fresh session; nothing is reused
across questions or across conditions.

Why the file-reading prohibition exists: this repo's own README, `demo/`
prompts, and `setup/seed_warehouse.py` describe the three planted landmines
(cents-not-dollars, cancelled/refunded inflating naive revenue, the
half-null `customer_id` join trap) in plain language. An agent that reads
any of those files has been handed the answer key regardless of which
condition it's in, which would contaminate the no-memory arm (the entire
point of that arm is to see whether an agent without institutional memory
re-derives or misses the landmines on its own) and make the with-memory
arm's advantage look bigger or smaller than it really is. Both templates
below carry the same prohibition for that reason; Template B's carve-out is
narrow (only `clients/recall.py`'s own output, not its source) so that the
memory condition still can't peek at the landmine descriptions directly.

---

## Template A (no memory)

```
You're a data analyst at an e-commerce company. Answer this question:

{QUESTION}

Connect to the warehouse and compute the answer yourself with SQL. Connection
string: postgresql://demo:demo@localhost:5434/demo_warehouse

You can run queries either with:
  docker exec dhmem-demo-postgres psql -U demo -d demo_warehouse -c "<sql>"
or:
  uv run python -c "<python using psycopg2>"

HARD RULES:
- Do not read any files in this repository.
- Do not use any file under clients/, tools/, examples/, demo/, protocol/, or
  skill/.
- Do not browse DataHub (the UI, the MCP server, or any DataHub API).
- Work only from what you discover by querying Postgres directly.

When you're done, report your result in exactly this format and nothing else
after it:

FINAL ANSWER: <answer>
QUERIES RUN: <n>
GOTCHAS DISCOVERED: <list, or "none">
```

---

## Template B (with memory)

```
You're a data analyst at an e-commerce company. Answer this question:

{QUESTION}

This organization keeps agent learnings in its DataHub catalog. Before writing
any SQL, run:

  uv run python clients/recall.py "urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.fct_orders,PROD)" --upstream

and the same for any other table you plan to touch, e.g. dim_customers,
dim_products (substitute the table name in the urn, same
demo_warehouse.ecommerce.<table> pattern). Apply what it returns before you
write your first query.

Connect to the warehouse and compute the answer yourself with SQL. Connection
string: postgresql://demo:demo@localhost:5434/demo_warehouse

You can run queries either with:
  docker exec dhmem-demo-postgres psql -U demo -d demo_warehouse -c "<sql>"
or:
  uv run python -c "<python using psycopg2>"

HARD RULES:
- Do not read any files in this repository, except that you may read the
  terminal output of clients/recall.py itself (not its source code).
- Do not use any file under clients/, tools/, examples/, demo/, protocol/, or
  skill/, other than running clients/recall.py as instructed above.
- Do not browse DataHub (the UI, the MCP server, or any DataHub API) other
  than by running clients/recall.py as instructed above.
- Work only from what you discover by querying Postgres directly and from
  what recall.py returns.

When you're done, report your result in exactly this format and nothing else
after it:

FINAL ANSWER: <answer>
QUERIES RUN: <n>
GOTCHAS DISCOVERED: <list, or "none">
```
