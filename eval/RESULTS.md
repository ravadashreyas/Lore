# Eval results

Run 2026-07-29. Methodology, prompts, and ground truth: `eval/README.md`,
`eval/prompts.md`, `eval/ground_truth.json`. Twelve arms total: the six questions
from `ground_truth.json`, each answered by two independent, fresh agent sessions
(same model family, Claude Sonnet), one per condition. Condition A had no memory.
Condition B was instructed to run `clients/recall.py` against the tables it planned
to touch, and to apply what it returned, before writing SQL. Neither condition was
permitted to read repository files (the repo documents the landmines). Scoring was
done against `ground_truth.json`, computed before any arm ran: numeric answers
within $1 (0.1 points for the percentage question), names exact, both parts
required on two-part questions.

## Headline numbers

| | Condition A (no memory) | Condition B (with memory) |
|---|---|---|
| Correct answers | **6 / 6** | **5 / 6** |
| Total queries across all questions | **42** | **16** |
| Mean queries per question | 7.0 | 2.7 |
| Median queries | 7.5 | 2.0 |
| Cents landmine handled correctly | 6/6 (re-derived from scratch each time) | 6/6 (recalled) |
| Completed-only revenue definition handled | 6/6 (re-derived or confirmed via the LTV view) | 6/6 (recalled) |

With memory, agents reached their answers with **62% fewer queries** (16 vs 42)
while every piece of recalled knowledge they applied was correct. Without memory,
agents got there too, but paid the re-derivation cost on every single question:
the cents conversion was independently re-discovered six separate times.

## Per-arm detail

| Q | Ground truth | A answer | A queries | B answer | B queries |
|---|---|---|---|---|---|
| q1 June revenue | $38,604,332.17 | correct | 8 | correct | 1 |
| q2 Top product line | Training, $8,854,377.83 | correct | 8 | correct | 4 |
| q3 Avg completed order | $169,506.80 | correct | 6 | correct | 6 |
| q4 Refund rate | 4.8% | correct | 4 | correct | 3 |
| q5 Top customer | Skyler Rossi (key 7), $1,770,250.80 | correct | 9 | **wrong: $2,612,852.62** | 1 |
| q6 June cancelled revenue | $6,214,716.94 | correct | 7 | correct | 1 |

## The q5 failure, in full

The with-memory arm on q5 answered "Skyler Rossi, $2,612,852.62". The name is
right; the number is the sum of **two distinct customers who share that name**
(customer_key 7: $1,770,250.80, customer_key 10: $842,601.82; verified directly
against the warehouse, which contains a dozen duplicated names). The arm grouped
by customer name instead of by customer_key and merged the homonyms. The
no-memory arm on the same question ran 9 queries, noticed the duplicate names
itself, disambiguated by customer_key, and answered correctly.

This is the most instructive result in the run, and it cuts against the
with-memory condition, so it is reported in full. What happened: the recalled
learnings covered the cents and completed-only traps, the arm applied them,
answered in one query, and never profiled the data further. The trap it hit
(non-unique names) was one no agent had ever retained a learning about. Memory
reduced exploration, which is exactly its value on q1 and q6 (one query,
correct) and exactly its risk on q5. Institutional memory only protects against
what the institution has learned.

The protocol's own answer to this failure mode is the retain loop: the q5
no-memory arm's discovery ("customer names are not unique; disambiguate by
customer_key") is precisely the kind of `join_path`/`caveat` learning the retain
workflow exists to capture, after which no future agent, with or without
curiosity, hits it again. The failure is an argument for more memory, not less;
what it honestly tempers is any claim that recalled knowledge substitutes for
data profiling on questions the memory does not cover.

## Threats to validity, observed in practice

- **The landmines were more discoverable than intended.** Condition A agents
  found the cents trap 6/6 times, usually via two channels we built ourselves:
  the `unit_cost_cents` column name in `dim_products` (a naming hint that leaks
  the unit convention), and the `features_customer_ltv` view, whose SQL
  definition (readable in Postgres) encodes both the division by 100 and the
  completed-only filter. Real warehouses rarely annotate their traps this well.
  The correct reading of condition A's 6/6 is "a careful frontier model, given
  unlimited queries against a small, self-consistent warehouse with in-schema
  hints, re-derives tribal knowledge reliably"; the cost of that reliability is
  the 2.6x query multiplier, and it does not generalize to messier schemas,
  larger tables (where profiling queries are expensive), or weaker models.
- **n = 6 questions, 1 run per arm.** No variance estimates. Single model family.
- **Small data.** 500-row tables make exhaustive profiling cheap; at production
  scale, condition A's 7-query median becomes materially expensive and slow.
- **Condition B's delivery mechanism** was the stdlib recall client, not the
  interactive MCP skill; the knowledge content is identical, but skill-driven
  sessions could behave differently.

## What this supports, and what it does not

Supported by this run: recalled learnings were applied correctly every time they
were relevant (12/12 applications across the B arms); memory cut query cost by
62%; and on the two questions whose phrasing depends on an organizational metric
definition (q1, q6), memory took agents from ambiguity to a single correct query.

Not supported: any claim that memory improves raw accuracy for a strong,
careful agent on a small, hint-rich warehouse (A went 6/6), or that recall
removes the need to profile data on questions outside the memory's coverage
(q5's failure is the counterexample, kept here on purpose).
