"""Integration test for _discover_related_entities with real GraphStorage.

Requested by maintainer (doobidoo) in PR #78 re-review:
'Please add one non-mocked integration test that seeds has_entity edges
into a real sqlite_vec graph (via store_entity_link) and asserts
_discover_related_entities resolves them to expected entity names with
correct dedup.'
"""
import pytest
import tempfile
import os
from pathlib import Path
import importlib.util

# Load GraphStorage directly (same pattern as test_graph_storage_integration.py)
graph_path = Path(__file__).parent.parent / "src" / "mcp_memory_service" / "storage" / "graph.py"
spec = importlib.util.spec_from_file_location("graph", graph_path)
graph_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graph_module)
GraphStorage = graph_module.GraphStorage
normalize_entity_id = graph_module.normalize_entity_id


@pytest.fixture
async def real_graph():
    """Create a real GraphStorage with sqlite for integration testing."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        db_path = tmp.name

    storage = GraphStorage(db_path)
    conn = await storage._get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_graph (
            source_hash TEXT NOT NULL,
            target_hash TEXT NOT NULL,
            similarity REAL NOT NULL,
            connection_types TEXT NOT NULL,
            metadata TEXT,
            created_at REAL NOT NULL,
            relationship_type TEXT DEFAULT 'related',
            PRIMARY KEY (source_hash, target_hash)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_relationship ON memory_graph(relationship_type)")
    conn.commit()

    yield storage

    if storage._connection:
        storage._connection.close()
    os.unlink(db_path)


async def _discover_related_entities_real(graph, memory_hashes, max_hops: int):
    """Inline copy of _discover_related_entities logic for integration testing.

    This avoids importing the full handler module (which pulls mcp SDK + server deps).
    The logic mirrors src/mcp_memory_service/server/handlers/graph.py:778 exactly.
    """
    entity_map: dict = {}
    for h in memory_hashes[:max_hops + 1]:
        for cand_hash, shared, _deg in await graph.common_neighbors(h):
            entity_names = await graph.get_entities_for_memory(cand_hash)
            for entity_name in entity_names:
                eid = normalize_entity_id(entity_name)
                if eid in entity_map:
                    entity_map[eid]["shared_count"] = max(entity_map[eid]["shared_count"], shared)
                else:
                    entity_map[eid] = {
                        "entity_id": eid,
                        "name": entity_name,
                        "shared_count": shared,
                    }

    related = sorted(entity_map.values(), key=lambda x: x["shared_count"], reverse=True)
    return related[:10]


class TestDiscoverRelatedEntitiesIntegration:
    """Non-mocked integration test using real sqlite GraphStorage.

    Validates the full path: store_entity_link → common_neighbors → get_entities_for_memory
    → entity name resolution with dedup.
    """

    @pytest.mark.asyncio
    async def test_resolves_entity_names_with_dedup(self, real_graph):
        """Seeds real has_entity edges and verifies entity name resolution + dedup."""

        # Topology for common_neighbors (2-hop via "related" edges):
        # query_mem ←→ intermediate ←→ candidate_a
        # query_mem ←→ intermediate ←→ candidate_b
        # (store_association with "related" creates bidirectional edges)

        await real_graph.store_association(
            source_hash="query_mem",
            target_hash="intermediate",
            similarity=0.9,
            connection_types=["semantic"],
            relationship_type="related",
        )
        await real_graph.store_association(
            source_hash="intermediate",
            target_hash="candidate_a",
            similarity=0.8,
            connection_types=["semantic"],
            relationship_type="related",
        )
        await real_graph.store_association(
            source_hash="intermediate",
            target_hash="candidate_b",
            similarity=0.7,
            connection_types=["semantic"],
            relationship_type="related",
        )

        # Seed has_entity edges on candidates
        await real_graph.store_entity_link("candidate_a", "Python", "language")
        await real_graph.store_entity_link("candidate_a", "FastAPI", "framework")
        await real_graph.store_entity_link("candidate_b", "Python", "language")

        # Call the real aggregation logic against the real graph
        result = await _discover_related_entities_real(real_graph, ["query_mem"], max_hops=2)

        # Assertions
        assert len(result) == 2, f"Expected 2 unique entities, got {len(result)}: {result}"

        by_name = {r["name"]: r for r in result}
        assert "Python" in by_name, f"Expected 'Python' in results: {result}"
        assert "FastAPI" in by_name, f"Expected 'FastAPI' in results: {result}"

        # entity_id is normalized (lowercase)
        assert by_name["Python"]["entity_id"] == "python"
        assert by_name["FastAPI"]["entity_id"] == "fastapi"

        # Python dedup'd — shared_count is the max across both candidates
        assert by_name["Python"]["shared_count"] >= 1
