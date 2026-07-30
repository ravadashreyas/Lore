"""Seed the demo e-commerce warehouse with deterministic data + 3 planted landmines.

Landmines (see PLAN.md SS5):
  1. fct_orders.amount is BIGINT cents, not dollars.
  2. fct_orders.status includes 'cancelled'/'refunded' rows that must be excluded
     from revenue.
  3. dim_customers.customer_id is a half-null legacy column; the real join key
     is customer_key (always populated).

Also creates `ecommerce.features_customer_ltv`, a genuine SQL view over
fct_orders + dim_customers (the classic LTV feature set: completed-order
revenue, order count, first/last order dates per customer). It exists so the
lineage-aware recall demo beat (PLAN.md SS5 Act 3) has a real downstream
consumer of fct_orders to recall through — the view correctly applies the
cents-division and completed-only landmines itself, so recalling fct_orders'
learnings from it confirms the view is built right rather than exposing a bug.

Prerequisites: `docker compose up -d` in demo/ (postgres on localhost:5434).
Usage:         uv run setup/seed_warehouse.py
Idempotent:    drops and recreates the `ecommerce` schema on every run.
"""

import os
import random
from datetime import date, timedelta

import psycopg2

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://demo:demo@localhost:5434/demo_warehouse"
)

SEED = 42
N_CUSTOMERS = 100
N_PRODUCTS = 40
N_ORDERS = 500

SEGMENTS = ["Enterprise", "Mid-Market", "SMB"]
REGIONS = ["NA", "EMEA", "APAC", "LATAM"]
PRODUCT_LINES = ["Hardware", "Software", "Services", "Support", "Training"]

FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Drew",
    "Cameron", "Avery", "Quinn", "Reese", "Skyler", "Rowan", "Elliot", "Hayden",
]
LAST_NAMES = [
    "Chen", "Patel", "Garcia", "Kim", "Nguyen", "Smith", "Johansson", "Okafor",
    "Rossi", "Muller", "Dubois", "Silva", "Tanaka", "Kowalski", "Haddad", "Novak",
]

DDL = """
DROP SCHEMA IF EXISTS ecommerce CASCADE;
CREATE SCHEMA ecommerce;

CREATE TABLE ecommerce.dim_products (
    product_id INT PRIMARY KEY,
    product_name TEXT NOT NULL,
    product_line TEXT NOT NULL,
    unit_cost_cents BIGINT NOT NULL
);

CREATE TABLE ecommerce.dim_customers (
    customer_key INT PRIMARY KEY,
    customer_id INT,  -- legacy id, ~50% NULL; do NOT join on this
    name TEXT NOT NULL,
    segment TEXT NOT NULL,
    region TEXT NOT NULL
);

CREATE TABLE ecommerce.fct_orders (
    order_id INT PRIMARY KEY,
    customer_key INT NOT NULL REFERENCES ecommerce.dim_customers(customer_key),
    product_id INT NOT NULL REFERENCES ecommerce.dim_products(product_id),
    amount BIGINT NOT NULL,  -- CENTS, not dollars
    status TEXT NOT NULL,
    order_date DATE NOT NULL
);

-- ML feature view: per-customer LTV features derived from fct_orders +
-- dim_customers. Divides amount by 100 and filters to completed orders,
-- same as the verified_query/metric_definition learnings already on
-- fct_orders -- this view is the "someone applied the tribal knowledge
-- correctly" case, not a fresh landmine.
CREATE VIEW ecommerce.features_customer_ltv AS
SELECT
    c.customer_key,
    COUNT(o.order_id) AS completed_order_count,
    COALESCE(SUM(o.amount), 0) / 100.0 AS lifetime_revenue_dollars,
    MIN(o.order_date) AS first_order_date,
    MAX(o.order_date) AS last_order_date
FROM ecommerce.dim_customers c
LEFT JOIN ecommerce.fct_orders o
    ON o.customer_key = c.customer_key AND o.status = 'completed'
GROUP BY c.customer_key;
"""


def build_products(rng):
    rows = []
    for product_id in range(1, N_PRODUCTS + 1):
        line = PRODUCT_LINES[(product_id - 1) % len(PRODUCT_LINES)]
        name = f"{line} Product {product_id:03d}"
        unit_cost_cents = rng.randint(500_00, 20_000_00)
        rows.append((product_id, name, line, unit_cost_cents))
    return rows


def build_customers(rng):
    rows = []
    for customer_key in range(1, N_CUSTOMERS + 1):
        # Legacy customer_id survives for ~half of customers only.
        customer_id = customer_key + 1000 if rng.random() < 0.5 else None
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        segment = rng.choice(SEGMENTS)
        region = rng.choice(REGIONS)
        rows.append((customer_key, customer_id, name, segment, region))
    return rows


def random_order_date(rng):
    # Weighted toward June 2026 so "last month revenue" queries hit a real cluster.
    month = rng.choices(
        [date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1)],
        weights=[20, 55, 25],
    )[0]
    days_in_month = {5: 31, 6: 30, 7: 31}[month.month]
    return month + timedelta(days=rng.randint(0, days_in_month - 1))


def build_orders(rng):
    rows = []
    for order_id in range(1, N_ORDERS + 1):
        customer_key = rng.randint(1, N_CUSTOMERS)
        product_id = rng.randint(1, N_PRODUCTS)
        status = rng.choices(
            ["completed", "cancelled", "refunded"], weights=[80, 15, 5]
        )[0]
        # B2B-ish order sizes: $40,000-$290,000, stored as cents. Sized so June
        # completed-order revenue lands near $42M (~4.2B cents) for the demo.
        amount = rng.randint(4_000_000, 29_000_000)
        order_date = random_order_date(rng)
        rows.append((order_id, customer_key, product_id, amount, status, order_date))
    return rows


def seed():
    rng = random.Random(SEED)
    products = build_products(rng)
    customers = build_customers(rng)
    orders = build_orders(rng)

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(DDL)
            cur.executemany(
                "INSERT INTO ecommerce.dim_products VALUES (%s, %s, %s, %s)",
                products,
            )
            cur.executemany(
                "INSERT INTO ecommerce.dim_customers VALUES (%s, %s, %s, %s, %s)",
                customers,
            )
            cur.executemany(
                "INSERT INTO ecommerce.fct_orders VALUES (%s, %s, %s, %s, %s, %s)",
                orders,
            )
    finally:
        conn.close()

    print(f"Seeded {len(products)} products, {len(customers)} customers, "
          f"{len(orders)} orders into ecommerce schema.")


if __name__ == "__main__":
    seed()
