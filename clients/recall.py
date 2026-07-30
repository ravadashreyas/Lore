#!/usr/bin/env python3
"""
recall.py -- minimal, stdlib-only recall client for the Agent Memory on DataHub
protocol (see protocol/SPEC.md). Reads io.datahub.agentMemory.learnings structured
properties for a dataset (table-level and per schemaField, SPEC SS4-SS6) and prints
them grouped by confidence, with any disputed/conflict status surfaced rather than
silently resolved (SS8). Optionally recalls entities exactly one lineage hop upstream
(SS6 scope). Read-only: this script never writes to DataHub.

Usage:
    python clients/recall.py 'urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.fct_orders,PROD)'
    python clients/recall.py '<dataset-urn>' --gms http://localhost:8080 --upstream

Talks to DataHub GMS's GraphQL endpoint (POST <gms>/api/graphql). No auth header is
sent; if your instance requires a token, add it to the Authorization header below.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

PROPERTY_URN = "urn:li:structuredProperty:io.datahub.agentMemory.learnings"

RECALL_QUERY = """
query recall($urn: String!) {
  entity(urn: $urn) {
    ... on Dataset {
      structuredProperties { ...props }
      schemaMetadata {
        fields { fieldPath schemaFieldEntity { structuredProperties { ...props } } }
      }
    }
  }
}
fragment props on StructuredProperties {
  properties {
    structuredProperty { urn }
    values { ... on StringValue { stringValue } }
  }
}
"""

LINEAGE_QUERY = """
query upstream($urn: String!) {
  searchAcrossLineage(input: {urn: $urn, direction: UPSTREAM, types: [DATASET], start: 0, count: 100}) {
    searchResults { degree entity { urn ... on Dataset { name } } }
  }
}
"""


def graphql(gms, query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        f"{gms}/api/graphql", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
    except (urllib.error.URLError, ConnectionError) as exc:
        sys.exit(f"error: could not reach DataHub GMS at {gms}: {exc}")
    if payload.get("errors"):
        sys.exit(f"error: GraphQL errors from {gms}: {payload['errors']}")
    return payload["data"]


def extract_values(structured_properties):
    """Pull this protocol's raw JSON strings out of a StructuredProperties block."""
    if not structured_properties:
        return []
    values = []
    for entry in structured_properties["properties"]:
        if entry["structuredProperty"]["urn"] == PROPERTY_URN:
            values.extend(v["stringValue"] for v in entry["values"] if "stringValue" in v)
    return values


def parse_learnings(raw_values, source_label):
    """Parse each raw value as JSON per SPEC SS4; skip and warn, never crash (SS6)."""
    learnings = []
    for raw in raw_values:
        try:
            learnings.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            print(f"warning: skipping unparseable learning on {source_label}: {exc}", file=sys.stderr)
    return learnings


def fetch_dataset_learnings(gms, urn):
    """Return (table-level learnings, {field_path: learnings}) for one dataset urn."""
    entity = graphql(gms, RECALL_QUERY, {"urn": urn}).get("entity")
    if entity is None:
        print(f"warning: {urn} not found in DataHub", file=sys.stderr)
        return [], {}
    table = parse_learnings(extract_values(entity.get("structuredProperties")), urn)
    fields = {}
    for field in (entity.get("schemaMetadata") or {}).get("fields", []):
        values = extract_values(field["schemaFieldEntity"].get("structuredProperties"))
        if values:
            fields[field["fieldPath"]] = parse_learnings(values, f"{urn}.{field['fieldPath']}")
    return table, fields


def fetch_upstream(gms, urn):
    """Entities exactly one lineage hop upstream of urn, per SPEC SS6's scope rule."""
    results = graphql(gms, LINEAGE_QUERY, {"urn": urn})["searchAcrossLineage"]["searchResults"]
    return [(r["entity"]["urn"], r["entity"].get("name", r["entity"]["urn"])) for r in results if r["degree"] == 1]


def status_flag(learning):
    status = learning.get("status", "active")
    if status == "disputed":
        return "  [DISPUTED -- a conflicting learning exists for this subject/kind]"
    if status == "conflict":
        return f"  [CONFLICT -- contradicts id {learning.get('conflicts_with', '?')}]"
    return ""


def print_learnings(label, table_learnings, field_learnings):
    total = len(table_learnings) + sum(len(v) for v in field_learnings.values())
    print(f"\n=== {label} ({total} learning{'' if total == 1 else 's'}) ===")
    if total == 0:
        print("  (none)")
        return
    tagged = [("table", l) for l in table_learnings]
    for field, learnings in field_learnings.items():
        tagged += [(field, l) for l in learnings]
    for level in ("high", "medium", "low"):
        bucket = [(subj, l) for subj, l in tagged if l.get("confidence") == level]
        if not bucket:
            continue
        print(f"\n-- confidence: {level} --")
        for subj, l in bucket:
            print(f"[{l.get('kind', '?')}] {subj}{status_flag(l)}")
            print(f"  claim:    {l.get('claim', '?')}")
            print(f"  evidence: {l.get('evidence', '?')}")
            print(f"  by {l.get('learned_by', '?')} on {l.get('learned_at', '?')}  (id {l.get('id', '?')})")


def main():
    parser = argparse.ArgumentParser(description="Recall agent-memory learnings for a DataHub dataset.")
    parser.add_argument("dataset_urn")
    parser.add_argument("--gms", default="http://localhost:8080", help="DataHub GMS base URL")
    parser.add_argument("--upstream", action="store_true", help="also recall entities one lineage hop upstream")
    args = parser.parse_args()

    table, fields = fetch_dataset_learnings(args.gms, args.dataset_urn)
    print_learnings(args.dataset_urn, table, fields)

    if args.upstream:
        upstream = fetch_upstream(args.gms, args.dataset_urn)
        if not upstream:
            print("\n(no entities found one lineage hop upstream)")
        for up_urn, up_name in upstream:
            up_table, up_fields = fetch_dataset_learnings(args.gms, up_urn)
            print_learnings(f"{up_name} (upstream of {args.dataset_urn})", up_table, up_fields)


if __name__ == "__main__":
    main()
