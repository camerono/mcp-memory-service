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
A test that changes the process timezone has to give it back.

monkeypatch.setenv("TZ", ...) plus time.tzset() looks like it does, and does not:
the variable is restored during teardown, after the test body, so a tzset() in a
finally block still reads the overridden value. Nothing calls tzset() once the
variable is back, so the C library keeps the test's timezone for every later test
in the same worker. The suite stayed green because nothing in it depends on local
time — which is luck, not isolation.

These two tests run in order and check the property directly: the second one uses
no fixture and asserts that the first one left nothing behind.
"""

import os
import time

import pytest

# Captured at import, before any test in this file has touched the timezone.
BASELINE_TZNAME = time.tzname
BASELINE_TZ_ENV = os.environ.get("TZ")

# Two zones, so the assertions cannot pass by accident on a machine that already
# runs in one of them.
ELSEWHERE = "Asia/Tokyo" if BASELINE_TZNAME[0] != "JST" else "America/Los_Angeles"


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset is POSIX-only")
def test_fixture_applies_the_timezone(local_timezone):
    local_timezone(ELSEWHERE)

    assert os.environ["TZ"] == ELSEWHERE
    assert time.tzname != BASELINE_TZNAME


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset is POSIX-only")
def test_the_timezone_is_restored_for_whatever_runs_next():
    """No fixture here on purpose — this is a later test, and it must see the
    timezone the worker started with."""
    assert time.tzname == BASELINE_TZNAME
    assert os.environ.get("TZ") == BASELINE_TZ_ENV
