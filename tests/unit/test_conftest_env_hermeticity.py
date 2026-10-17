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
Guards the harness against embedding settings leaking in from the host.

conftest pins the storage backend and the database path but used to leave
MCP_EMBEDDING_MODEL alone, so whatever a developer had exported chose the model
and with it the vector width. Three tests in
test_multi_store_migration_dimension.py built 1024-dimensional vec0 tables and
then loaded the 384-dimensional default, failing on one machine and passing on
another -- which a contributor reasonably read as breakage in the tree (#234).

These assert the invariant directly rather than through that downstream symptom.
Reproducing the symptom needs a *cached* 1024-dimensional model, because
conftest also sets MCP_MEMORY_ONNX_ALLOW_DOWNLOAD=0 and an uncached model falls
back to 384-dimensional hash embeddings -- which is exactly why the original
failure looked like flakiness that came and went between machines.
"""

import os
import subprocess
import sys

import pytest

#: Settings that decide the embedding dimension. Anything here must not reach a
#: test run from the ambient environment.
DIMENSION_VARS = (
    "MCP_EMBEDDING_MODEL",
    "MCP_MEMORY_USE_ONNX",
    "MCP_EXTERNAL_EMBEDDING_URL",
    "MCP_EXTERNAL_EMBEDDING_MODEL",
    "MCP_EXTERNAL_EMBEDDING_API_KEY",
)


@pytest.mark.parametrize("var", DIMENSION_VARS)
def test_dimension_var_is_not_set_during_tests(var):
    """conftest runs at import time, so by the time any test body runs these
    must already be gone."""
    assert var not in os.environ, (
        f"{var}={os.environ.get(var)!r} leaked into the test environment; "
        "the embedding dimension is no longer deterministic"
    )


def test_a_host_value_does_not_survive_into_a_run():
    """The property that matters, exercised end to end.

    A nested pytest run is the only honest way to test this. conftest scrubs
    while it is being imported, so within this process the value is already
    gone, and setting it here would prove nothing about what conftest did.
    """
    env = {
        **os.environ,
        "MCP_EMBEDDING_MODEL": "intfloat/multilingual-e5-large",
        "MCP_EXTERNAL_EMBEDDING_URL": "http://should-not-survive.invalid/v1",
    }
    # The nested run's own parametrised tests are the assertion: they check the
    # variables are absent, and they run with this polluted environment as their
    # parent. A green exit therefore means conftest removed the values on import.
    # Asserting on conftest's log line instead would be brittle -- pytest
    # captures module-level output, so it does not reliably reach stdout.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
         "tests/unit/test_conftest_env_hermeticity.py",
         "-k", "test_dimension_var_is_not_set_during_tests", "-q"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        "a host-set embedding variable survived into a test run:\n" + combined[-3000:]
    )
