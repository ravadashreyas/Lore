"""Compute ground-truth answers for the with/without-memory eval's 6 questions.

Connects directly to the demo Postgres warehouse (postgresql://demo:demo@
localhost:5434/demo_warehouse, schema ecommerce, deterministic seed 42) and runs
explicitly correct SQL for each question: `status = 'completed'` wherever
"revenue" is the subject, and `amount / 100.0` to convert the BIGINT-cents
`fct_orders.amount` column to dollars. See the root README's "The demo scenario
is constructed" section and `setup/seed_warehouse.py` for the three planted
landmines (cents-not-dollars, cancelled/refunded rows inflating naive revenue,
and the half-null `dim_customers.customer_id` vs. the real join key
`customer_key`) that this script's SQL deliberately avoids.

'Revenue' throughout means completed-order revenue only. Q4's refund rate is
refunded_count / total_count over ALL orders (not revenue-based, so no status
filter is applied to the denominator or numerator: refunded is itself a status
value). Q6 asks about revenue *lost* to cancellation, so it deliberately sums
`status = 'cancelled'` orders using the same cents-to-dollars treatment as
completed revenue -- see that question's SQL comment for the precise
definition, since "lost revenue" is not itself a GAAP-recognized revenue figure.

Usage:
    uv run python eval/ground_truth.py > eval/ground_truth.json

Prints a single JSON object of the form:
    {"q1": {"answer": ..., "sql": "..."}, "q2": {...}, ...}

Deterministic: the warehouse is seeded with a fixed random seed (42), so this
script's output is stable across runs as long as the warehouse hasn't been
reseeded with a different seed or schema.
"""

import json
import os

import psycopg2

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://demo:demo@localhost:5434/demo_warehouse"
)

QUERIES = {
    "q1": {
        "question": "What was our total revenue in June 2026, in dollars?",
        "sql": """
            SELECT ROUND(SUM(amount) / 100.0, 2) AS revenue_dollars
            FROM ecommerce.fct_orders
            WHERE status = 'completed'
              AND order_date >= DATE '2026-06-01'
              AND order_date <  DATE '2026-07-01'
        """,
        "scoring": "numeric, within $1",
    },
    "q2": {
        "question": "Which product line generated the most revenue in June 2026, and how much?",
        "sql": """
            SELECT p.product_line, ROUND(SUM(o.amount) / 100.0, 2) AS revenue_dollars
            FROM ecommerce.fct_orders o
            JOIN ecommerce.dim_products p ON p.product_id = o.product_id
            WHERE o.status = 'completed'
              AND o.order_date >= DATE '2026-06-01'
              AND o.order_date <  DATE '2026-07-01'
            GROUP BY p.product_line
            ORDER BY revenue_dollars DESC
            LIMIT 1
        """,
        "scoring": "product line name exact; dollar amount within $1",
    },
    "q3": {
        "question": "What is the average value of a completed order across all time, in dollars?",
        "sql": """
            SELECT ROUND(AVG(amount) / 100.0, 2) AS avg_completed_order_dollars
            FROM ecommerce.fct_orders
            WHERE status = 'completed'
        """,
        "scoring": "numeric, within $1",
    },
    "q4": {
        "question": "What percentage of all orders (by count) were refunded?",
        "sql": """
            SELECT ROUND(
                100.0 * COUNT(*) FILTER (WHERE status = 'refunded') / COUNT(*),
                2
            ) AS pct_refunded
            FROM ecommerce.fct_orders
        """,
        "scoring": "numeric, within 0.1 percentage points",
    },
    "q5": {
        "question": "Which customer has the highest lifetime revenue, and what is their name and total?",
        "sql": """
            SELECT c.name, ROUND(SUM(o.amount) / 100.0, 2) AS lifetime_revenue_dollars
            FROM ecommerce.fct_orders o
            JOIN ecommerce.dim_customers c ON c.customer_key = o.customer_key
            WHERE o.status = 'completed'
            GROUP BY c.customer_key, c.name
            ORDER BY lifetime_revenue_dollars DESC
            LIMIT 1
        """,
        "scoring": "customer name exact; dollar amount within $1",
    },
    "q6": {
        # Definition: the dollar-equivalent value of orders placed in June 2026
        # that ended up with status = 'cancelled', using the identical
        # cents-to-dollars treatment (amount / 100.0) applied to completed
        # revenue elsewhere in this file. This is NOT a GAAP "lost revenue"
        # figure and is never summed into completed revenue (Q1); it answers
        # "how much would June revenue have been higher by, had these specific
        # orders completed instead of being cancelled" under the simplifying
        # assumption that a cancelled order's `amount` is what it would have
        # billed at.
        "question": "How much June 2026 revenue was lost to cancelled orders, in dollars?",
        "sql": """
            SELECT ROUND(SUM(amount) / 100.0, 2) AS cancelled_revenue_equivalent_dollars
            FROM ecommerce.fct_orders
            WHERE status = 'cancelled'
              AND order_date >= DATE '2026-06-01'
              AND order_date <  DATE '2026-07-01'
        """,
        "scoring": "numeric, within $1",
    },
}


def run():
    conn = psycopg2.connect(DATABASE_URL)
    results = {}
    try:
        with conn, conn.cursor() as cur:
            for qid, spec in QUERIES.items():
                cur.execute(spec["sql"])
                row = cur.fetchone()
                if len(row) == 1:
                    answer = float(row[0]) if row[0] is not None else None
                else:
                    # (label, amount) pairs: q2, q5
                    label, amount = row
                    answer = {"label": label, "amount": float(amount)}
                results[qid] = {
                    "question": spec["question"],
                    "answer": answer,
                    "sql": " ".join(spec["sql"].split()),
                    "scoring": spec["scoring"],
                }
    finally:
        conn.close()
    return results


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
