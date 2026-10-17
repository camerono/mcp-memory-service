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

"""
Tests that health reporting names the model actually producing the vectors.

With MCP_EXTERNAL_EMBEDDING_URL/MODEL set, `memory_health` and
/api/health/detailed reported "all-MiniLM-L6-v2" while a 1024-dimensional
external model was doing the work (issue #254, reported with the vector
measured: 4096 bytes = 1024 dims). Nothing in the reporting code was
hardcoded -- both surfaces read `storage.embedding_model_name`, and the
external initialisation path set `embedding_model` and `embedding_dimension`
but never the name, so the attribute kept the constructor's local default.

The cache-hit path matters as much as the cold one. The global model cache
makes it the normal path once anything has connected, so setting the name only
on a fresh connect would leave the report wrong nearly everywhere.
"""

from unittest.mock import MagicMock, patch

import pytest

from mcp_memory_service.storage.mixins import embeddings as embeddings_mixin


EXTERNAL_URL = "http://localhost:1234/v1"
EXTERNAL_MODEL = "voyage-4"
LOCAL_DEFAULT = "all-MiniLM-L6-v2"


@pytest.fixture
def external_env(monkeypatch):
    monkeypatch.setenv("MCP_EXTERNAL_EMBEDDING_URL", EXTERNAL_URL)
    monkeypatch.setenv("MCP_EXTERNAL_EMBEDDING_MODEL", EXTERNAL_MODEL)
    monkeypatch.delenv("MCP_EXTERNAL_EMBEDDING_API_KEY", raising=False)
    # sqlite_vec is the only backend that supports external embeddings; hybrid
    # and cloudflare are refused earlier in the same function.
    monkeypatch.setenv("MCP_MEMORY_STORAGE_BACKEND", "sqlite_vec")
    return monkeypatch


@pytest.fixture
def clean_caches(monkeypatch):
    """The model and dimension caches are module globals shared across tests."""
    monkeypatch.setattr(embeddings_mixin, "_MODEL_CACHE", {})
    monkeypatch.setattr(embeddings_mixin, "_DIMENSION_CACHE", {})


@pytest.fixture
def fake_external_model():
    model = MagicMock()
    model.embedding_dimension = 1024
    return model


class _Store(embeddings_mixin.EmbeddingMixin if hasattr(embeddings_mixin, "EmbeddingMixin") else object):
    """Minimal stand-in carrying only what _initialize_embedding_model touches."""

    def __init__(self):
        self.embedding_model = None
        self.embedding_model_name = LOCAL_DEFAULT
        self.embedding_dimension = 384
        self.conn = None


def _storage():
    """Build a store whose _initialize_embedding_model is the real one."""
    from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

    store = SqliteVecMemoryStorage.__new__(SqliteVecMemoryStorage)
    store.embedding_model = None
    store.embedding_model_name = LOCAL_DEFAULT
    store.embedding_dimension = 384
    store.conn = None
    return store


@pytest.mark.asyncio
async def test_fresh_connect_reports_the_external_model(
    external_env, clean_caches, fake_external_model
):
    store = _storage()
    with patch(
        "mcp_memory_service.embeddings.external_api.get_external_embedding_model",
        return_value=fake_external_model,
    ):
        await store._initialize_embedding_model()
    assert store.embedding_model_name == EXTERNAL_MODEL
    assert store.embedding_dimension == 1024


@pytest.mark.asyncio
async def test_cache_hit_also_reports_the_external_model(
    external_env, clean_caches, fake_external_model
):
    """The path every process after the first one takes."""
    first = _storage()
    with patch(
        "mcp_memory_service.embeddings.external_api.get_external_embedding_model",
        return_value=fake_external_model,
    ):
        await first._initialize_embedding_model()

    second = _storage()
    # No patch this time: a cache hit must not call the factory at all.
    with patch(
        "mcp_memory_service.embeddings.external_api.get_external_embedding_model",
        side_effect=AssertionError("cache miss: the factory should not be called"),
    ):
        await second._initialize_embedding_model()

    assert second.embedding_model_name == EXTERNAL_MODEL
    assert second.embedding_dimension == 1024


@pytest.mark.asyncio
async def test_default_external_model_name_is_reported(
    external_env, clean_caches, fake_external_model, monkeypatch
):
    """With the URL set but no model named, the documented default applies and
    must be what gets reported -- not the local model."""
    monkeypatch.delenv("MCP_EXTERNAL_EMBEDDING_MODEL", raising=False)
    store = _storage()
    with patch(
        "mcp_memory_service.embeddings.external_api.get_external_embedding_model",
        return_value=fake_external_model,
    ):
        await store._initialize_embedding_model()
    assert store.embedding_model_name == "nomic-embed-text"


@pytest.mark.asyncio
async def test_local_path_keeps_the_constructor_value(clean_caches, monkeypatch):
    """Without an external URL nothing about the name should change."""
    monkeypatch.delenv("MCP_EXTERNAL_EMBEDDING_URL", raising=False)
    store = _storage()
    try:
        await store._initialize_embedding_model()
    except Exception:
        # Whether a local backend is installed is beside the point here; the
        # name must not have been rewritten either way.
        pass
    assert store.embedding_model_name == LOCAL_DEFAULT


@pytest.mark.asyncio
async def test_health_surface_reports_the_external_name(
    external_env, clean_caches, fake_external_model
):
    """End of the chain: what /api/health/detailed reads off the storage.

    web/api/health.py sets storage_info["embedding_model"] from
    embedding_model_name, so this is the value the dashboard and the MCP tool
    both end up showing.
    """
    store = _storage()
    with patch(
        "mcp_memory_service.embeddings.external_api.get_external_embedding_model",
        return_value=fake_external_model,
    ):
        await store._initialize_embedding_model()

    reported = (
        store.embedding_model_name if hasattr(store, "embedding_model_name") else None
    )
    assert reported == EXTERNAL_MODEL
    assert reported != LOCAL_DEFAULT
