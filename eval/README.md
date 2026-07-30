# With/without-memory eval: methodology

This directory holds the groundwork for a small evaluation of whether Lore's
recall mechanism (agent learnings stored in DataHub) measurably improves an
agent's answers on the demo warehouse, compared to an agent working from
scratch. This file documents the design. It does not run the eval; see
"What this directory does and doesn't contain" below for the division of
labor.

## Design

Six questions (`eval/ground_truth.json`), two conditions, one fresh Claude
Code session per (question, condition) pair, so 12 sessions total. No session
is reused across questions or across conditions: each one starts from an
empty context window and gets exactly one question.

- **No-memory condition**: Template A in `eval/prompts.md`. The agent is
  told to connect to Postgres directly and compute the answer, with a hard
  rule against reading any file in this repository or browsing DataHub.
- **With-memory condition**: Template B in `eval/prompts.md`. Identical to
  Template A, plus one instruction inserted before querying: run
  `clients/recall.py` against `fct_orders` (with `--upstream`) and against
  any other table the agent plans to touch, and apply what it returns. The
  same do-not-read-the-repo rule holds, with a narrow carve-out for
  `recall.py`'s own terminal output.

Both conditions use the same underlying model for every arm, so the only
manipulated variable is presence or absence of the recall step. The
orchestrator (not this groundwork) runs all 12 sessions and grades each
answer against `eval/ground_truth.json` using the scoring rule attached to
that question.

## What "with memory" means here

The with-memory condition uses `clients/recall.py`, the stdlib-only client
described in the root README as an independent implementation of the recall
half of the protocol, talking straight to DataHub's GraphQL endpoint. It
does not use the interactive `datahub-learnings` skill (the one driven through
the DataHub MCP server, used in the three-act `demo/`) or its automatic
per-prompt triggering.

This is deliberately a fair proxy rather than a shortcut. `recall.py` reads
the exact same structured-property learnings, written by the exact same
`retain` workflow, that the MCP-driven skill would read: the knowledge
content on the graph is identical between the two delivery paths. What
differs is only the mechanism by which an agent asks for it (one
command-line script call versus an MCP tool invocation the skill wires up
automatically). Using the stdlib client here keeps the eval's with-memory
arm reproducible without depending on the MCP server's tool-loading
behavior or the skill's auto-trigger heuristics, both of which are harder to
pin down deterministically across sessions than "run this one script and
read its output."

Before the eval sessions run, `fct_orders` (and ideally `dim_customers`,
`dim_products`, and `features_customer_ltv`) must already carry real,
retained learnings on the DataHub instance the orchestrator points at
(for example, from a prior Agent A run per `demo/README.md`, or from
`examples/learnings-fct_orders.json` if it has been written back). This
groundwork does not create those learnings and does not modify anything in
DataHub; it only prepares the questions, the ground truth, and the prompts
that assume such learnings already exist for the with-memory condition to
recall.

## Scoring rules

Recorded per-question in `eval/ground_truth.json` (`scoring` field) and
repeated here:

| Question | Scoring rule |
|---|---|
| Q1 (June revenue) | numeric, within $1 |
| Q2 (top product line + revenue) | product line name exact; dollar amount within $1 |
| Q3 (avg completed order value) | numeric, within $1 |
| Q4 (refund rate) | numeric, within 0.1 percentage points |
| Q5 (top customer + total) | customer name exact; dollar amount within $1 |
| Q6 (June cancelled-order dollars) | numeric, within $1 |

A "pass" requires every part of a multi-part answer (name and amount, or
product line and amount) to independently satisfy its rule; a numerically
correct total paired with the wrong name (or vice versa) is a fail on that
question, not a partial credit.

## Threats to validity

- **n = 6.** Six questions is enough to illustrate the mechanism, not
  enough to support a statistically significant claim about effect size.
  Treat results as directional, not as a benchmark score.
- **Constructed dataset.** The warehouse (`setup/seed_warehouse.py`) is
  seeded, deterministic, and small (500 orders, 100 customers, 40
  products), with three landmines planted specifically to be discoverable.
  Real production warehouses have more landmines, fewer of them documented
  anywhere, and less clean signal-to-noise between "genuine complexity" and
  "planted trap." Results here should not be read as an estimate of the
  effect size in a real environment.
- **Same model family across all arms.** Both conditions use the same
  underlying model, run through the same harness (Claude Code), with the
  same tool access apart from the recall step itself. This isolates the
  effect of the recall mechanism from model-choice confounds, but it also
  means the result says nothing about whether a weaker or stronger model
  changes the size of the gap.
- **No-memory agents can legitimately stumble onto the landmines anyway.**
  Nothing stops a no-memory agent from running its own sanity checks (for
  example, comparing a naive `SUM(amount)` against an order of magnitude it
  finds implausible, or noticing `features_customer_ltv` already applies
  the cents-division and completed-only filter and inferring the same
  should apply to `fct_orders`) and correcting itself without ever having
  read a learning. This is allowed under the hard rules (it does not
  require reading a repository file or browsing DataHub) and is not a
  violation of the no-memory condition. When it happens, it should be
  reported honestly in the results rather than treated as contamination:
  a no-memory arm that self-corrects via its own investigation is a
  meaningful data point about how much the recall step is actually saving,
  not a broken trial.
- **Grading is against a single ground-truth run.** `eval/ground_truth.json`
  was generated once from the deterministic seed-42 warehouse and verified
  stable across two independent runs (see "Sanity checks" below). If the
  warehouse is ever reseeded with a different seed, the ground truth and
  the ready-made $38,604,332.17 comparison in the root README would no
  longer agree, and `eval/ground_truth.py` would need to be rerun.

## Sanity checks performed on this ground truth

- Q1 recomputed independently against the live warehouse: **$38,604,332.17**,
  matching the figure already established in the root README's "The demo
  scenario is constructed" section.
- Q4's refund rate (4.8%) matches the root README's stated landmine table
  (80.8% completed / 14.4% cancelled / 4.8% refunded).
- `eval/ground_truth.py` was run twice back-to-back; the two JSON outputs
  were byte-identical, confirming the warehouse and the queries are
  deterministic and produce stable answers.

## What this directory does and doesn't contain

This groundwork produces the questions, the ground truth, the prompt
templates, and this methodology document. It does not run any agent arms:
the orchestrator (a separate process, outside this directory's scope) is
responsible for pasting `eval/prompts.md`'s templates into fresh sessions,
collecting the `FINAL ANSWER` / `QUERIES RUN` / `GOTCHAS DISCOVERED` reports,
and grading them against `eval/ground_truth.json`.

## Results

See `RESULTS.md`. Short version: both conditions were accurate on this small,
hint-rich warehouse (no memory 6/6, with memory 5/6), the with-memory arms used
62% fewer queries (16 vs 42), and the single failure was a with-memory arm
hitting a trap (duplicate customer names) that no learning covered, reported in
full because it is the most instructive result of the run.
