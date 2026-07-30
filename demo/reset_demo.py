"""Reset the demo scenario to a clean slate so Agent A / Agent B / Agent C can be
re-run for another video take.

Removes every value of the `io.datahub.agentMemory.learnings` structured property
from the 4 demo dataset urns (fct_orders, dim_customers, dim_products,
features_customer_ltv) and from every schemaField urn under them, and strips the
`<!-- agent-memory:begin/end -->` block back out of each dataset's editable
description. Idempotent: running it against an already-clean instance reports
nothing to remove and exits 0.

Prerequisites: DataHub GMS reachable (default http://localhost:8080, override with
DATAHUB_GMS_URL) with the 4 demo datasets already ingested (setup/ingest_postgres.yml).

Example invocation:
    uv run python demo/reset_demo.py
"""

import os
import sys

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig
from datahub.metadata.schema_classes import (
    EditableDatasetPropertiesClass,
    StructuredPropertiesClass,
)

PROPERTY_URN = "urn:li:structuredProperty:io.datahub.agentMemory.learnings"
DATASET_URNS = [
    f"urn:li:dataset:(urn:li:dataPlatform:postgres,demo_warehouse.ecommerce.{table},PROD)"
    for table in ("fct_orders", "dim_customers", "dim_products", "features_customer_ltv")
]
BEGIN_MARKER = "<!-- agent-memory:begin -->"
END_MARKER = "<!-- agent-memory:end -->"

ENTITY_QUERY = """
query GetEntity($urn: String!) {
  entity(urn: $urn) {
    urn
    ... on Dataset {
      schemaMetadata { fields { fieldPath } }
      editableProperties { description }
      structuredProperties { properties { structuredProperty { urn } values { ... on StringValue { stringValue } } } }
    }
    ... on SchemaFieldEntity {
      structuredProperties { properties { structuredProperty { urn } values { ... on StringValue { stringValue } } } }
    }
  }
}
"""


def make_graph() -> DataHubGraph:
    server = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
    token = os.environ.get("DATAHUB_GMS_TOKEN")
    return DataHubGraph(DatahubClientConfig(server=server, token=token))


def field_urns_for(graph: DataHubGraph, dataset_urn: str) -> list[str]:
    """All schemaField urns for a dataset, discovered from live schema metadata
    (not hardcoded) so the sweep covers every column, not just the planted one."""
    data = graph.execute_graphql(ENTITY_QUERY, {"urn": dataset_urn})
    entity = data.get("entity")
    if entity is None:
        raise RuntimeError(f"Dataset not found in DataHub: {dataset_urn}")
    schema = entity.get("schemaMetadata")
    fields = schema["fields"] if schema else []
    return [f"urn:li:schemaField:({dataset_urn},{f['fieldPath']})" for f in fields]


def learnings_count(entity: dict) -> int:
    for prop in (entity.get("structuredProperties") or {}).get("properties", []):
        if prop["structuredProperty"]["urn"] == PROPERTY_URN:
            return len(prop["values"])
    return 0


def clear_structured_property(graph: DataHubGraph, entity_urn: str) -> None:
    graph.emit_mcp(
        MetadataChangeProposalWrapper(
            entityUrn=entity_urn,
            aspect=StructuredPropertiesClass(properties=[{"propertyUrn": PROPERTY_URN, "values": []}]),
        )
    )


def strip_doc_block(description: str | None) -> str | None:
    if not description or BEGIN_MARKER not in description or END_MARKER not in description:
        return description
    pre = description.split(BEGIN_MARKER)[0]
    post = description.split(END_MARKER)[1]
    return (pre.rstrip() + post).strip() or None


def reset_dataset(graph: DataHubGraph, dataset_urn: str) -> None:
    data = graph.execute_graphql(ENTITY_QUERY, {"urn": dataset_urn})
    entity = data.get("entity")
    if entity is None:
        raise RuntimeError(f"Dataset not found in DataHub: {dataset_urn}")

    count = learnings_count(entity)
    if count:
        clear_structured_property(graph, dataset_urn)
        print(f"  removed {count} learning(s) from {dataset_urn}")
    else:
        print(f"  no learnings on {dataset_urn}, nothing to remove")

    description = (entity.get("editableProperties") or {}).get("description")
    stripped = strip_doc_block(description)
    if stripped != description:
        graph.emit_mcp(
            MetadataChangeProposalWrapper(
                entityUrn=dataset_urn,
                aspect=EditableDatasetPropertiesClass(description=stripped or ""),
            )
        )
        print(f"  stripped agent-memory doc block from {dataset_urn} description")
    else:
        print(f"  no doc block present on {dataset_urn} description, nothing to strip")

    for field_urn in field_urns_for(graph, dataset_urn):
        field_data = graph.execute_graphql(ENTITY_QUERY, {"urn": field_urn})
        field_entity = field_data.get("entity") or {}
        field_count = learnings_count(field_entity)
        if field_count:
            clear_structured_property(graph, field_urn)
            print(f"  removed {field_count} learning(s) from {field_urn}")


def main() -> None:
    graph = make_graph()
    print(f"Resetting demo scenario against {graph.config.server}")
    try:
        for dataset_urn in DATASET_URNS:
            print(f"{dataset_urn}:")
            reset_dataset(graph, dataset_urn)
    except Exception as exc:
        print(f"Reset failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
    print("Reset complete.")


if __name__ == "__main__":
    main()
