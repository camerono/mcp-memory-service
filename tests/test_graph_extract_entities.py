"""Tests for memory_graph(action='extract_entities') and memory_search's entity filter.

Both were gated on `storage.graph`, an attribute no storage class assigns, so
neither could ever run (Issue #219). The extract_entities branch additionally
called `storage.retrieve(hash)` — the semantic-search method, not a hash lookup —
and then treated the result as a dict.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_memory_service.server.handlers.graph import handle_memory_graph


@pytest.fixture
def mock_graph():
    graph = MagicMock()
    graph.store_entity_link = AsyncMock(return_value=True)
    return graph


@pytest.fixture
def mock_server():
    server = MagicMock()
    storage = MagicMock()
    memory = MagicMock()
    memory.content = "bus notes in /src/bus/consumer.py, see https://wiki.internal/bus"
    memory.metadata = {}
    memory.tags = ["message-bus"]
    memory.content_hash = "abc12345"
    storage.get_by_hash = AsyncMock(return_value=memory)
    # Deliberately absent: storage.graph. No storage class sets it (#219).
    del storage.graph
    server.storage = storage
    return server, storage, memory


@pytest.mark.asyncio
async def test_extract_entities_works_without_a_storage_graph_attribute(mock_server, mock_graph):
    """The guard must not depend on storage.graph, which nothing ever sets."""
    server, storage, _ = mock_server
    with patch("mcp_memory_service.server.handlers.graph.get_graph_storage",
               AsyncMock(return_value=mock_graph)):
        result = await handle_memory_graph(server, {"action": "extract_entities", "hash": "abc12345"})

    data = json.loads(result[0].text)
    assert data["entities_found"] > 0
    assert data["entities_stored"] == data["entities_found"]
    assert data["hash"] == "abc12345"


@pytest.mark.asyncio
async def test_extract_entities_looks_up_by_hash_not_semantic_search(mock_server, mock_graph):
    """`retrieve()` is semantic search over a query; a hash lookup is get_by_hash."""
    server, storage, _ = mock_server
    storage.retrieve = AsyncMock(side_effect=AssertionError("must not call retrieve() for a hash"))
    with patch("mcp_memory_service.server.handlers.graph.get_graph_storage",
               AsyncMock(return_value=mock_graph)):
        await handle_memory_graph(server, {"action": "extract_entities", "hash": "abc12345"})

    storage.get_by_hash.assert_awaited_once_with("abc12345")


@pytest.mark.asyncio
async def test_extract_entities_sees_memory_tags(mock_server, mock_graph):
    """Same tags-vs-metadata trap as #218, on the single-memory path."""
    server, _, _ = mock_server
    with patch("mcp_memory_service.server.handlers.graph.get_graph_storage",
               AsyncMock(return_value=mock_graph)):
        await handle_memory_graph(server, {"action": "extract_entities", "hash": "abc12345"})

    linked = {call.args[1] for call in mock_graph.store_entity_link.call_args_list}
    assert "message-bus" in linked
    assert "/src/bus/consumer.py" in linked


@pytest.mark.asyncio
async def test_extract_entities_reports_missing_memory(mock_server, mock_graph):
    server, storage, _ = mock_server
    storage.get_by_hash = AsyncMock(return_value=None)
    with patch("mcp_memory_service.server.handlers.graph.get_graph_storage",
               AsyncMock(return_value=mock_graph)):
        result = await handle_memory_graph(server, {"action": "extract_entities", "hash": "nope"})

    assert "not found" in result[0].text


@pytest.mark.asyncio
async def test_extract_entities_errors_when_backend_has_no_graph(mock_server):
    """Cloudflare has no graph storage — that must be an explicit error."""
    server, _, _ = mock_server
    with patch("mcp_memory_service.server.handlers.graph.get_graph_storage",
               AsyncMock(return_value=None)):
        result = await handle_memory_graph(server, {"action": "extract_entities", "hash": "abc12345"})

    assert "graph storage" in result[0].text.lower()


@pytest.mark.asyncio
async def test_search_entity_filter_applies_without_storage_graph():
    """memory_search's entity filter must not silently no-op (#219)."""
    from mcp_memory_service.server.handlers.memory import handle_memory_search

    server = MagicMock()
    storage = MagicMock()
    del storage.graph
    storage.search_memories = AsyncMock(return_value={
        "memories": [
            {"content": "linked", "content_hash": "keep0001", "tags": [], "created_at_iso": ""},
            {"content": "unlinked", "content_hash": "drop0001", "tags": [], "created_at_iso": ""},
        ],
        "total": 2,
    })
    server._ensure_storage_initialized = AsyncMock(return_value=storage)
    server.storage = storage

    graph = MagicMock()
    graph.find_memories_by_entity = AsyncMock(return_value=["keep0001"])

    with patch("mcp_memory_service.server.handlers.graph.get_graph_storage",
               AsyncMock(return_value=graph)):
        result = await handle_memory_search(server, {"query": "bus", "entity": "message-bus"})

    text = result[0].text
    graph.find_memories_by_entity.assert_awaited_once_with("message-bus")
    assert "drop0001" not in text
