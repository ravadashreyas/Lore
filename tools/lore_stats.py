#!/usr/bin/env python3
"""
lore_stats.py -- stdlib-only knowledge-accumulation report for the Agent Memory on
DataHub protocol (protocol/SPEC.md). Sweeps every postgres-platform dataset in the
catalog plus their schemaFields (same catalog approach as tools/lint_learnings.py and
hooks/enforce_recall.py), parses every io.datahub.agentMemory.learnings value, and
prints totals, breakdowns, open conflicts, and two operational signals: a
--stale-days review queue and a per-entity noise warning.

SPEC.md SS9 states the protocol has "no automated expiry or TTL" by design: deleting
a learning silently is worse than flagging it. --stale-days is explicitly a reporting
signal, not a retention policy; it never deletes or disputes anything.

Usage:
    python tools/lore_stats.py
    python tools/lore_stats.py --gms http://localhost:8080 --stale-days 60

Talks to DataHub GMS's GraphQL endpoint (POST <gms>/api/graphql), same approach as
clients/recall.py. No auth header is sent; add one if your instance requires it.

Always exits 0: this is a report, not a gate. Use tools/lint_learnings.py for a
pass/fail check suitable for CI.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

PROPERTY_URN = "urn:li:structuredProperty:io.datahub.agentMemory.learnings"
NOISE_THRESHOLD = 20

CATALOG_QUERY = """
query LoreStatsCatalog($query: String!) {
  search(input: {type: DATASET, query: $query, start: 0, count: 1000,
    filters: [{field: "platform", values: ["urn:li:dataPlatform:postgres"]}]}) {
    searchResults { entity { urn ... on Dataset { name } } }
  }
}
"""

ENTITY_QUERY = """
query LoreStatsEntity($urn: String!) {
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

def fetch_catalog(gms):
    data = graphql(gms, CATALOG_QUERY, {"query": "*"})
    results = ((data.get("search") or {}).get("searchResults")) or []
    return [(r["entity"]["name"], r["entity"]["urn"]) for r in results if r.get("entity", {}).get("name")]

def extract_values(structured_properties):
    if not structured_properties:
        return []
    values = []
    for entry in structured_properties["properties"]:
        if entry["structuredProperty"]["urn"] == PROPERTY_URN:
            values.extend(v["stringValue"] for v in entry["values"] if "stringValue" in v)
    return values

def fetch_all_learnings(gms):
    """[(entity_label, parsed_record), ...] across every postgres dataset + schemaField.
    Skips values that fail to parse, with a warning, same as clients/recall.py SS6."""
    catalog = fetch_catalog(gms)
    out = []
    for name, urn in catalog:
        entity = graphql(gms, ENTITY_QUERY, {"urn": urn}).get("entity")
        if entity is None:
            print(f"warning: {urn} not found in DataHub, skipping", file=sys.stderr)
            continue
        scopes = [(name, extract_values(entity.get("structuredProperties")))]
        for field in (entity.get("schemaMetadata") or {}).get("fields", []):
            values = extract_values(field["schemaFieldEntity"].get("structuredProperties"))
            if values:
                scopes.append((f"{name}.{field['fieldPath']}", values))
        for label, raw_values in scopes:
            for raw in raw_values:
                try:
                    out.append((label, json.loads(raw)))
                except json.JSONDecodeError as exc:
                    print(f"warning: skipping unparseable learning on {label}: {exc}", file=sys.stderr)
    return len(catalog), out

def count_by(records, key):
    counts = {}
    for _, rec in records:
        counts[rec.get(key, "?")] = counts.get(rec.get(key, "?"), 0) + 1
    return counts

def print_counts(title, counts):
    print(f"\n{title}:")
    if not counts:
        print("  (none)")
        return
    for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        print(f"  {k}: {v}")

def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None

def main():
    parser = argparse.ArgumentParser(
        description="Report on io.datahub.agentMemory.learnings accumulation across the catalog."
    )
    parser.add_argument("--gms", default="http://localhost:8080", help="DataHub GMS base URL")
    parser.add_argument(
        "--stale-days", type=int, default=90,
        help="flag learnings older than N days as review candidates (reporting only, no TTL enforced)",
    )
    args = parser.parse_args()

    dataset_count, records = fetch_all_learnings(args.gms)
    total = len(records)

    print(f"=== Lore stats: {total} learning(s) across {dataset_count} postgres dataset(s) ===")

    entity_counts = count_by([(label, {"_": label}) for label, _ in records], "_")

    print_counts("By kind", count_by(records, "kind"))
    print_counts("By confidence", count_by(records, "confidence"))
    print_counts("By entity", entity_counts)

    conflicts = [(label, rec) for label, rec in records if rec.get("status") == "conflict"]
    print(f"\nOpen conflicts (status=conflict, per SPEC SS8 these stay open until a human resolves them): {len(conflicts)}")
    for label, rec in conflicts:
        print(f"  {label}: id {rec.get('id', '?')} contradicts {rec.get('conflicts_with', '?')}")

    dated = [(label, rec, d) for label, rec in records if (d := parse_date(rec.get("learned_at"))) is not None]
    if dated:
        label, rec, newest = max(dated, key=lambda t: t[2])
        print(f"\nNewest learned_at: {newest.isoformat()} ({label}, id {rec.get('id', '?')})")
    else:
        print("\nNewest learned_at: (no dated learnings)")

    print(
        f"\nStale review candidates (--stale-days {args.stale_days}; reporting only -- "
        f"SPEC SS9: no TTL by design, staleness is surfaced, never auto-deleted):"
    )
    today = date.today()
    stale = sorted(
        ((label, rec, d) for label, rec, d in dated if (today - d).days > args.stale_days),
        key=lambda t: t[2],
    )
    if not stale:
        print("  (none)")
    for label, rec, d in stale:
        age = (today - d).days
        print(f"  {label}: id {rec.get('id', '?')} learned_at {d.isoformat()} ({age}d old) - {rec.get('claim', '?')}")

    print(f"\nNoise warnings (entities with more than {NOISE_THRESHOLD} learnings):")
    noisy = {k: v for k, v in entity_counts.items() if v > NOISE_THRESHOLD}
    if not noisy:
        print("  (none)")
    for label, n in sorted(noisy.items(), key=lambda kv: -kv[1]):
        print(f"  {label}: {n} learnings")

    sys.exit(0)

if __name__ == "__main__":
    main()
