"""Guard tests for the hash-embedding fallback (upstream issue #135).

When no ML backend is available, the storage layer previously fell back to
``_HashEmbeddingModel`` and silently wrote SHA256 pseudo-vectors into the same
vec0 table as real embeddings — permanently poisoning semantic search on a
database that already held real memories.

These tests simulate "no ML backend available" on a machine where
sentence-transformers *is* installed, by patching the embeddings module's
``SentenceTransformer``/``SENTENCE_TRANSFORMERS_AVAILABLE`` and disabling ONNX
via the environment. They verify:

  (a) a fresh, empty database still falls back to hash embeddings and marks the
      backend as degraded;
  (b) a database that already contains memories refuses the fallback with an
      actionable RuntimeError;
  (c) the ``MCP_MEMORY_ALLOW_HASH_EMBEDDINGS=1`` override re-enables the fallback
      on a non-empty database (for testing).
"""

import os
import shutil
import tempfile

import pytest
import pytest_asyncio

try:
    import sqlite_vec  # inline import: availability probe, the module may be absent  # noqa: F401
    SQLITE_VEC_AVAILABLE = True
except ImportError:
    SQLITE_VEC_AVAILABLE = False

from mcp_memory_service.models.memory import Memory
from mcp_memory_service.utils.hashing import generate_content_hash
from mcp_memory_service.storage import sqlite_vec as sqlite_vec_mod
from mcp_memory_service.storage.mixins import embeddings as embeddings_mod
from mcp_memory_service.storage.mixins.embeddings import _HashEmbeddingModel

pytestmark = pytest.mark.skipif(not SQLITE_VEC_AVAILABLE, reason="sqlite-vec not available")

SqliteVecMemoryStorage = sqlite_vec_mod.SqliteVecMemoryStorage


def _disable_ml_backends(monkeypatch):
    """Simulate 'no ML backend available' regardless of what is installed."""
    # sentence-transformers: both the flag and the symbol are consulted
    # (availability == _st_flag or SentenceTransformer is not None), so patch both.
    monkeypatch.setattr(embeddings_mod, "SentenceTransformer", None)
    monkeypatch.setattr(embeddings_mod, "SENTENCE_TRANSFORMERS_AVAILABLE", False)
    monkeypatch.setattr(sqlite_vec_mod, "SENTENCE_TRANSFORMERS_AVAILABLE", False, raising=False)
    # Avoid cross-test contamination from a cached real model.
    monkeypatch.setattr(embeddings_mod, "_MODEL_CACHE", {})
    monkeypatch.setattr(embeddings_mod, "_DIMENSION_CACHE", {})
    # ONNX is enabled unless explicitly disabled; external API must be off too.
    monkeypatch.setenv("MCP_MEMORY_USE_ONNX", "false")
    monkeypatch.delenv("MCP_EXTERNAL_EMBEDDING_URL", raising=False)


@pytest_asyncio.fixture
async def temp_db_path():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_hash_fallback.db")
    try:
        yield db_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_fresh_empty_db_allows_hash_fallback(monkeypatch, temp_db_path):
    """(a) A fresh, empty DB falls back to hash embeddings and flags degraded mode."""
    _disable_ml_backends(monkeypatch)
    monkeypatch.delenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", raising=False)

    storage = SqliteVecMemoryStorage(temp_db_path)
    try:
        await storage.initialize()

        assert isinstance(storage.embedding_model, _HashEmbeddingModel)
        assert getattr(storage, "embedding_backend_degraded", False) is True
    finally:
        if storage.conn:
            storage.conn.close()


@pytest.mark.asyncio
async def test_non_empty_db_refuses_hash_fallback(monkeypatch, temp_db_path):
    """(b) A DB with existing memories refuses the fallback with an actionable error."""
    _disable_ml_backends(monkeypatch)

    # First, seed one memory using the override so a hash write is allowed.
    monkeypatch.setenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", "1")
    storage = SqliteVecMemoryStorage(temp_db_path)
    await storage.initialize()
    content = "seed memory that must be protected"
    ok, _ = await storage.store(
        Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["seed"],
            memory_type="note",
        )
    )
    assert ok is True
    storage.conn.close()

    # Now reopen with the override removed → the non-empty DB must refuse.
    monkeypatch.delenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", raising=False)
    storage2 = SqliteVecMemoryStorage(temp_db_path)
    try:
        with pytest.raises(RuntimeError) as excinfo:
            await storage2.initialize()
        message = str(excinfo.value)
        assert "MCP_MEMORY_ALLOW_HASH_EMBEDDINGS" in message
        # Exactly one memory was seeded above, and it has one embedding row.
        # The message used to report the sum of both tables as a memory count,
        # so it said "2 existing memories" here and roughly double the truth on
        # a real database (#228). Asserting the phrasing keeps that from
        # regressing quietly.
        assert "1 memories and 1 embedding rows" in message, message
        assert "2 existing memories" not in message
    finally:
        if storage2.conn:
            storage2.conn.close()


@pytest.mark.asyncio
async def test_non_empty_db_override_allows_hash_fallback(monkeypatch, temp_db_path):
    """(c) MCP_MEMORY_ALLOW_HASH_EMBEDDINGS=1 re-enables the fallback on a non-empty DB."""
    _disable_ml_backends(monkeypatch)
    monkeypatch.setenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", "1")

    # Seed one memory.
    storage = SqliteVecMemoryStorage(temp_db_path)
    await storage.initialize()
    content = "seed memory for override case"
    ok, _ = await storage.store(
        Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["seed"],
            memory_type="note",
        )
    )
    assert ok is True
    storage.conn.close()

    # Reopen with the override still set → initialization must succeed.
    storage2 = SqliteVecMemoryStorage(temp_db_path)
    try:
        await storage2.initialize()
        assert isinstance(storage2.embedding_model, _HashEmbeddingModel)
        assert getattr(storage2, "embedding_backend_degraded", False) is True
    finally:
        if storage2.conn:
            storage2.conn.close()
