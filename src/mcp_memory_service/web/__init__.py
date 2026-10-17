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
Web interface for MCP Memory Service.

Provides HTTP REST API and Server-Sent Events (SSE) interface
using FastAPI and SQLite-vec backend.
"""

try:
    from .. import __version__
except (ImportError, AttributeError):
    __version__ = "0.0.0.dev0"

# Installed here rather than in app.py's lifespan so it is in place no matter
# how the server is started, and before the first request is ever logged. See
# log_redaction.install() for why the ordering works out for both launchers.
from .log_redaction import install as _install_log_redaction

_install_log_redaction()