"""Register the agent-memory structured property definition on DataHub.

Creates `io.datahub.agentMemory.learnings` (protocol/SPEC.md §5.1): a MULTIPLE-
cardinality string property, applicable to `dataset` and `schemaField` entities,
where each value is one JSON-serialized learning record (SPEC.md §4).

Idempotent: emitting the same StructuredPropertyDefinition aspect twice just
overwrites it with identical content, so safe to re-run after any change here.

Prerequisites: DataHub GMS reachable (default http://localhost:8080, override
with DATAHUB_GMS_URL); optional DATAHUB_GMS_TOKEN if the instance requires auth
(local OSS quickstart does not).

Example invocation:
    uv run python setup/register_properties.py
"""

import os

from datahub.api.entities.structuredproperties.structuredproperties import (
    StructuredProperties,
)
from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig

PROPERTY_QUALIFIED_NAME = "io.datahub.agentMemory.learnings"


def make_graph() -> DataHubGraph:
    server = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
    token = os.environ.get("DATAHUB_GMS_TOKEN")
    return DataHubGraph(DatahubClientConfig(server=server, token=token))


def main() -> None:
    graph = make_graph()

    learnings_property = StructuredProperties(
        id=PROPERTY_QUALIFIED_NAME,
        qualified_name=PROPERTY_QUALIFIED_NAME,
        type="string",
        cardinality="MULTIPLE",
        entity_types=["dataset", "schemaField"],
        display_name="Agent memory learnings",
        description=(
            "One JSON-serialized agent-memory learning record (see "
            "protocol/SPEC.md §4) per list value. Written and read by the "
            "recall/retain skill; not hand-edited."
        ),
    )

    for mcp in learnings_property.generate_mcps():
        graph.emit_mcp(mcp)

    print(f"Registered structured property: {learnings_property.urn}")

    fetched = StructuredProperties.from_datahub(graph, learnings_property.urn)
    assert fetched.cardinality == "MULTIPLE", (
        f"expected MULTIPLE cardinality, got {fetched.cardinality}"
    )
    assert set(fetched.entity_types or []) == {
        "urn:li:entityType:datahub.dataset",
        "urn:li:entityType:datahub.schemaField",
    }, f"unexpected entity_types: {fetched.entity_types}"
    print("Verified: cardinality=MULTIPLE, entityTypes=[dataset, schemaField]")


if __name__ == "__main__":
    main()
