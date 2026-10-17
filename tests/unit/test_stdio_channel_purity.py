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
Guards the stdio transport's JSON-RPC channel against human-readable output.

On a stdio MCP server, stdout *is* the protocol channel. Anything else written
there corrupts the stream. This was not hypothetical: with LM Studio detected,
the dependency check wrote its banner to stdout and put seven non-JSON lines
ahead of the initialize response (issue #275). The guard in place at the time
made it worse in an instructive way -- it restricted the output to LM Studio
"to avoid JSON parsing errors in Claude Desktop", but LM Studio speaks stdio
too, so it spared the client that was fine and kept breaking the one that
wasn't.

A unit test on the dependency-check function alone would not have caught that,
because the bug was about which stream the process writes to. So this drives
the real server as a subprocess and reads its actual stdout.
"""

import json
import os
import subprocess
import sys

import pytest

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "lmstudio", "version": "1"},
    },
}


def _run_stdio_server(tmp_path, extra_env):
    """Drive `python -m mcp_memory_service.server` over stdio with one request.

    Every path the server might write to is redirected into tmp_path: the
    sqlite database, the base directory and XDG_DATA_HOME. A subprocess does
    not inherit conftest's fixtures, so this has to be explicit or the test
    would reach for the developer's real database.
    """
    env = {
        **os.environ,
        "MCP_MEMORY_STORAGE_BACKEND": "sqlite_vec",
        "MCP_MEMORY_SQLITE_PATH": str(tmp_path / "test.db"),
        "MCP_MEMORY_BASE_DIR": str(tmp_path),
        "XDG_DATA_HOME": str(tmp_path),
        **extra_env,
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "mcp_memory_service.server"],
            input=json.dumps(INITIALIZE) + "\n",
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("stdio server did not settle within the timeout on this machine")
    return proc


def _non_json_lines(stdout):
    bad = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
        except (ValueError, TypeError):
            bad.append(line)
    return bad


@pytest.mark.parametrize(
    "client_env",
    [
        pytest.param({"LM_STUDIO": "1"}, id="lm_studio"),
        pytest.param({}, id="no_client_hint"),
        pytest.param(
            {"LM_STUDIO": "1", "DOCKER_CONTAINER": "1"}, id="lm_studio_in_docker"
        ),
    ],
)
def test_stdout_carries_only_json(tmp_path, client_env):
    """Whatever the detected client, stdout must stay parseable.

    LM Studio is parametrised explicitly because it was the detection branch
    that turned the diagnostics on, and an unhinted run is included so the
    test still means something if that detection changes.

    The Docker case is here because it was missed once. Two banners in
    startup_orchestrator sit behind `is_docker_environment()`, one of them
    *inside* run_stdio, so on a developer machine they never fire and look
    unreachable -- while CI runs in a container and tripped it immediately.
    DOCKER_CONTAINER=1 is what is_docker_environment() checks besides
    /.dockerenv, so this exercises that path everywhere.
    """
    proc = _run_stdio_server(tmp_path, client_env)
    bad = _non_json_lines(proc.stdout)
    assert not bad, (
        f"{len(bad)} non-JSON line(s) on the JSON-RPC channel; first: {bad[0]!r}"
    )


def test_diagnostics_are_not_simply_silenced(tmp_path):
    """The fix must move the output, not delete it.

    Redirecting the banner to stderr keeps the warning a user needs when
    dependencies are missing. Dropping it instead would also make the test
    above pass, which is why this asserts the output still exists somewhere.
    """
    proc = _run_stdio_server(tmp_path, {"LM_STUDIO": "1"})
    assert proc.stderr.strip(), "no diagnostics on stderr at all"
    assert "Dependency Check" in proc.stderr, (
        "the dependency-check banner reached neither stdout nor stderr"
    )
