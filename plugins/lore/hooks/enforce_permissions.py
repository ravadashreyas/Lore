#!/usr/bin/env python3
"""
enforce_permissions.py -- Claude Code PreToolUse hook that grants an agent per-table
and per-column data permissions (read / update / write) over the demo warehouse, while
leaving the Lore learnings layer (the "sticky notes": structured-property recall and
retain) always accessible. Wired via .claude/settings.json to run before every Bash
tool call, alongside enforce_recall.py.

Permissions come from a JSON file the operator edits to toggle what an agent may do:
`lore-permissions.json` in the project root (or the path in LORE_PERMS_FILE). No file
means the feature is off and every command is allowed. See hooks/README.md for the
schema and hooks/permissions.example.json for a starting point.

Unlike enforce_recall.py's block-once pattern, a denial here is deterministic: the
same command is blocked every time until the config changes. Metadata-layer commands
(anything touching the agent-memory structured property or the GraphQL API) are never
blocked, so an agent locked out of the data can still recall and retain learnings.

Usage (invoked by Claude Code; hook JSON arrives on stdin):
    uv run python hooks/enforce_permissions.py
    python hooks/enforce_permissions.py
"""

import json
import os
import re
import sys

from enforce_recall import find_matched_tables, get_catalog

OPS = ("read", "update", "write")

# The always-open metadata layer: any command aimed at DataHub's GraphQL API or the
# agent-memory property is recall/retain traffic, not data access. This is a guardrail,
# not a security boundary (same stance as enforce_recall.py's honest limits).
METADATA_MARKERS = ("agentMemory", "structuredProperty", "/api/graphql")

UPDATE_VERBS = re.compile(r"\bupdate\b", re.IGNORECASE)
WRITE_VERBS = re.compile(
    r"\b(insert|delete|drop|truncate|alter|create|copy|merge|grant|revoke)\b", re.IGNORECASE
)


def load_config(cwd):
    """Parsed config dict, or None when the file doesn't exist (feature off).
    Raises ValueError on a malformed file -- an access-control file the operator
    wrote deliberately fails CLOSED, never silently open."""
    path = os.environ.get("LORE_PERMS_FILE") or os.path.join(cwd, "lore-permissions.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    for allow in [config.get("default", [])] + [
        entry.get("allow", []) for entry in config.get("tables", {}).values()
    ]:
        bad = [op for op in allow if op not in OPS]
        if bad:
            raise ValueError(f"unknown operation(s) {bad}; allowed: {list(OPS)}")
    return config


def required_ops(command):
    """Which of read/update/write the command needs, judged by SQL verbs appearing as
    whole words. No verbs at all means the table is only being read."""
    required = set()
    if UPDATE_VERBS.search(command):
        required.add("update")
    if WRITE_VERBS.search(command):
        required.add("write")
    return required or {"read"}


def check_command(command, config, catalog):
    """[(table, column-or-None, allowed, missing), ...] for every violated grant."""
    tables = config.get("tables", {})
    default_allow = set(config.get("default", OPS))
    known = {name: None for name in set(catalog) | set(tables)}
    required = required_ops(command)

    violations = []
    for table in find_matched_tables(command, known):
        entry = tables.get(table, {})
        allow = set(entry.get("allow", default_allow))
        missing = required - allow
        if missing:
            violations.append((table, None, allow, missing))
        for column, column_allow in entry.get("columns", {}).items():
            if re.search(r"\b" + re.escape(column) + r"\b", command, re.IGNORECASE):
                missing = required - set(column_allow)
                if missing:
                    violations.append((table, column, set(column_allow), missing))
    return violations


def format_denial(violations):
    lines = []
    for table, column, allow, missing in violations:
        subject = f"{table}.{column}" if column else table
        granted = ", ".join(sorted(allow)) or "nothing"
        lines.append(
            f"[lore] Permission denied by lore-permissions.json: {subject} grants "
            f"[{granted}] but this command needs [{', '.join(sorted(missing))}]."
        )
    lines.append(
        "The learnings layer is always open regardless of data permissions: you can "
        "still recall and retain (MCP structured-property tools, or the agent-memory "
        "GraphQL path). If you learned something before being blocked, retain it."
    )
    return "\n".join(lines) + "\n"


def run():
    payload = json.loads(sys.stdin.read())
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    command = (payload.get("tool_input") or {}).get("command")
    if not command:
        sys.exit(0)

    try:
        config = load_config(payload.get("cwd") or os.getcwd())
    except ValueError as e:
        sys.stderr.write(
            f"[lore] lore-permissions.json is malformed ({e}). Permissions fail closed: "
            "fix the file or remove it to disable enforcement.\n"
        )
        sys.exit(2)
    if config is None:
        sys.exit(0)

    if any(marker in command for marker in METADATA_MARKERS):
        sys.exit(0)

    # Config-listed tables are enforced even when DataHub is unreachable; the catalog
    # only extends the "default" grant to cataloged tables the config doesn't name.
    try:
        catalog = get_catalog(os.environ.get("LORE_GMS_URL", "http://localhost:8080"))
    except Exception:
        catalog = {}

    violations = check_command(command, config, catalog)
    if violations:
        sys.stderr.write(format_denial(violations))
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception:  # fail-open: any unexpected failure must never block the user's shell
        sys.exit(0)
