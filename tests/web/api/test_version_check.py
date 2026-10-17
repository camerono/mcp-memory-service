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
Tests for GET /api/version/check git remote/branch configurability (#27).

The update check used to hardcode `origin` / `origin/main`, which broke for
installs whose remote is named differently (codeberg, upstream, ...) or that
track a non-main branch. The remote and branch are now read from
MCP_UPDATE_GIT_REMOTE / MCP_UPDATE_GIT_BRANCH, defaulting to origin/main.

`check_for_updates` ignores its `user` arg (auth is enforced by the
Depends(require_admin_access) at the route layer), so the handler is called
directly with user=None and `_run_git_command` patched to a recorder.
"""

import pytest
from unittest.mock import patch

from mcp_memory_service.web.api import server as server_module


def _make_runner(calls, count="0", log=""):
    """Record git invocations and return canned (output, success) tuples."""
    def _runner(args):
        calls.append(args)
        if args[:2] == ['rev-list', '--count']:
            return (count, True)
        if args[:1] == ['log']:
            return (log, True)
        return ("", True)  # fetch and anything else
    return _runner


@pytest.mark.asyncio
async def test_version_check_defaults_to_origin_main(monkeypatch):
    monkeypatch.delenv('MCP_UPDATE_GIT_REMOTE', raising=False)
    monkeypatch.delenv('MCP_UPDATE_GIT_BRANCH', raising=False)

    calls = []
    with patch.object(server_module, '_run_git_command', _make_runner(calls)):
        resp = await server_module.check_for_updates(user=None)

    assert ['fetch', 'origin'] in calls
    rev_list = [c for c in calls if c[:2] == ['rev-list', '--count']]
    assert rev_list and rev_list[0][2] == 'HEAD..origin/main'
    assert resp.git_available is True


@pytest.mark.asyncio
async def test_version_check_honors_custom_remote_and_branch(monkeypatch):
    monkeypatch.setenv('MCP_UPDATE_GIT_REMOTE', 'codeberg')
    monkeypatch.setenv('MCP_UPDATE_GIT_BRANCH', 'develop')

    calls = []
    runner = _make_runner(calls, count="3", log="abc123 fix: a\ndef456 feat: b")
    with patch.object(server_module, '_run_git_command', runner):
        resp = await server_module.check_for_updates(user=None)

    # fetch targets the configured remote
    assert ['fetch', 'codeberg'] in calls
    # rev-list + log compare against the configured upstream ref
    rev_list = [c for c in calls if c[:2] == ['rev-list', '--count']]
    assert rev_list and rev_list[0][2] == 'HEAD..codeberg/develop'
    log_calls = [c for c in calls if c[:1] == ['log']]
    assert log_calls and 'HEAD..codeberg/develop' in log_calls[0]

    assert resp.commits_behind == 3
    assert resp.update_available is True
    assert resp.latest_commits == ['abc123 fix: a', 'def456 feat: b']


@pytest.mark.asyncio
async def test_version_check_no_log_when_up_to_date(monkeypatch):
    monkeypatch.setenv('MCP_UPDATE_GIT_REMOTE', 'upstream')
    monkeypatch.setenv('MCP_UPDATE_GIT_BRANCH', 'main')

    calls = []
    with patch.object(server_module, '_run_git_command', _make_runner(calls, count="0")):
        resp = await server_module.check_for_updates(user=None)

    assert ['fetch', 'upstream'] in calls
    # zero commits behind -> the log command is skipped entirely
    assert not [c for c in calls if c[:1] == ['log']]
    assert resp.commits_behind == 0
    assert resp.update_available is False
