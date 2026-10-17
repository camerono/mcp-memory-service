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
Tests that the LM Studio compatibility patches actually apply.

This module monkey-patches MCP SDK internals by name, which is fragile by
design: when the SDK renames or removes a target, the `hasattr` guards make the
patch quietly stop running. That is not hypothetical -- Patch 2 wrapped
BaseSession._handle_notification, which the SDK no longer has, and it went
unnoticed until a dependency bump happened to look. Nothing failed, nothing
logged a warning, and the compatibility guarantee silently got thinner.

These tests are the missing alarm: at least one patch must apply, the surviving
targets must actually be replaced, and the removed target must still be absent.
"""

import mcp.shared.session as session_module
import pytest
from mcp.shared.session import BaseSession

from mcp_memory_service import lm_studio_compat


@pytest.fixture
def restore_sdk():
    """Undo the global mutation these patches perform.

    patch_mcp_for_lm_studio() rebinds attributes on SDK classes and modules
    process-wide. Without restoring them, any later test touching MCP session
    machinery would silently run against patched internals."""
    sentinel = object()
    saved = {
        (BaseSession, "_receive_loop"): getattr(BaseSession, "_receive_loop", sentinel),
        (session_module, "CancelledNotification"): getattr(
            session_module, "CancelledNotification", sentinel
        ),
    }
    client_notification = getattr(session_module, "ClientNotification", None)
    if client_notification is not None:
        saved[(client_notification, "model_validate")] = client_notification.model_validate

    yield

    for (target, name), value in saved.items():
        if value is sentinel:
            if hasattr(target, name):
                delattr(target, name)
        else:
            setattr(target, name, value)


def test_at_least_one_patch_applies(restore_sdk):
    """The alarm. A False return means every target has drifted away and LM
    Studio compatibility is gone -- which is exactly the state Patch 2 reached
    on its own, without anything noticing."""
    assert lm_studio_compat.patch_mcp_for_lm_studio() is True


def test_receive_loop_is_actually_replaced(restore_sdk):
    """Patch 3 carries the behaviour on its own now that Patch 2 is gone, so a
    silent drift here would leave nothing suppressing the cancelled
    notification error."""
    before = BaseSession._receive_loop
    lm_studio_compat.patch_mcp_for_lm_studio()
    assert BaseSession._receive_loop is not before


def test_handle_notification_is_still_absent():
    """Canary for the patch removed from lm_studio_compat.py.

    BaseSession._handle_notification does not exist in the SDK and did not
    exist at 1.27.1 either, so the wrapper was dead code. If a future SDK
    reintroduces it, this fails -- and re-adding a patch becomes a deliberate
    decision rather than something rediscovered by accident."""
    assert not hasattr(BaseSession, "_handle_notification"), (
        "BaseSession._handle_notification is back in the MCP SDK. Decide "
        "whether lm_studio_compat needs to wrap it again; see issue #283."
    )
