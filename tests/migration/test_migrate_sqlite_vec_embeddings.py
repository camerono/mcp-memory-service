"""Tests for scripts/migration/migrate_sqlite_vec_embeddings.py (#189).

The migration rebuilds the database from the ``memories`` table alone, so every
auxiliary table used to be lost on the way. These tests pin the carry-over of
the tables that hold data the migration cannot regenerate: graph edges and
beliefs.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "migration" / "migrate_sqlite_vec_embeddings.py"

GRAPH_SCHEMA = """
CREATE TABLE memory_graph (
    source_hash TEXT NOT NULL,
    target_hash TEXT NOT NULL,
    similarity REAL NOT NULL,
    connection_types TEXT NOT NULL,
    metadata TEXT,
    created_at REAL NOT NULL,
    PRIMARY KEY (source_hash, target_hash)
)
"""

BELIEFS_SCHEMA = """
CREATE TABLE beliefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    belief_hash TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    derived_from TEXT NOT NULL DEFAULT '[]',
    contradicted_by TEXT NOT NULL DEFAULT '[]',
    metadata TEXT DEFAULT '{}'
)
"""

MEMORIES_SCHEMA = """
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL
)
"""


@pytest.fixture(scope="module")
def migration_module():
    spec = importlib.util.spec_from_file_location("migrate_sqlite_vec_embeddings", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_db(path: Path, *, memories, graph_edges=(), beliefs=(), graph_schema=GRAPH_SCHEMA):
    conn = sqlite3.connect(path)
    conn.execute(MEMORIES_SCHEMA)
    conn.executemany(
        "INSERT INTO memories (content_hash, content) VALUES (?, ?)",
        [(h, f"content for {h}") for h in memories],
    )
    if graph_edges or graph_schema is not None:
        conn.execute(graph_schema)
        conn.executemany(
            "INSERT INTO memory_graph (source_hash, target_hash, similarity, "
            "connection_types, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            graph_edges,
        )
    if beliefs:
        conn.execute(BELIEFS_SCHEMA)
        conn.executemany(
            "INSERT INTO beliefs (belief_hash, content, confidence, status, "
            "created_at, updated_at, derived_from) VALUES (?, ?, ?, ?, ?, ?, ?)",
            beliefs,
        )
    conn.commit()
    conn.close()


def _edge(source, target, similarity=0.9):
    return (source, target, similarity, '["semantic"]', "{}", 1700000000.0)


def test_graph_edges_survive_the_migration(migration_module, tmp_path):
    """Content hashes are stable across re-embedding, so edges must carry over."""
    source = tmp_path / "old.db"
    target = tmp_path / "new.db"
    _make_db(source, memories=["aaa", "bbb"], graph_edges=[_edge("aaa", "bbb")])
    _make_db(target, memories=["aaa", "bbb"])

    result = migration_module.copy_auxiliary_tables(source, target)

    conn = sqlite3.connect(target)
    edges = conn.execute(
        "SELECT source_hash, target_hash, similarity, connection_types FROM memory_graph"
    ).fetchall()
    conn.close()

    assert edges == [("aaa", "bbb", 0.9, '["semantic"]')]
    assert result["memory_graph"]["copied"] == 1
    assert result["memory_graph"]["skipped"] == 0


def test_edges_pointing_at_a_lost_memory_are_dropped_and_counted(migration_module, tmp_path):
    """A memory that failed to restore leaves a dangling endpoint; report it."""
    source = tmp_path / "old.db"
    target = tmp_path / "new.db"
    _make_db(
        source,
        memories=["aaa", "bbb"],
        graph_edges=[_edge("aaa", "bbb"), _edge("aaa", "ccc")],
    )
    _make_db(target, memories=["aaa", "bbb"])

    result = migration_module.copy_auxiliary_tables(source, target)

    conn = sqlite3.connect(target)
    edges = conn.execute("SELECT source_hash, target_hash FROM memory_graph").fetchall()
    conn.close()

    assert edges == [("aaa", "bbb")]
    assert result["memory_graph"]["copied"] == 1
    assert result["memory_graph"]["skipped"] == 1


def test_beliefs_survive_the_migration(migration_module, tmp_path):
    source = tmp_path / "old.db"
    target = tmp_path / "new.db"
    belief = ("h1", "user prefers dark mode", 0.8, "active", "2026-01-01", "2026-01-02", '["aaa"]')
    _make_db(source, memories=["aaa"], beliefs=[belief])
    _make_db(target, memories=["aaa"])
    conn = sqlite3.connect(target)
    conn.execute(BELIEFS_SCHEMA)
    conn.commit()
    conn.close()

    result = migration_module.copy_auxiliary_tables(source, target)

    conn = sqlite3.connect(target)
    rows = conn.execute("SELECT belief_hash, content, confidence, derived_from FROM beliefs").fetchall()
    conn.close()

    assert rows == [("h1", "user prefers dark mode", 0.8, '["aaa"]')]
    assert result["beliefs"]["copied"] == 1


def test_column_added_after_the_source_db_was_created(migration_module, tmp_path):
    """Target has relationship_type (migration 009), source predates it."""
    source = tmp_path / "old.db"
    target = tmp_path / "new.db"
    _make_db(source, memories=["aaa", "bbb"], graph_edges=[_edge("aaa", "bbb")])
    _make_db(
        target,
        memories=["aaa", "bbb"],
        graph_schema=GRAPH_SCHEMA.replace(
            "PRIMARY KEY (source_hash, target_hash)",
            "relationship_type TEXT,\n    PRIMARY KEY (source_hash, target_hash)",
        ),
    )

    result = migration_module.copy_auxiliary_tables(source, target)

    conn = sqlite3.connect(target)
    rows = conn.execute(
        "SELECT source_hash, target_hash, relationship_type FROM memory_graph"
    ).fetchall()
    conn.close()

    assert rows == [("aaa", "bbb", None)]
    assert result["memory_graph"]["copied"] == 1


def test_column_dropped_in_the_target_is_ignored(migration_module, tmp_path):
    """A source column the new schema no longer has must not abort the copy."""
    source = tmp_path / "old.db"
    target = tmp_path / "new.db"
    _make_db(
        source,
        memories=["aaa", "bbb"],
        graph_edges=[_edge("aaa", "bbb")],
        graph_schema=GRAPH_SCHEMA.replace(
            "PRIMARY KEY (source_hash, target_hash)",
            "legacy_score REAL,\n    PRIMARY KEY (source_hash, target_hash)",
        ),
    )
    _make_db(target, memories=["aaa", "bbb"])

    result = migration_module.copy_auxiliary_tables(source, target)

    conn = sqlite3.connect(target)
    rows = conn.execute("SELECT source_hash, target_hash FROM memory_graph").fetchall()
    conn.close()

    assert rows == [("aaa", "bbb")]
    assert result["memory_graph"]["copied"] == 1


def test_table_missing_in_source_is_skipped(migration_module, tmp_path):
    """An old database predating the graph table must migrate without error."""
    source = tmp_path / "old.db"
    target = tmp_path / "new.db"
    _make_db(source, memories=["aaa"], graph_schema=None)
    _make_db(target, memories=["aaa"])

    result = migration_module.copy_auxiliary_tables(source, target)

    assert "memory_graph" not in result
    assert result == {}


def test_rerunning_the_copy_is_idempotent(migration_module, tmp_path):
    source = tmp_path / "old.db"
    target = tmp_path / "new.db"
    _make_db(source, memories=["aaa", "bbb"], graph_edges=[_edge("aaa", "bbb")])
    _make_db(target, memories=["aaa", "bbb"])

    migration_module.copy_auxiliary_tables(source, target)
    migration_module.copy_auxiliary_tables(source, target)

    conn = sqlite3.connect(target)
    count = conn.execute("SELECT COUNT(*) FROM memory_graph").fetchone()[0]
    conn.close()

    assert count == 1
