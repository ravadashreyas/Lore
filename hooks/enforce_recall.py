#!/usr/bin/env python3
"""
enforce_recall.py -- Claude Code PreToolUse hook that makes recall (protocol/SPEC.md
SS6) infrastructure instead of etiquette, closing the "No enforced recall" gap admitted
in SPEC.md SS9. Wired via .claude/settings.json to run before every Bash tool call.

On a Bash command, looks for cataloged DataHub table names appearing as whole words in
the command. If a matched table (or an entity one lineage hop upstream, SS6's scope)
has learnings not yet surfaced this session, blocks once (exit 2, learnings on stderr
-- Claude Code feeds this back to the model as the block reason), marks it seen, and
lets the retry through (exit 0). Fails open on any error: a broken guardrail must never
break the user's shell.

Usage (invoked by Claude Code; hook JSON arrives on stdin):
    uv run python hooks/enforce_recall.py
    python hooks/enforce_recall.py
"""

import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.request

PROPERTY_URN = "urn:li:structuredProperty:io.datahub.agentMemory.learnings"
HTTP_TIMEOUT_SECONDS = 5
CATALOG_TTL_SECONDS = 300

CATALOG_QUERY = """
query LoreCatalog($query: String!) {
  search(input: {type: DATASET, query: $query, start: 0, count: 1000,
    filters: [{field: "platform", values: ["urn:li:dataPlatform:postgres"]}]}) {
    searchResults { entity { urn ... on Dataset { name } } }
  }
}
"""

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
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        f"{gms}/api/graphql", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read())
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload["data"]


def get_tmp_base():
    base = os.environ.get("TMP") or os.environ.get("TEMP") or tempfile.gettempdir()
    path = os.path.join(base, "lore_hook")
    os.makedirs(path, exist_ok=True)
    return path


def fetch_catalog(gms):
    """{table_name: dataset_urn} for every dataset on platform postgres."""
    data = graphql(gms, CATALOG_QUERY, {"query": "*"})
    results = ((data.get("search") or {}).get("searchResults")) or []
    tables = {}
    for r in results:
        entity = r.get("entity") or {}
        name, urn = entity.get("name"), entity.get("urn")
        if name and urn:
            tables[name] = urn
    return tables


def get_catalog(gms):
    """Cached catalog lookup (TTL CATALOG_TTL_SECONDS) so the hook stays fast. Cache
    file is keyed by gms so pointing LORE_GMS_URL elsewhere can't serve a stale hit."""
    gms_key = hashlib.md5(gms.encode("utf-8")).hexdigest()[:8]
    cache_path = os.path.join(get_tmp_base(), f"catalog_cache_{gms_key}.json")
    now = time.time()
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if now - cached.get("fetched_at", 0) < CATALOG_TTL_SECONDS:
                return cached.get("tables", {})
        except (OSError, ValueError):  # fail-open: a corrupt cache just triggers a refetch below
            pass

    tables = fetch_catalog(gms)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": now, "tables": tables}, f)
    except OSError:  # fail-open: caching is an optimization, not a requirement
        pass
    return tables


def find_matched_tables(command, catalog):
    """Cataloged table names appearing as whole words in command, case-insensitive,
    in first-seen order. Word-boundary regex so `orders` never matches `fct_orders`."""
    names = sorted(catalog.keys(), key=len, reverse=True)
    if not names:
        return []
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)
    lower_to_name = {n.lower(): n for n in names}
    matched, seen = [], set()
    for m in pattern.finditer(command):
        canonical = lower_to_name[m.group(0).lower()]
        if canonical not in seen:
            seen.add(canonical)
            matched.append(canonical)
    return matched


def extract_values(structured_properties):
    if not structured_properties:
        return []
    values = []
    for entry in structured_properties["properties"]:
        if entry["structuredProperty"]["urn"] == PROPERTY_URN:
            values.extend(v["stringValue"] for v in entry["values"] if "stringValue" in v)
    return values


def parse_learnings(raw_values):
    """Parse each raw value as JSON per SPEC SS4; skip malformed entries silently --
    a warning here would print to stderr even on a non-blocking (exit 0) run."""
    learnings = []
    for raw in raw_values:
        try:
            learnings.append(json.loads(raw))
        except json.JSONDecodeError:  # fail-open: a malformed entry must not break recall of the rest
            pass
    return learnings


def fetch_dataset_learnings(gms, urn):
    """(table-level learnings, {field_path: learnings}) for one dataset urn."""
    entity = graphql(gms, RECALL_QUERY, {"urn": urn}).get("entity")
    if entity is None:
        return [], {}
    table = parse_learnings(extract_values(entity.get("structuredProperties")))
    fields = {}
    for field in (entity.get("schemaMetadata") or {}).get("fields", []):
        values = extract_values(field["schemaFieldEntity"].get("structuredProperties"))
        if values:
            fields[field["fieldPath"]] = parse_learnings(values)
    return table, fields


def fetch_upstream(gms, urn):
    """Entities exactly one lineage hop upstream of urn (SPEC SS6 scope)."""
    results = graphql(gms, LINEAGE_QUERY, {"urn": urn})["searchAcrossLineage"]["searchResults"]
    return [(r["entity"]["urn"], r["entity"].get("name", r["entity"]["urn"])) for r in results if r["degree"] == 1]


def gather_sources(gms, catalog, table):
    """[(label, table_learnings, field_learnings), ...] for `table` itself plus every
    entity one lineage hop upstream of it."""
    urn = catalog[table]
    table_learnings, field_learnings = fetch_dataset_learnings(gms, urn)
    sources = [(table, table_learnings, field_learnings)]
    for up_urn, up_name in fetch_upstream(gms, urn):
        up_table, up_fields = fetch_dataset_learnings(gms, up_urn)
        sources.append((f"{up_name} (upstream of {table})", up_table, up_fields))
    return sources


def count_learnings(sources):
    return sum(len(tl) + sum(len(v) for v in fl.values()) for _, tl, fl in sources)


def status_flag(learning):
    status = learning.get("status", "active")
    if status == "disputed":
        return "  [DISPUTED - a conflicting learning exists for this subject/kind]"
    if status == "conflict":
        return f"  [CONFLICT - contradicts id {learning.get('conflicts_with', '?')}]"
    return ""


def format_message(blocks):
    """blocks: [(table, total, sources), ...] -> concise ASCII stderr block reason."""
    lines = []
    for table, total, sources in blocks:
        plural = "" if total == 1 else "s"
        lines.append(f"[lore] Recall enforced: {table} has {total} learning{plural} in DataHub you have not yet seen:")
        for label, table_learnings, field_learnings in sources:
            tagged = [("table", l) for l in table_learnings]
            for field, learnings in field_learnings.items():
                tagged += [(field, l) for l in learnings]
            if not tagged:
                continue
            lines.append(f"  -- {label} --")
            for subj, l in tagged:
                lines.append(f"  [{l.get('kind', '?')}] {subj} (confidence: {l.get('confidence', '?')}){status_flag(l)}")
                lines.append(f"    claim: {l.get('claim', '?')}")
        lines.append("")
    lines.append(
        "Re-run your command - it will be allowed now. Apply high-confidence learnings "
        "directly; verify medium ones cheaply (SPEC section 6)."
    )
    return "\n".join(lines) + "\n"


def marker_path(marker_dir, session_id, table):
    safe_session = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)
    safe_table = re.sub(r"[^A-Za-z0-9_-]", "_", table)
    return os.path.join(marker_dir, f"{safe_session}__{safe_table}.marker")


def run():
    payload = json.loads(sys.stdin.read())
    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    command = (payload.get("tool_input") or {}).get("command")
    session_id = payload.get("session_id")
    if not command or not session_id:
        sys.exit(0)

    gms = os.environ.get("LORE_GMS_URL", "http://localhost:8080")
    catalog = get_catalog(gms)
    matched = find_matched_tables(command, catalog)
    if not matched:
        sys.exit(0)

    marker_dir = os.path.join(get_tmp_base(), "markers")
    os.makedirs(marker_dir, exist_ok=True)

    blocks, newly_marked = [], []
    for table in matched:
        if os.path.exists(marker_path(marker_dir, session_id, table)):
            continue
        sources = gather_sources(gms, catalog, table)
        total = count_learnings(sources)
        if total > 0:
            blocks.append((table, total, sources))
            newly_marked.append(table)

    if not blocks:
        sys.exit(0)

    for table in newly_marked:
        try:
            with open(marker_path(marker_dir, session_id, table), "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except OSError:  # fail-open: an unwritable marker just means we re-check DataHub next time
            pass

    sys.stderr.write(format_message(blocks))
    sys.exit(2)


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception:  # fail-open: any unexpected failure must never block the user's shell
        sys.exit(0)
