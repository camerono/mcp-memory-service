"""Regression test for #150: has_entity edges must survive orphan pruning."""

import pytest
import sqlite3
import time
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_storage_with_graph(tmp_path):
    """Create a real SQLite DB with memory_graph table and mock storage."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE memories (
            content_hash TEXT PRIMARY KEY,
            content TEXT,
            created_at REAL,
            deleted_at REAL DEFAULT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE memory_graph (
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

    # Insert a live memory
    conn.execute(
        "INSERT INTO memories (content_hash, content, created_at) VALUES (?, ?, ?)",
        ("live_hash_1", "some content", time.time()),
    )

    # Insert a has_entity edge (live memory → entity name)
    conn.execute(
        "INSERT INTO memory_graph VALUES (?, ?, 1.0, '[\"entity\"]', '{}', ?, 'has_entity')",
        ("live_hash_1", "PostgreSQL", time.time()),
    )

    # Insert a shares_entity edge (live memory ↔ live memory)
    conn.execute(
        "INSERT INTO memories (content_hash, content, created_at) VALUES (?, ?, ?)",
        ("live_hash_2", "other content", time.time()),
    )
    conn.execute(
        "INSERT INTO memory_graph VALUES (?, ?, 0.9, '[\"entity\"]', '{}', ?, 'shares_entity')",
        ("live_hash_1", "live_hash_2", time.time()),
    )

    # Insert an orphaned edge (source doesn't exist in memories)
    conn.execute(
        "INSERT INTO memory_graph VALUES (?, ?, 0.8, '[\"semantic\"]', '{}', ?, 'related')",
        ("orphan_hash", "live_hash_1", time.time()),
    )

    conn.commit()

    storage = MagicMock()
    storage.conn = conn
    return storage, conn


@pytest.mark.asyncio
async def test_prune_preserves_has_entity_edges(mock_storage_with_graph):
    """has_entity edges with live source must survive pruning (#150)."""
    from mcp_memory_service.consolidation.consolidator import DreamInspiredConsolidator

    storage, conn = mock_storage_with_graph

    consolidator = DreamInspiredConsolidator.__new__(DreamInspiredConsolidator)
    consolidator.storage = storage
    consolidator.logger = MagicMock()

    pruned = await consolidator._prune_orphaned_graph_edges()

    # The orphaned 'related' edge should be pruned
    assert pruned >= 1

    # has_entity edge (live_hash_1 → "PostgreSQL") must survive
    cursor = conn.execute(
        "SELECT COUNT(*) FROM memory_graph WHERE relationship_type = 'has_entity'"
    )
    assert cursor.fetchone()[0] == 1, "has_entity edge was incorrectly pruned"

    # shares_entity edge (both sides live) must survive
    cursor = conn.execute(
        "SELECT COUNT(*) FROM memory_graph WHERE relationship_type = 'shares_entity'"
    )
    assert cursor.fetchone()[0] == 1, "shares_entity edge was incorrectly pruned"


@pytest.mark.asyncio
async def test_prune_removes_has_entity_with_orphaned_source(mock_storage_with_graph):
    """has_entity edges with deleted source SHOULD be pruned (#150)."""
    from mcp_memory_service.consolidation.consolidator import DreamInspiredConsolidator

    storage, conn = mock_storage_with_graph

    # Add a has_entity edge with orphaned source (memory doesn't exist)
    conn.execute(
        "INSERT INTO memory_graph VALUES (?, ?, 1.0, '[\"entity\"]', '{}', ?, 'has_entity')",
        ("deleted_memory_hash", "MIR", time.time()),
    )
    conn.commit()

    consolidator = DreamInspiredConsolidator.__new__(DreamInspiredConsolidator)
    consolidator.storage = storage
    consolidator.logger = MagicMock()

    await consolidator._prune_orphaned_graph_edges()

    # has_entity with orphaned source should be pruned
    cursor = conn.execute(
        "SELECT COUNT(*) FROM memory_graph WHERE source_hash = 'deleted_memory_hash'"
    )
    assert cursor.fetchone()[0] == 0, "has_entity with orphaned source should be pruned"

    # has_entity with live source should survive
    cursor = conn.execute(
        "SELECT COUNT(*) FROM memory_graph WHERE source_hash = 'live_hash_1' AND relationship_type = 'has_entity'"
    )
    assert cursor.fetchone()[0] == 1, "has_entity with live source should survive"
