"""One-command environment doctor for hackathon judges running the Lore demo.

Runs 8 checks in dependency order (DataHub GMS/UI health, demo Postgres, the
4 ingested demo datasets, the lineage edge, the learnings structured
property, learnings JSON validity, MCP server resolution). Prints one
[PASS]/[FAIL]/[WARN] line per check with the exact fix on failure. Check 8 is
a [WARN]: it confirms mcp-server-datahub resolves via uvx, not that a Claude
Code session is wired to it -- that needs the repo opened in Claude Code.

Prerequisites: repo deps installed (`uv sync`).

Example: uv run python setup/doctor.py
         uv run python setup/doctor.py --gms http://localhost:9999  # exercise a failure path
"""

import argparse
import json
import subprocess
import urllib.request

import psycopg2

DATABASE_URL = "postgresql://demo:demo@localhost:5434/demo_warehouse"
PROPERTY_URN = "urn:li:structuredProperty:io.datahub.agentMemory.learnings"
TABLES = ("fct_orders", "dim_customers", "dim_products", "features_customer_ltv")

QUICKSTART_FIX = (
    "run `PYTHONIOENCODING=utf-8 datahub docker quickstart` (README.md Quickstart step 1); "
    "verify with `docker ps`, not the CLI's own exit code."
)


def dataset_urn(table: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.{table},PROD)"


def http_ok(url: str) -> tuple[bool, str]:
    """GET url. True + status text if it returns HTTP 200; False + the error otherwise."""
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except OSError as exc:
        return False, str(exc)


def graphql(gms_url: str, query: str, variables: dict) -> tuple[dict | None, str | None]:
    """POST a GraphQL query. Returns (response_data, None) or (None, error_message)."""
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        f"{gms_url}/api/graphql", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)


def check_http(url: str, label: str):
    """Shared by the GMS-health and UI-reachable checks -- both are just a 200 check."""
    ok, detail = http_ok(url)
    if not ok:
        return False, f"{label} not reachable at {url} ({detail}). Fix: {QUICKSTART_FIX}"
    return True, f"{label} is reachable"


def check_postgres():
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
    except psycopg2.OperationalError as exc:
        fix = "`docker compose -f demo/docker-compose.yml up -d` (README.md Quickstart step 2)"
        return False, f"Demo Postgres not reachable at {DATABASE_URL} ({exc}). Fix: {fix}."
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ecommerce.fct_orders")
            n_orders = cur.fetchone()[0]
            cur.execute("SELECT to_regclass('ecommerce.features_customer_ltv')")
            has_view = cur.fetchone()[0] is not None
    finally:
        conn.close()
    if n_orders != 500 or not has_view:
        fix = "`uv run python setup/seed_warehouse.py` (README.md Quickstart step 3)"
        view_state = "present" if has_view else "missing"
        return False, (
            f"Postgres reachable but not seeded (fct_orders has {n_orders} rows, expected 500; "
            f"features_customer_ltv view {view_state}). Fix: {fix}."
        )
    return True, "Demo Postgres reachable and seeded (fct_orders: 500 rows, view present)"


def check_datasets_exist(gms_url: str):
    query = "query GetEntity($urn: String!) { entity(urn: $urn) { urn type } }"
    missing = []
    for table in TABLES:
        data, error = graphql(gms_url, query, {"urn": dataset_urn(table)})
        if error:
            return False, f"GraphQL query failed for {table}: {error}"
        if (data.get("data") or {}).get("entity") is None:
            missing.append(table)
    if missing:
        fix = (
            'PYTHONIOENCODING=utf-8 uvx --from "acryl-datahub[postgres]==1.6.0.16" datahub '
            "ingest -c setup/ingest_postgres.yml (README.md Quickstart step 4)"
        )
        return False, f"Missing datasets in DataHub: {', '.join(missing)}. Fix: {fix}"
    return True, "All 4 demo datasets present in DataHub"


def check_lineage(gms_url: str):
    query = (
        "query GetLineage($urn: String!) { searchAcrossLineage(input: {urn: $urn, "
        "direction: UPSTREAM, types: [DATASET], start: 0, count: 10}) { "
        "searchResults { entity { urn } degree } } }"
    )
    data, error = graphql(gms_url, query, {"urn": dataset_urn("features_customer_ltv")})
    if error:
        return False, f"Lineage query failed: {error}"
    results = ((data.get("data") or {}).get("searchAcrossLineage") or {}).get("searchResults", [])
    fct_orders_urn = dataset_urn("fct_orders")
    hop = next((r for r in results if r["entity"]["urn"] == fct_orders_urn), None)
    if hop is None or hop["degree"] != 1:
        found = [r["entity"]["urn"] for r in results]
        fix = (
            "re-run `uv run python setup/seed_warehouse.py` then the ingestion command in "
            "setup/NOTES-datahub-quickstart.md, section Ingestion"
        )
        return False, (
            f"fct_orders is not exactly 1 hop upstream of features_customer_ltv "
            f"(found: {found}). Fix: {fix}."
        )
    return True, "features_customer_ltv -> fct_orders lineage edge present (1 hop upstream)"


def check_structured_property(gms_url: str):
    query = (
        "query GetProp($urn: String!) { "
        "structuredProperty(urn: $urn) { urn definition { cardinality } } }"
    )
    data, error = graphql(gms_url, query, {"urn": PROPERTY_URN})
    if error:
        return False, f"structuredProperty query failed: {error}"
    if (data.get("data") or {}).get("structuredProperty") is None:
        fix = "`uv run python setup/register_properties.py` (README.md Quickstart step 5)"
        return False, f"io.datahub.agentMemory.learnings is not registered. Fix: run {fix}."
    return True, "io.datahub.agentMemory.learnings structured property is registered"


def check_learnings_parseable(gms_url: str):
    """State-agnostic: any number of learnings (incl. zero, incl. concurrently
    changing) is fine as long as whatever is present right now parses as JSON."""
    query = (
        "query GetEntity($urn: String!) { entity(urn: $urn) { ... on Dataset { "
        "structuredProperties { properties { structuredProperty { urn } "
        "values { ... on StringValue { stringValue } } } } } } }"
    )
    total, bad_tables = 0, []
    for table in TABLES:
        data, error = graphql(gms_url, query, {"urn": dataset_urn(table)})
        if error:
            return False, f"Learnings readback failed for {table}: {error}"
        entity = (data.get("data") or {}).get("entity") or {}
        for prop in (entity.get("structuredProperties") or {}).get("properties", []):
            if prop["structuredProperty"]["urn"] != PROPERTY_URN:
                continue
            for value in prop["values"]:
                total += 1
                try:
                    json.loads(value["stringValue"])
                except json.JSONDecodeError:
                    bad_tables.append(table)
    if bad_tables:
        fix = "inspect the DataHub UI, or run `uv run python demo/reset_demo.py` to start over"
        return False, f"Unparseable learning JSON on: {', '.join(bad_tables)}. Fix: {fix}."
    if total == 0:
        return True, "no learnings yet -- run the demo"
    return True, f"{total} learning(s) present across the 4 demo datasets, all valid JSON"


def check_mcp_server():
    try:
        result = subprocess.run(
            ["uvx", "mcp-server-datahub@latest", "--help"],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        fix = "install uv (https://docs.astral.sh/uv/) -- see Windows gotchas in NOTES-datahub-quickstart.md"
        return False, f"uvx not found on PATH. Fix: {fix}."
    except subprocess.TimeoutExpired:
        return False, "`uvx mcp-server-datahub@latest --help` timed out after 60s."
    if result.returncode != 0:
        return False, (
            f"`uvx mcp-server-datahub@latest --help` exited {result.returncode}: "
            f"{result.stderr.strip()[-300:]}"
        )
    return True, (
        "mcp-server-datahub resolves via uvx. This does NOT confirm the Claude Code MCP "
        "session is configured -- open the repo root in Claude Code for that (.mcp.json "
        "loads at session start only; fully quit and reopen after editing it)."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Lore demo environment is set up.")
    parser.add_argument("--gms", default="http://localhost:8080", help="DataHub GMS base URL")
    parser.add_argument("--ui", default="http://localhost:9002", help="DataHub UI base URL")
    args = parser.parse_args()

    checks = [
        ("DataHub GMS healthy", lambda: check_http(f"{args.gms}/health", "DataHub GMS"), True),
        ("DataHub UI reachable", lambda: check_http(args.ui, "DataHub UI"), True),
        ("Demo Postgres reachable + seeded", check_postgres, True),
        ("4 demo datasets in DataHub", lambda: check_datasets_exist(args.gms), True),
        ("Lineage edge (ltv -> fct_orders)", lambda: check_lineage(args.gms), True),
        ("Structured property registered", lambda: check_structured_property(args.gms), True),
        ("Learnings parse as valid JSON", lambda: check_learnings_parseable(args.gms), True),
        ("MCP server package resolves", check_mcp_server, False),
    ]

    critical_failed = False
    for name, check, critical in checks:
        passed, message = check()
        marker = "PASS" if passed else ("FAIL" if critical else "WARN")
        critical_failed = critical_failed or (critical and not passed)
        print(f"[{marker}] {name}: {message}")

    print()
    if critical_failed:
        print("Environment has issues -- see [FAIL] lines above for the exact fix.")
    else:
        print("All critical checks passed. Environment is ready for the demo.")
    return 1 if critical_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
