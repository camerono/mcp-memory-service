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
Request body-size limiting ASGI middleware.

Caps how many bytes a request may send so a caller cannot exhaust memory/disk
(e.g. by looping unbounded form fields) or attempt a buffer-overflow style
flood. Two tiers:

* ``/oauth/*`` auth endpoints — tight cap (default 64 KiB).
* everything else — global cap (default 1 MiB).

Large-upload routes (document ingestion under ``/api/documents``) are exempt
because they legitimately stream multi-megabyte files.

Both the declared ``Content-Length`` and the actually-streamed byte count are
enforced, so a missing/forged header or chunked transfer cannot bypass the cap.
"""

import json
import logging

from ..config import HTTP_MAX_BODY_BYTES, OAUTH_MAX_BODY_BYTES

logger = logging.getLogger(__name__)

# Routes that legitimately accept large bodies and must not be capped.
_EXEMPT_PREFIXES = ("/api/documents",)
_AUTH_PREFIXES = ("/oauth",)


def _limit_for_path(path: str) -> int | None:
    """Return the byte cap for ``path``, or None when the path is exempt."""
    for prefix in _EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return None
    for prefix in _AUTH_PREFIXES:
        if path.startswith(prefix):
            return OAUTH_MAX_BODY_BYTES
    return HTTP_MAX_BODY_BYTES


class BodySizeLimitMiddleware:
    """Pure ASGI middleware enforcing a per-route request body-size cap."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = _limit_for_path(scope.get("path", ""))
        if limit is None:
            await self.app(scope, receive, send)
            return

        # Fast path: reject immediately on a declared Content-Length over the cap.
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except (ValueError, TypeError):
                    declared = None
                if declared is not None and declared > limit:
                    await self._reject(send, limit)
                    return
                break

        state = {
            "received": 0,
            "over_limit": False,
            "rejected": False,
            "response_started": False,
        }

        async def receive_wrapper():
            # Once the body is known to be over the limit, stop feeding real
            # data to the app: hand it a disconnect so its body parser unwinds.
            if state["over_limit"]:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                state["received"] += len(message.get("body", b""))
                if state["received"] > limit:
                    state["over_limit"] = True
                    message["more_body"] = False
            return message

        async def guarded_send(message):
            # Suppress the downstream response and emit 413 exactly once.
            if state["over_limit"]:
                # If the app already emitted its response start, the status line
                # and headers are on the wire — we can no longer inject a 413
                # without a duplicate http.response.start (RuntimeError). Stop
                # sending instead. (Not reachable for OAuth/JSON routes, which
                # read the whole body before responding, but guards streaming
                # handlers that flush headers early.)
                if state["response_started"]:
                    return
                if not state["rejected"]:
                    state["rejected"] = True
                    await self._reject(send, limit)
                return
            if message["type"] == "http.response.start":
                state["response_started"] = True
            await send(message)

        await self.app(scope, receive_wrapper, guarded_send)

        # The app may finish without sending anything (e.g. it raised after the
        # disconnect). Ensure the client still gets a 413 — but only if no
        # response start has gone out yet.
        if state["over_limit"] and not state["rejected"] and not state["response_started"]:
            await self._reject(send, limit)

    @staticmethod
    async def _reject(send, limit: int) -> None:
        body = json.dumps(
            {
                "error": "payload_too_large",
                "error_description": f"Request body exceeds the maximum of {limit} bytes",
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
