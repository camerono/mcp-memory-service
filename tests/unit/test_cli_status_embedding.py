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
Tests for the `memory status` embedding-health checks (issue #136).

`status` must not merely report storage stats and claim "healthy"; it has to
surface which embedding backend actually loaded, compare the model's output
dimension against the vec0 table's declared FLOAT[N], and (with --deep) prove a
memory can round-trip store→search→delete.

The status command loads the storage backend and (in the default path) a real
embedding model, and it reads its DB path from the ``config`` module which
caches ``SQLITE_VEC_PATH`` at import time. To keep these tests hermetic,
offline, and immune to config-caching across the wider suite, each case runs the
command in a fresh subprocess with its own temp DB and env — the same isolation
strategy used by tests/unit/test_cli_lazy.py.
"""

import subprocess
import sys
import tempfile
import textwrap
import os


def _run_status(script_body: str, db_path: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a status-related snippet in a subprocess with a hermetic sqlite-vec env."""
    env = dict(os.environ)
    env.update({
        "MCP_MEMORY_STORAGE_BACKEND": "sqlite_vec",
        "MCP_MEMORY_SQLITE_PATH": db_path,
        # Skip the ONNX path so the SentenceTransformer/hash decision is ours to force.
        "MCP_MEMORY_USE_ONNX": "0",
        # Never reach out to Hugging Face during tests.
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    })
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script_body)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )


# Lines that force the pure-Python hash embedding fallback (no ML model load).
# Kept flush-left so callers can prepend them to an already-dedented body.
_FORCE_HASH = (
    "import mcp_memory_service.storage.mixins.embeddings as emb\n"
    "emb.SENTENCE_TRANSFORMERS_AVAILABLE = False\n"
    "emb.SentenceTransformer = None\n"
)


def test_get_storage_passes_configured_embedding_model():
    """CLI sqlite-vec storage must use MCP_EMBEDDING_MODEL, not its default."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "status.db")
        configured_model = "test/configured-embedding-model"
        result = _run_status(
            """
            import asyncio
            from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

            captured = {}

            def fake_init(self, db_path, embedding_model="constructor-default"):
                captured["embedding_model"] = embedding_model

            async def fake_initialize(self, strict_dimension_check=True):
                pass

            SqliteVecMemoryStorage.__init__ = fake_init
            SqliteVecMemoryStorage.initialize = fake_initialize

            from mcp_memory_service.cli.utils import get_storage
            asyncio.run(get_storage("sqlite_vec"))
            print(captured["embedding_model"])
            """,
            db_path,
            {"MCP_EMBEDDING_MODEL": configured_model},
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == configured_model


def test_status_reports_degraded_hash_backend_and_exits_1():
    """Fresh DB with the hash fallback active -> degraded verdict, exit code 1.

    On an empty DB the vec0 table is created from the model's dimension, so the
    dimensions always match; the meaningful failure here is that hash
    pseudo-embeddings are active and semantic search is non-functional.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "status.db")
        result = _run_status(_FORCE_HASH + textwrap.dedent("""
            from click.testing import CliRunner
            from mcp_memory_service.cli.main import cli
            r = CliRunner().invoke(cli, ['status'])
            print(r.output)
            print('EXIT', r.exit_code)
        """), db_path)

        out = result.stdout
        assert "EXIT 1" in out, f"Expected exit 1.\nstdout:\n{out}\nstderr:\n{result.stderr}"
        assert "_HashEmbeddingModel" in out, f"Backend class not reported:\n{out}"
        assert "degraded: hash pseudo-embeddings active" in out, f"Degraded verdict missing:\n{out}"
        assert "❌ Service is NOT healthy" in out, f"Unhealthy summary missing:\n{out}"
        # Must not falsely claim healthy.
        assert "✅ Service is healthy" not in out


def test_status_detects_dimension_mismatch_and_exits_1():
    """Model dimension (384) != vec0 table FLOAT[1024] -> mismatch verdict, exit 1.

    Builds a DB whose ``memory_embeddings`` table is FLOAT[1024] (via a stub
    1024-dim model), then runs status with a stub 384-dim model so the model and
    table dimensions genuinely disagree.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "status.db")
        result = _run_status("""
            import asyncio
            import numpy as np
            from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

            DIM = {'v': 1024}

            class StubModel:
                def __init__(self, d):
                    self.embedding_dimension = d
                def encode(self, texts, convert_to_numpy=False):
                    return np.zeros((len(texts), self.embedding_dimension), dtype='float32')

            async def fake_init(self):
                self.embedding_model = StubModel(DIM['v'])
                self.embedding_dimension = DIM['v']

            SqliteVecMemoryStorage._initialize_embedding_model = fake_init

            from mcp_memory_service.cli.utils import get_storage

            # Step 1: build a DB with a FLOAT[1024] vec0 table.
            async def build():
                s = await get_storage('sqlite_vec')
                await s.close()
            asyncio.run(build())

            # Step 2: run status with a model that now reports dimension 384.
            DIM['v'] = 384
            from click.testing import CliRunner
            from mcp_memory_service.cli.main import cli
            r = CliRunner().invoke(cli, ['status'])
            print(r.output)
            print('EXIT', r.exit_code)
        """, db_path)

        out = result.stdout
        assert "EXIT 1" in out, f"Expected exit 1.\nstdout:\n{out}\nstderr:\n{result.stderr}"
        assert "Model dimension: 384" in out, f"Model dimension not reported:\n{out}"
        assert "Database dimension: 1024" in out, f"DB dimension not reported:\n{out}"
        assert "dimension mismatch: model outputs 384, database table is FLOAT[1024]" in out, \
            f"Mismatch verdict missing:\n{out}"
        assert "❌ Service is NOT healthy" in out


def test_status_deep_round_trip_reports_each_step():
    """--deep exercises a real store→search→delete round trip and prints each step."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "status.db")
        result = _run_status(_FORCE_HASH + textwrap.dedent("""
            from click.testing import CliRunner
            from mcp_memory_service.cli.main import cli
            r = CliRunner().invoke(cli, ['status', '--deep'])
            print(r.output)
            print('EXIT', r.exit_code)
        """), db_path)

        out = result.stdout
        assert "Deep round-trip smoke test" in out, f"Deep section missing:\n{out}"
        assert "✅ store:" in out, f"store step missing:\n{out}"
        assert "✅ search:" in out, f"search step missing:\n{out}"
        assert "✅ delete:" in out, f"delete step missing:\n{out}"
        assert "✅ verify:" in out, f"verify step missing:\n{out}"
