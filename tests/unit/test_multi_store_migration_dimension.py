"""Regression tests for issue #134: multi-store vec0 migration must preserve
embeddings on databases whose vec0 dimension differs from the 384 default, and
must recover from a migration interrupted after the destructive DROP.
"""
import os
import sqlite3
import struct

import pytest

os.environ.setdefault('MCP_MEMORY_STORAGE_BACKEND', 'sqlite_vec')

import sqlite_vec
from sqlite_vec import serialize_float32

from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

DIM = 1024


def _make_embedding(seed: int) -> bytes:
    """Serialize a deterministic DIM-length float32 vector to sqlite-vec format."""
    vec = [((seed * 31 + i) % 97) / 97.0 for i in range(DIM)]
    return serialize_float32(vec)


def _raw_vec_connection(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _create_memories_table(conn):
    """Create the `memories` table with the shape initialize() expects."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            memory_type TEXT,
            metadata TEXT,
            created_at REAL,
            updated_at REAL,
            created_at_iso TEXT,
            updated_at_iso TEXT,
            deleted_at REAL DEFAULT NULL
        )
    ''')
    for i in range(3):
        conn.execute(
            "INSERT INTO memories (content_hash, content) VALUES (?, ?)",
            (f"hash_{i}", f"legacy content {i}"),
        )


def _build_legacy_1024_db(db_path: str):
    """Create a pre-#134 legacy DB: a vec0 `memory_embeddings` table using a
    NON-384 dimension (1024) WITHOUT a store partition key, plus 3 embedding rows.
    """
    conn = _raw_vec_connection(db_path)
    try:
        _create_memories_table(conn)
        conn.execute(
            f"CREATE VIRTUAL TABLE memory_embeddings USING vec0("
            f"content_embedding FLOAT[{DIM}] distance_metric=cosine)"
        )
        for i in range(3):
            conn.execute(
                "INSERT INTO memory_embeddings (rowid, content_embedding) VALUES (?, ?)",
                (i + 1, _make_embedding(i)),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_migration_preserves_1024_dim_embeddings(tmp_path, monkeypatch):
    """Migrating a legacy 1024-dim DB must keep FLOAT[1024] (not 384) and lose no rows."""
    monkeypatch.setenv("MCP_MEMORY_USE_ONNX", "false")
    db_path = str(tmp_path / "legacy_1024.db")
    _build_legacy_1024_db(db_path)

    storage = SqliteVecMemoryStorage(db_path)
    # strict_dimension_check=False on purpose: these fixtures build a 1024-dim
    # database while the configured model produces 384, so the #143 guard would
    # fire before the migration under test is ever reached. Setting
    # MCP_MEMORY_USE_ONNX=false is not enough -- it only keeps a model out of
    # the way when none of the ml extras are installed, and falls through to
    # SentenceTransformer when they are. The guard has its own tests.
    await storage.initialize(strict_dimension_check=False)
    try:
        sql = storage.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='memory_embeddings'"
        ).fetchone()[0]
        # (a) partition key added AND dimension preserved at 1024 (not 384).
        assert 'partition' in sql.lower(), "partition key not added by migration"
        assert 'FLOAT[1024]' in sql, f"dimension not preserved (got: {sql})"
        assert 'FLOAT[384]' not in sql, "dimension wrongly reset to 384"

        # (b) all 3 embeddings survived.
        count = storage.conn.execute(
            "SELECT COUNT(*) FROM memory_embeddings"
        ).fetchone()[0]
        assert count == 3, "embeddings lost during migration"

        # (c) the crash-safety backup table was cleaned up.
        backup = storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='memory_embeddings_migration_backup'"
        ).fetchone()
        assert backup is None, "migration backup table not cleaned up"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_recovery_restores_from_backup_after_interrupted_migration(tmp_path, monkeypatch):
    """A migration interrupted after the DROP leaves a durable backup + an empty
    already-partitioned vec0 table; the next initialize() must restore the rows.
    """
    monkeypatch.setenv("MCP_MEMORY_USE_ONNX", "false")
    db_path = str(tmp_path / "interrupted.db")

    conn = _raw_vec_connection(db_path)
    try:
        _create_memories_table(conn)
        # Simulate the crashed state: new partitioned (but EMPTY) vec0 table...
        conn.execute(
            f"CREATE VIRTUAL TABLE memory_embeddings USING vec0("
            f"content_embedding FLOAT[{DIM}] distance_metric=cosine, "
            f"store TEXT partition key)"
        )
        # ...and a surviving durable backup with the 3 original rows.
        conn.execute(
            "CREATE TABLE memory_embeddings_migration_backup ("
            "rowid INTEGER, content_embedding BLOB)"
        )
        for i in range(3):
            conn.execute(
                "INSERT INTO memory_embeddings_migration_backup "
                "(rowid, content_embedding) VALUES (?, ?)",
                (i + 1, _make_embedding(i)),
            )
        conn.commit()
    finally:
        conn.close()

    storage = SqliteVecMemoryStorage(db_path)
    # See the note in test_migration_preserves_1024_dim_embeddings.
    await storage.initialize(strict_dimension_check=False)
    try:
        count = storage.conn.execute(
            "SELECT COUNT(*) FROM memory_embeddings"
        ).fetchone()[0]
        assert count == 3, "rows not restored from backup after interrupted migration"

        backup = storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='memory_embeddings_migration_backup'"
        ).fetchone()
        assert backup is None, "backup table not dropped after recovery"
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_recovery_partial_restore_does_not_crash(tmp_path, monkeypatch):
    """A migration interrupted mid-reinsert leaves the new partitioned vec0 table
    with SOME of the backup rows already present. Recovery must restore only the
    missing rows (vec0 rejects INSERT OR IGNORE on rowid conflict), reach 3 rows,
    not raise, and drop the backup.
    """
    monkeypatch.setenv("MCP_MEMORY_USE_ONNX", "false")
    db_path = str(tmp_path / "partial.db")

    conn = _raw_vec_connection(db_path)
    try:
        _create_memories_table(conn)
        conn.execute(
            f"CREATE VIRTUAL TABLE memory_embeddings USING vec0("
            f"content_embedding FLOAT[{DIM}] distance_metric=cosine, "
            f"store TEXT partition key)"
        )
        # One of the three rows already re-inserted before the crash.
        conn.execute(
            "INSERT INTO memory_embeddings (rowid, content_embedding, store) "
            "VALUES (?, ?, ?)",
            (1, _make_embedding(0), 'default'),
        )
        # Durable backup still holds all three original rows.
        conn.execute(
            "CREATE TABLE memory_embeddings_migration_backup ("
            "rowid INTEGER, content_embedding BLOB)"
        )
        for i in range(3):
            conn.execute(
                "INSERT INTO memory_embeddings_migration_backup "
                "(rowid, content_embedding) VALUES (?, ?)",
                (i + 1, _make_embedding(i)),
            )
        conn.commit()
    finally:
        conn.close()

    storage = SqliteVecMemoryStorage(db_path)
    # See the note in test_migration_preserves_1024_dim_embeddings.
    await storage.initialize(strict_dimension_check=False)  # must not raise on the rowid=1 conflict
    try:
        count = storage.conn.execute(
            "SELECT COUNT(*) FROM memory_embeddings"
        ).fetchone()[0]
        assert count == 3, "missing rows not restored during partial recovery"

        backup = storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='memory_embeddings_migration_backup'"
        ).fetchone()
        assert backup is None, "backup table not dropped after partial recovery"
    finally:
        await storage.close()
