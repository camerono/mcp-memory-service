# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Graph visualization must not select nodes on edges it cannot draw (Issue #256).

`get_graph_visualization_data` picks the top-N memories by connection count and
then draws only edges whose *both* endpoints are in that node set. `has_entity`
rows store an entity NAME in `target_hash`, never a memory hash, so those edges
are always discarded at render time. Counting them during selection therefore
picked memories whose connections can never appear, and the view filled up with
isolated dots.
"""

import os
import tempfile

import pytest
import pytest_asyncio

from mcp_memory_service.models.memory import Memory
from mcp_memory_service.storage.graph import GraphStorage
from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage
from mcp_memory_service.utils.hashing import generate_content_hash


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test_graph_viz_entities.db")


@pytest_asyncio.fixture
async def storage(temp_db):
    store = SqliteVecMemoryStorage(temp_db)
    await store.initialize()
    yield store
    # `close` is a coroutine on BaseMixin; the older graph tests call it bare and
    # leak a RuntimeWarning per test.
    await store.close()


@pytest_asyncio.fixture
async def graph_storage(storage):
    graph = GraphStorage(storage.db_path)
    await graph._get_connection()
    yield graph


async def _store(storage, content: str) -> str:
    memory = Memory(
        content=content,
        content_hash=generate_content_hash(content),
        tags=["test"],
    )
    ok, message = await storage.store(memory)
    assert ok, f"failed to store memory: {message}"
    return memory.content_hash


@pytest.mark.asyncio
async def test_entity_only_memory_is_not_selected_as_a_node(storage, graph_storage):
    """A memory whose only links are has_entity edges must not be picked.

    Before the fix its 3 entity links counted as connections, so it was selected
    and then rendered with no edges at all.
    """
    entity_only = await _store(storage, "memory linked only to entities")
    for name in ("alpha", "beta", "gamma"):
        await graph_storage.store_entity_link(entity_only, name, "concept")

    data = await storage.get_graph_visualization_data(min_connections=1, limit=50)

    node_ids = {node["id"] for node in data["nodes"]}
    assert entity_only not in node_ids, (
        "memory with only has_entity links was selected but has no drawable edge"
    )


@pytest.mark.asyncio
async def test_memory_to_memory_links_still_select_nodes(storage, graph_storage):
    """The filter must not remove genuine memory-to-memory connections."""
    left = await _store(storage, "left side of a real association")
    right = await _store(storage, "right side of a real association")
    await graph_storage.store_association(left, right, 0.8, ["semantic"], relationship_type="related")

    data = await storage.get_graph_visualization_data(min_connections=1, limit=50)

    node_ids = {node["id"] for node in data["nodes"]}
    assert left in node_ids and right in node_ids
    assert any(
        {edge["source"], edge["target"]} == {left, right} for edge in data["edges"]
    ), "the memory-to-memory edge should be rendered"


@pytest.mark.asyncio
async def test_entity_links_do_not_inflate_the_connection_count(storage, graph_storage):
    """Connection count must reflect drawable edges only.

    This memory has one real association and four entity links. The reported
    count was 5 before the fix, of which 4 could never render.
    """
    subject = await _store(storage, "memory with one association and many entities")
    partner = await _store(storage, "the associated memory")
    await graph_storage.store_association(subject, partner, 0.9, ["semantic"], relationship_type="related")
    for name in ("delta", "epsilon", "zeta", "eta"):
        await graph_storage.store_entity_link(subject, name, "concept")

    data = await storage.get_graph_visualization_data(min_connections=1, limit=50)

    node = next(n for n in data["nodes"] if n["id"] == subject)
    assert node["connections"] == 1, (
        f"expected 1 drawable connection, got {node['connections']} "
        "(entity links counted toward the total)"
    )
