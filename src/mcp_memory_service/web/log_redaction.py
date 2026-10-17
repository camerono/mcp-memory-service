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
Keep credentials out of the HTTP access log.

The dashboard authenticates its SSE connection with the API key in the query
string, because the EventSource API cannot send an Authorization header (see
web/static/app.js). uvicorn's access log records the full request line, so
without this every SSE connection writes the key in cleartext to
~/.local/share/mcp-memory/logs/server.log:

    INFO: 127.0.0.1:57919 - "GET /api/events?api_key=<the actual key> HTTP/1.1" 200 OK

TLS does not help here -- it protects the wire, not the file. The log then
outlives the session and gets pasted into bug reports.

This is the containment half of issue #282. It does not stop the key travelling
in a URL; the fix for that is a short-lived SSE ticket, tracked in the same
issue. Redaction is worth having regardless, since it also covers anything else
that ends up in a query string later.
"""

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: Query parameters whose values must never reach the log. Matched
#: case-insensitively against the parameter name.
SENSITIVE_PARAMS = frozenset({"api_key", "apikey", "token", "access_token", "key"})

REDACTED = "REDACTED"

#: uvicorn's access logger formats "%s - \"%s %s HTTP/%s\" %d" with the request
#: path as the third argument. Anything else is left untouched.
_PATH_ARG_INDEX = 2


def redact_query_string(url: str) -> str:
    """Return `url` with the values of SENSITIVE_PARAMS replaced.

    Parameter names, ordering and everything outside the query string are
    preserved, so the log stays readable and it is still obvious that a key was
    supplied -- just not which one.
    """
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not any(name.lower() in SENSITIVE_PARAMS for name, _ in pairs):
        return url
    cleaned = [
        (name, REDACTED if name.lower() in SENSITIVE_PARAMS else value)
        for name, value in pairs
    ]
    return urlunsplit(parts._replace(query=urlencode(cleaned)))


class RedactQueryStringFilter(logging.Filter):
    """Rewrite the request path in uvicorn access records before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) <= _PATH_ARG_INDEX:
            return True
        path = args[_PATH_ARG_INDEX]
        if not isinstance(path, str) or "?" not in path:
            return True
        redacted = redact_query_string(path)
        if redacted != path:
            record.args = args[:_PATH_ARG_INDEX] + (redacted,) + args[_PATH_ARG_INDEX + 1:]
        return True


def install(logger_name: str = "uvicorn.access") -> bool:
    """Attach the filter to the access logger. Returns True if it was added.

    Attaches to the *logger*, not to its handlers, and that is load-bearing.
    The two launchers set up logging in opposite orders relative to loading the
    app. `python -m uvicorn` builds its Config, which calls dictConfig, and
    only then loads the app; run_http_server.py loads the app first and calls
    uvicorn.run() afterwards. dictConfig removes and re-adds a logger's
    handlers, so a handler-level filter would be dropped in the second case --
    but it never clears filters already attached to the logger itself, so a
    logger-level filter survives both orders.

    Idempotent: repeated calls (module reimport, a test that installs again)
    do not stack duplicate filters.
    """
    logger = logging.getLogger(logger_name)
    if any(isinstance(f, RedactQueryStringFilter) for f in logger.filters):
        return False
    logger.addFilter(RedactQueryStringFilter())
    return True
