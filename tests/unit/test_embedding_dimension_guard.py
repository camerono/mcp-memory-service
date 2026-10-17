"""Guard tests for issue #143: the sqlite_vec backend must fail loudly when the
loaded embedding model's dimension does not match an existing database's vec0
table, instead of silently degrading and only failing later at INSERT time.

Two independent gaps were reported:

1. The default ONNX path ignores the requested model (ONNXEmbeddingModel is
   hardcoded to all-MiniLM-L6-v2 / 384-dim) and logs success, so requesting a
   larger custom model silently loads MiniLM-384.
2. On an existing database, initialization never compared the loaded dimension
   against the vec0 table's FLOAT[N]; the mismatch first surfaced as a hard
   INSERT error far from its cause.

These tests cover the init-time dimension guard (gap 2) and the ONNX honesty
warning (gap 1). They are hermetic: a fixed-dimension model is simulated via
monkeypatch, so no ML backend or model download is required.
"""
import os
import logging

import pytest

os.environ.setdefault('MCP_MEMORY_STORAGE_BACKEND', 'sqlite_vec')

try:
    import sqlite_vec  # noqa: F401
    from sqlite_vec import serialize_float32
    SQLITE_VEC_AVAILABLE = True
except ImportError:
    SQLITE_VEC_AVAILABLE = False

from mcp_memory_service.storage.mixins import embeddings as embeddings_mod
from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

pytestmark = pytest.mark.skipif(not SQLITE_VEC_AVAILABLE, reason="sqlite-vec not available")

DIM = 1024  # existing-database dimension, deliberately != 384


def _raw_vec_connection(db_path: str):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _build_1024_db(db_path: str):
    """Create an existing DB whose vec0 table is FLOAT[1024] with one embedding row."""
    conn = _raw_vec_connection(db_path)
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_hash TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                tags TEXT, memory_type TEXT, metadata TEXT,
                created_at REAL, updated_at REAL,
                created_at_iso TEXT, updated_at_iso TEXT,
                deleted_at REAL DEFAULT NULL
            )
        ''')
        conn.execute("INSERT INTO memories (content_hash, content) VALUES (?, ?)",
                     ("hash_0", "existing content"))
        conn.execute(
            f"CREATE VIRTUAL TABLE memory_embeddings USING vec0("
            f"content_embedding FLOAT[{DIM}] distance_metric=cosine)"
        )
        conn.execute(
            "INSERT INTO memory_embeddings (rowid, content_embedding) VALUES (?, ?)",
            (1, serialize_float32([0.1] * DIM)),
        )
        conn.commit()
    finally:
        conn.close()


def _install_fixed_dim_model(monkeypatch, dim: int = 384):
    """Force _initialize_embedding_model to load a fixed-dimension model that does
    NOT adapt to the existing DB (mimics ONNX MiniLM / a SentenceTransformer)."""
    import numpy as np

    class _FixedModel:
        embedding_dimension = dim

        def encode(self, texts, convert_to_numpy=True):
            return np.zeros((len(texts), dim), dtype="float32")

    async def _fake_init(self):
        self.embedding_model = _FixedModel()
        self.embedding_dimension = dim

    monkeypatch.setattr(embeddings_mod.EmbeddingsMixin, "_initialize_embedding_model", _fake_init)


@pytest.mark.asyncio
async def test_existing_db_dimension_mismatch_raises(monkeypatch, tmp_path):
    """A 384-dim model against a FLOAT[1024] database must raise at init, naming
    both dimensions — not silently proceed to a later INSERT failure."""
    db_path = str(tmp_path / "mismatch_1024.db")
    _build_1024_db(db_path)
    _install_fixed_dim_model(monkeypatch, dim=384)

    storage = SqliteVecMemoryStorage(db_path)
    try:
        with pytest.raises(RuntimeError) as excinfo:
            await storage.initialize()
        msg = str(excinfo.value)
        assert "1024" in msg and "384" in msg, f"error must name both dimensions: {msg}"
    finally:
        if storage.conn:
            storage.conn.close()


@pytest.mark.asyncio
async def test_existing_db_dimension_match_ok(monkeypatch, tmp_path):
    """A model whose dimension matches the existing DB must initialize cleanly."""
    db_path = str(tmp_path / "match_1024.db")
    _build_1024_db(db_path)
    _install_fixed_dim_model(monkeypatch, dim=DIM)  # matches the DB

    storage = SqliteVecMemoryStorage(db_path)
    try:
        await storage.initialize()  # must not raise
        assert storage.embedding_dimension == DIM
    finally:
        if storage.conn:
            storage.conn.close()


@pytest.mark.asyncio
async def test_onnx_custom_model_logs_warning(monkeypatch, tmp_path, caplog):
    """Requesting a non-MiniLM model on the ONNX path must warn that the request is
    not honored (MiniLM-384 served instead), rather than logging plain success."""
    monkeypatch.setenv("MCP_MEMORY_USE_ONNX", "true")
    monkeypatch.delenv("MCP_EXTERNAL_EMBEDDING_URL", raising=False)
    monkeypatch.setattr(embeddings_mod, "_MODEL_CACHE", {})
    monkeypatch.setattr(embeddings_mod, "_DIMENSION_CACHE", {})

    class _FakeOnnx:
        embedding_dimension = 384

        def encode(self, texts, convert_to_numpy=True):
            import numpy as np
            return np.zeros((len(texts), 384), dtype="float32")

    # Simulate ONNX serving only MiniLM regardless of the requested name.
    # _initialize_embedding_model does a function-local `from ...embeddings import
    # get_onnx_embedding_model`, so patch it on the embeddings package.
    import mcp_memory_service.embeddings as emb_pkg
    monkeypatch.setattr(emb_pkg, "get_onnx_embedding_model", lambda name: _FakeOnnx(), raising=False)

    db_path = str(tmp_path / "custom_model.db")
    storage = SqliteVecMemoryStorage(db_path, embedding_model="Qwen/Qwen3-Embedding-0.6B")
    try:
        with caplog.at_level(logging.WARNING, logger=embeddings_mod.logger.name):
            await storage.initialize()
        warned = any(
            "Qwen" in r.getMessage() or "not honored" in r.getMessage().lower()
            or "all-MiniLM" in r.getMessage()
            for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert warned, "expected a warning that the requested model was not honored"
    finally:
        if storage.conn:
            storage.conn.close()
