#!/usr/bin/env python3
"""
lint_learnings.py -- stdlib-only governance linter for the Agent Memory on DataHub
protocol (protocol/SPEC.md SS4, SS7-SS9). Sweeps every postgres-platform dataset plus
their schemaFields (same catalog query as hooks/enforce_recall.py), reads every
io.datahub.agentMemory.learnings value, and checks each against spec-checkable rules:
required fields, kind/confidence/status enums, id/date shape, length caps, the
conflict-record contract (SS8), duplicate ids, and two heuristics (evidence
concreteness, secret/PII shape) -- flagged below as heuristics, not proofs. Lints the
memory itself, not the data it describes.

Usage:
    python tools/lint_learnings.py [--gms http://localhost:8080]

Talks to DataHub GMS's GraphQL endpoint (POST <gms>/api/graphql), same approach as
clients/recall.py. No auth header sent; add one if your instance requires it.

Exit 0 with one [PASS] line if the catalog is clean. Exit 1 with one
[FAIL] <entity> <learning-id-or-index>: <rule> - <detail> line per violation plus a
summary count. Suitable for CI.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

PROPERTY_URN = "urn:li:structuredProperty:io.datahub.agentMemory.learnings"
REQUIRED_FIELDS = ["id", "kind", "subject_urn", "claim", "evidence", "confidence", "learned_by", "learned_at"]
ENUMS = {  # field -> (valid values, rule name)
    "kind": ({"semantic_gotcha", "verified_query", "join_path", "caveat", "metric_definition"}, "invalid-kind"),
    "confidence": ({"high", "medium", "low"}, "invalid-confidence"),
    "status": ({"active", "disputed", "conflict"}, "invalid-status"),
}
LENGTH_CAPS = {"claim": ("claim-too-long", 280), "evidence": ("evidence-too-long", 500)}

UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SQL_KEYWORD_RE = re.compile(r"\b(select|count|sum|ratio)\b", re.I)  # (j) heuristic, not a proof of concreteness
SECRET_PATTERNS = [  # (n) shape heuristics, not a real secret scanner
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "looks like an email address"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "looks like an AWS access key (AKIA...)"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "long hex run (32+ chars), could be a hash/key"),
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), "long base64-like run (40+ chars), could be a token"),
    (re.compile(r"\b(password|token|secret)\b\s*[:=]\s*\S+", re.I), "'password'/'token'/'secret' followed by a value"),
]

CATALOG_QUERY = """
query LoreLintCatalog($query: String!) {
  search(input: {type: DATASET, query: $query, start: 0, count: 1000,
    filters: [{field: "platform", values: ["urn:li:dataPlatform:postgres"]}]}) {
    searchResults { entity { urn ... on Dataset { name } } }
  }
}
"""
ENTITY_QUERY = """
query LoreLintEntity($urn: String!) {
  entity(urn: $urn) {
    ... on Dataset {
      structuredProperties { ...props }
      schemaMetadata { fields { fieldPath schemaFieldEntity { structuredProperties { ...props } } } }
    }
  }
}
fragment props on StructuredProperties {
  properties { structuredProperty { urn } values { ... on StringValue { stringValue } } }
}
"""

def graphql(gms, query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(f"{gms}/api/graphql", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
    except (urllib.error.URLError, ConnectionError) as exc:
        sys.exit(f"error: could not reach DataHub GMS at {gms}: {exc}")
    if payload.get("errors"):
        sys.exit(f"error: GraphQL errors from {gms}: {payload['errors']}")
    return payload["data"]

def fetch_catalog(gms):
    """[(name, urn), ...] for every dataset on platform postgres."""
    results = (graphql(gms, CATALOG_QUERY, {"query": "*"}).get("search") or {}).get("searchResults") or []
    return [(r["entity"]["name"], r["entity"]["urn"]) for r in results if r.get("entity", {}).get("name")]

def extract_values(structured_properties):
    if not structured_properties:
        return []
    values = []
    for entry in structured_properties["properties"]:
        if entry["structuredProperty"]["urn"] == PROPERTY_URN:
            values.extend(v["stringValue"] for v in entry["values"] if "stringValue" in v)
    return values

def fetch_entity_scopes(gms, name, urn):
    """[(label, [raw_json_string, ...]), ...]: dataset scope + every non-empty schemaField scope."""
    entity = graphql(gms, ENTITY_QUERY, {"urn": urn}).get("entity")
    if entity is None:
        print(f"warning: {urn} not found in DataHub, skipping", file=sys.stderr)
        return []
    scopes = [(name, extract_values(entity.get("structuredProperties")))]
    for field in (entity.get("schemaMetadata") or {}).get("fields", []):
        values = extract_values(field["schemaFieldEntity"].get("structuredProperties"))
        if values:
            scopes.append((f"{name}.{field['fieldPath']}", values))
    return scopes

def validate_record(raw):
    """Return (violations, parsed-dict-or-None). violations: [(rule, detail), ...]."""
    violations = [("secret-or-pii", msg) for pattern, msg in SECRET_PATTERNS if pattern.search(raw)]

    try:
        rec = json.loads(raw)
    except json.JSONDecodeError as exc:
        return violations + [("invalid-json", str(exc))], None
    if not isinstance(rec, dict):
        return violations + [("invalid-json", "value is not a JSON object")], None

    for field in REQUIRED_FIELDS:
        if not rec.get(field):
            violations.append(("missing-field", f"required field '{field}' missing or empty"))
    for field, (valid, rule) in ENUMS.items():
        value = rec.get(field)
        if value and value not in valid:
            violations.append((rule, f"'{value}' not in {sorted(valid)}"))
    for field, (rule, cap) in LENGTH_CAPS.items():
        value = rec.get(field)
        if isinstance(value, str) and len(value) > cap:
            violations.append((rule, f"{len(value)} chars > {cap}"))

    rec_id = rec.get("id")
    if rec_id and not UUID4_RE.match(str(rec_id)):
        violations.append(("invalid-id-format", f"id '{rec_id}' is not UUID4-shaped"))
    learned_at = rec.get("learned_at")
    if learned_at and not DATE_RE.match(str(learned_at)):
        violations.append(("invalid-date-format", f"learned_at '{learned_at}' is not YYYY-MM-DD"))

    evidence = rec.get("evidence")
    if isinstance(evidence, str) and not re.search(r"\d", evidence) and not SQL_KEYWORD_RE.search(evidence):
        violations.append(("evidence-not-concrete", "no digit or SQL keyword (SELECT/count/sum/ratio) found "
                                                      "(heuristic, not a proof of concreteness)"))

    status = rec.get("status") or "active"
    has_conflicts_with = bool(rec.get("conflicts_with"))
    if status == "conflict" and not has_conflicts_with:
        violations.append(("conflicts-with-missing", "status=conflict requires conflicts_with"))
    if has_conflicts_with and status != "conflict":
        violations.append(("conflicts-with-unexpected", f"conflicts_with present but status='{status}'"))

    return violations, rec

def lint(gms):
    """Returns (violations, total_learnings, dataset_count)."""
    catalog = fetch_catalog(gms)
    violations, total_learnings = [], 0
    id_locations = {}  # id -> [entity_label, ...], across the whole catalog
    for name, urn in catalog:
        for label, raw_values in fetch_entity_scopes(gms, name, urn):
            scope_records, entries = {}, []  # id -> record (for l); (ref, violations, record)
            for idx, raw in enumerate(raw_values, start=1):
                total_learnings += 1
                v, rec = validate_record(raw)
                rec_id = rec.get("id") if rec else None
                ref = rec_id if (rec_id and UUID4_RE.match(str(rec_id))) else f"#{idx}"
                entries.append((ref, v, rec))
                if rec and isinstance(rec_id, str) and rec_id:
                    scope_records[rec_id] = rec
                    id_locations.setdefault(rec_id, []).append(label)

            for ref, v, rec in entries:
                target_id = rec.get("conflicts_with") if rec else None
                if target_id:
                    target = scope_records.get(target_id)
                    if target is None:
                        v.append(("conflicts-with-orphan", f"target id '{target_id}' not found among learnings on {label}"))
                    elif (target.get("status") or "active") != "disputed":
                        v.append(("conflicts-with-not-disputed",
                                  f"target id '{target_id}' has status '{target.get('status') or 'active'}', expected 'disputed'"))
                violations.extend((label, ref, rule, detail) for rule, detail in v)

    for rec_id, labels in id_locations.items():
        if len(labels) > 1:
            violations.append((labels[0], rec_id, "duplicate-id", f"id reused {len(labels)}x across: {', '.join(labels)}"))

    return violations, total_learnings, len(catalog)

def main():
    parser = argparse.ArgumentParser(description="Lint io.datahub.agentMemory.learnings values against protocol/SPEC.md.")
    parser.add_argument("--gms", default="http://localhost:8080", help="DataHub GMS base URL")
    args = parser.parse_args()

    violations, total_learnings, dataset_count = lint(args.gms)
    for label, ref, rule, detail in violations:
        print(f"[FAIL] {label} {ref}: {rule} - {detail}")

    if violations:
        print(f"\n[FAIL] {len(violations)} violation(s) across {total_learnings} learning(s) in {dataset_count} dataset(s).")
        sys.exit(1)
    print(f"[PASS] 0 violations across {total_learnings} learning(s) in {dataset_count} dataset(s).")
    sys.exit(0)

if __name__ == "__main__":
    main()
